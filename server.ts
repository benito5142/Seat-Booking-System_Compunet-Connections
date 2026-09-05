import express from 'express';
import path from 'path';
import { spawn } from 'child_process';
import http from 'http';
import { createProxyMiddleware, fixRequestBody } from 'http-proxy-middleware';
import { createServer as createViteServer } from 'vite';

const PORT = 3000;

function checkBackendHealth(): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get('http://127.0.0.1:8001/api/health', { timeout: 1000 }, (res) => {
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => {
      req.destroy();
      resolve(false);
    });
  });
}

let backendIsHealthy = false;

// In-memory fallback state for standalone Node deployments where Python is unavailable
const ROWS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J'];
const SEATS_PER_ROW = 12;

interface ServerSeat {
  id: string;
  row: string;
  seat_number: number;
  status: 'available' | 'held' | 'booked';
}

interface ServerHold {
  id: number;
  hold_token: string;
  seats: string[];
  expires_at: string;
  status: 'held' | 'released' | 'confirmed';
  user_id: string;
}

let serverSeats: ServerSeat[] = [];
let serverHolds: ServerHold[] = [];
let serverBookings: Array<{
  booking_id: number;
  booking_reference: string;
  seats: string[];
  confirmed_at: string;
  user_id: string;
  total_amount: number;
  currency: string;
}> = [];

function initServerSeats() {
  serverSeats = [];
  for (const row of ROWS) {
    for (let col = 1; col <= SEATS_PER_ROW; col++) {
      serverSeats.push({
        id: `${row}${col}`,
        row,
        seat_number: col,
        status: 'available',
      });
    }
  }
}
initServerSeats();

function sweepServerHolds() {
  const now = Date.now();
  const seatMap = new Map(serverSeats.map((s) => [s.id, s]));
  for (const hold of serverHolds) {
    if (hold.status === 'held') {
      if (new Date(hold.expires_at).getTime() <= now) {
        hold.status = 'released';
        for (const sId of hold.seats) {
          const s = seatMap.get(sId);
          if (s && s.status === 'held') {
            s.status = 'available';
          }
        }
      }
    }
  }
}

async function ensureBackend(): Promise<void> {
  backendIsHealthy = await checkBackendHealth();
  if (backendIsHealthy) {
    console.log('[Server] Python backend is already running and healthy.');
    return;
  }

  console.log('[Server] Launching Python backend via start_backend.py...');
  try {
    spawn('python3', ['start_backend.py'], {
      stdio: 'inherit',
      cwd: process.cwd(),
    });
  } catch (e) {
    console.warn('[Server] python3 not available, native Express fallback will serve API.');
    return;
  }

  // Wait up to 15 seconds for backend to become healthy
  for (let i = 0; i < 30; i++) {
    await new Promise((r) => setTimeout(r, 500));
    if (await checkBackendHealth()) {
      backendIsHealthy = true;
      console.log('[Server] Python backend is now healthy on http://127.0.0.1:8001');
      return;
    }
  }
  console.warn('[Server] Warning: Python backend did not report healthy. Using native Express API.');
}

async function startServer() {
  const app = express();
  app.use(express.json());

  // 1. Ensure Python FastAPI backend is started
  await ensureBackend();

  // 2. Proxy API routes to Python backend on port 8001 when healthy
  const apiProxy = createProxyMiddleware({
    target: 'http://127.0.0.1:8001',
    changeOrigin: true,
    on: {
      proxyReq: fixRequestBody,
      error: (err, req, res) => {
        console.error('[API Proxy Error]', req.method, req.url, err.message);
        backendIsHealthy = false;
        const resObj = res as express.Response;
        if (resObj && !resObj.headersSent && typeof resObj.status === 'function') {
          resObj.status(502).json({
            detail: 'Seat booking service is warming up or temporarily busy. Please retry.',
          });
        }
      },
    },
  });

  // Health route
  app.get('/api/health', async (req, res, next) => {
    if (backendIsHealthy) {
      return apiProxy(req, res, next);
    }
    res.json({
      status: 'ok',
      service: 'seat-booking-native-engine',
      environment: process.env.NODE_ENV || 'development',
    });
  });

  // Event info route
  app.get('/api/event/info', (req, res, next) => {
    if (backendIsHealthy) {
      return apiProxy(req, res, next);
    }
    res.json({
      event_id: 1,
      name: 'Main Event - Sci-Fi Concert Premiere',
      seat_map: { rows: 10, seats_per_row: 12, total_seats: 120 },
    });
  });

  // Seats route
  app.get('/seats', (req, res, next) => {
    if (backendIsHealthy) {
      return apiProxy(req, res, next);
    }
    sweepServerHolds();
    res.json(serverSeats);
  });

  // Holds route
  app.post('/holds', (req, res, next) => {
    if (backendIsHealthy) {
      return apiProxy(req, res, next);
    }
    sweepServerHolds();
    const { seats, user_id } = req.body || {};
    if (!Array.isArray(seats) || seats.length === 0) {
      return res.status(400).json({ detail: 'At least one seat must be specified' });
    }
    if (seats.length > 4) {
      return res.status(400).json({ detail: 'Cannot hold more than 4 seats' });
    }

    const seatMap = new Map(serverSeats.map((s) => [s.id, s]));
    const unavailable: string[] = [];
    for (const sId of seats) {
      const s = seatMap.get(sId);
      if (!s || s.status !== 'available') {
        unavailable.push(sId);
      }
    }

    if (unavailable.length > 0) {
      return res.status(409).json({
        detail: {
          message: `One or more requested seats are unavailable: ${unavailable.join(', ')}`,
          unavailable_seats: unavailable,
        },
      });
    }

    const holdId = Date.now();
    const holdToken = Math.random().toString(36).substring(2, 15);
    const expiresAt = new Date(Date.now() + 300 * 1000).toISOString();

    for (const sId of seats) {
      const s = seatMap.get(sId);
      if (s) s.status = 'held';
    }

    const newHold: ServerHold = {
      id: holdId,
      hold_token: holdToken,
      seats: [...seats],
      expires_at: expiresAt,
      status: 'held',
      user_id: user_id || 'user_1',
    };
    serverHolds.push(newHold);

    res.status(201).json({
      id: holdId,
      hold_id: holdId,
      hold_token: holdToken,
      seats,
      expires_at: expiresAt,
      expires_in_seconds: 300,
      status: 'held',
      user_id: user_id || 'user_1',
    });
  });

  // Release hold
  app.delete('/holds/:id', (req, res, next) => {
    if (backendIsHealthy) {
      return apiProxy(req, res, next);
    }
    sweepServerHolds();
    const holdId = req.params.id;
    const hold = serverHolds.find(
      (h) => String(h.id) === String(holdId) || h.hold_token === String(holdId)
    );
    if (!hold) {
      return res.status(404).json({ detail: 'Hold not found' });
    }
    hold.status = 'released';
    const seatMap = new Map(serverSeats.map((s) => [s.id, s]));
    for (const sId of hold.seats) {
      const s = seatMap.get(sId);
      if (s && s.status === 'held') s.status = 'available';
    }
    res.json({ status: 'released', message: 'Hold successfully released' });
  });

  // Confirm booking
  app.post('/bookings', (req, res, next) => {
    if (backendIsHealthy) {
      return apiProxy(req, res, next);
    }
    sweepServerHolds();
    const { hold_id, user_id } = req.body || {};
    const hold = serverHolds.find(
      (h) => String(h.id) === String(hold_id) || h.hold_token === String(hold_id)
    );
    if (!hold || hold.status !== 'held') {
      return res.status(400).json({ detail: 'Hold not found or has expired' });
    }
    hold.status = 'confirmed';
    const seatMap = new Map(serverSeats.map((s) => [s.id, s]));
    for (const sId of hold.seats) {
      const s = seatMap.get(sId);
      if (s) s.status = 'booked';
    }
    const bookingRef = `BK-${Math.random().toString(36).substring(2, 8).toUpperCase()}`;
    const booking = {
      booking_id: Date.now(),
      booking_reference: bookingRef,
      seats: [...hold.seats],
      confirmed_at: new Date().toISOString(),
      user_id: user_id || 'user_1',
      total_amount: hold.seats.length * 250,
      currency: 'INR',
    };
    serverBookings.push(booking);
    res.status(201).json({
      booking_id: booking.booking_id,
      booking_reference: bookingRef,
      hold_token: hold.hold_token,
      seats: hold.seats,
      confirmed_at: booking.confirmed_at,
      total_amount: booking.total_amount,
      currency: 'INR',
      message: 'Booking successfully confirmed',
    });
  });

  // Reset route
  app.post('/api/reset', (req, res, next) => {
    if (backendIsHealthy) {
      return apiProxy(req, res, next);
    }
    initServerSeats();
    serverHolds = [];
    serverBookings = [];
    res.json({ success: true, message: 'All 120 seats reset to Available' });
  });

  // Catch-all API fallback to proxy
  app.use((req, res, next) => {
    const p = req.path;
    if (
      p.startsWith('/seats') ||
      p.startsWith('/holds') ||
      p.startsWith('/bookings') ||
      p.startsWith('/api')
    ) {
      return apiProxy(req, res, next);
    }
    next();
  });

  // 3. Vite middleware for development vs Static files in production
  if (process.env.NODE_ENV !== 'production') {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*', (req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`Server running on http://0.0.0.0:${PORT}`);
  });
}

startServer();
