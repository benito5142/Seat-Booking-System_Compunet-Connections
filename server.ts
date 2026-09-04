import express, { Request, Response, NextFunction } from 'express';
import path from 'path';
import { fileURLToPath } from 'url';
import { createServer as createViteServer } from 'vite';
import crypto from 'crypto';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = 3000;

// Middleware
app.use((req: Request, res: Response, next: NextFunction) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Origin, X-Requested-With, Content-Type, Accept, Authorization');
  if (req.method === 'OPTIONS') {
    return res.sendStatus(200);
  }
  next();
});
app.use(express.json());

// In-Memory Data Models & State
interface Seat {
  id: string;
  row: string;
  seat_number: number;
  status: 'available' | 'held' | 'booked';
}

interface Hold {
  id: number;
  hold_token: string;
  user_id: string;
  status: 'ACTIVE' | 'RELEASED' | 'EXPIRED' | 'CONFIRMED';
  seats: string[];
  expires_at: Date;
  created_at: Date;
}

interface Booking {
  id: number;
  booking_reference: string;
  hold_id: number;
  user_id: string;
  status: 'confirmed';
  seats: string[];
  created_at: Date;
}

const ROWS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J'];
const SEATS_PER_ROW = 12;
const TOTAL_SEATS = 120;
const HOLD_DURATION_SECONDS = 300; // 5 minutes
const MAX_HOLD_SEATS = 4;

const seatsMap = new Map<string, Seat>();

function initSeats() {
  seatsMap.clear();
  for (const row of ROWS) {
    for (let num = 1; num <= SEATS_PER_ROW; num++) {
      const id = `${row}${num}`;
      seatsMap.set(id, {
        id,
        row,
        seat_number: num,
        status: 'available',
      });
    }
  }
}

initSeats();

let nextHoldId = 1;
let nextBookingId = 1;
const holdsList: Hold[] = [];
const bookingsList: Booking[] = [];

function cleanupExpiredHolds(now = new Date()): number {
  let cleanedCount = 0;
  for (const hold of holdsList) {
    if (hold.status === 'ACTIVE' && hold.expires_at.getTime() <= now.getTime()) {
      hold.status = 'EXPIRED';
      cleanedCount++;

      for (const seatId of hold.seats) {
        const seat = seatsMap.get(seatId);
        if (seat && seat.status === 'held') {
          const hasOtherActiveHold = holdsList.some(
            (h) =>
              h.id !== hold.id &&
              h.status === 'ACTIVE' &&
              h.expires_at.getTime() > now.getTime() &&
              h.seats.includes(seatId)
          );
          if (!hasOtherActiveHold) {
            seat.status = 'available';
          }
        }
      }
    }
  }
  return cleanedCount;
}

// Background cleanup every 15 seconds
setInterval(() => {
  try {
    cleanupExpiredHolds();
  } catch (err) {
    console.error('Error in background hold cleanup:', err);
  }
}, 15000);

function findHold(identifier: any): Hold | undefined {
  if (!identifier) return undefined;
  const str = String(identifier).trim();
  if (/^\d+$/.test(str)) {
    const numId = parseInt(str, 10);
    const found = holdsList.find((h) => h.id === numId);
    if (found) return found;
  }
  return holdsList.find((h) => h.hold_token === str);
}

function confirmHoldLogic(identifier: any, userId?: string) {
  cleanupExpiredHolds();
  const hold = findHold(identifier);
  if (!hold) {
    return { status: 404, data: { detail: 'Hold not found' } };
  }

  if (hold.status === 'RELEASED') {
    return {
      status: 400,
      data: { detail: 'Hold has already been released and cannot be confirmed' },
    };
  }

  if (hold.status === 'CONFIRMED') {
    return {
      status: 400,
      data: { detail: 'Hold has already been confirmed' },
    };
  }

  const now = new Date();
  if (hold.status === 'EXPIRED' || hold.expires_at.getTime() <= now.getTime()) {
    hold.status = 'EXPIRED';
    for (const sid of hold.seats) {
      const seat = seatsMap.get(sid);
      if (seat && seat.status === 'held') {
        seat.status = 'available';
      }
    }
    return {
      status: 400,
      data: { detail: 'Hold has expired and cannot be confirmed' },
    };
  }

  const unavailable = hold.seats.filter((sid) => seatsMap.get(sid)?.status !== 'held');
  if (unavailable.length > 0) {
    return {
      status: 409,
      data: {
        detail: {
          message: 'One or more seats are unavailable',
          unavailable_seats: unavailable,
        },
      },
    };
  }

  for (const sid of hold.seats) {
    const seat = seatsMap.get(sid);
    if (seat) {
      seat.status = 'booked';
    }
  }

  hold.status = 'CONFIRMED';

  const bookingRef = `BK-${crypto.randomBytes(4).toString('hex').toUpperCase()}`;
  const booking: Booking = {
    id: nextBookingId++,
    booking_reference: bookingRef,
    hold_id: hold.id,
    user_id: userId || hold.user_id || 'default_user',
    status: 'confirmed',
    seats: [...hold.seats],
    created_at: now,
  };

  bookingsList.push(booking);

  return {
    status: 201,
    data: {
      id: booking.id,
      booking_id: booking.id,
      booking_reference: booking.booking_reference,
      hold_id: hold.id,
      seats: booking.seats,
      booked_seats: booking.seats,
      user_id: booking.user_id,
      status: 'confirmed',
      created_at: booking.created_at.toISOString(),
    },
  };
}

// ---------------- API Routes ----------------

// Health check endpoint
app.get('/api/health', (req: Request, res: Response) => {
  res.json({
    status: 'ok',
    service: 'seat-booking-backend',
    database: 'connected',
    environment: process.env.APP_ENV || 'development',
  });
});

// Event info endpoint
app.get('/api/event/info', (req: Request, res: Response) => {
  res.json({
    event_id: 1,
    name: 'Main Event',
    seat_map: {
      rows: ROWS.length,
      seats_per_row: SEATS_PER_ROW,
      total_seats: TOTAL_SEATS,
    },
  });
});

// Seats list endpoint
app.get('/seats', (req: Request, res: Response) => {
  cleanupExpiredHolds();
  const seats: Seat[] = [];
  for (const row of ROWS) {
    for (let num = 1; num <= SEATS_PER_ROW; num++) {
      const s = seatsMap.get(`${row}${num}`);
      if (s) {
        seats.push({
          id: s.id,
          row: s.row,
          seat_number: s.seat_number,
          status: s.status,
        });
      }
    }
  }
  res.json(seats);
});

// Create hold endpoint
app.post('/holds', (req: Request, res: Response) => {
  cleanupExpiredHolds();
  const rawSeats = req.body.seats || req.body.seat_ids || [];
  if (!Array.isArray(rawSeats) || rawSeats.length === 0) {
    return res.status(400).json({ detail: 'At least one seat must be specified' });
  }

  const cleanSeatIds = Array.from(
    new Set(
      rawSeats
        .map((s: any) => String(s).trim().toUpperCase())
        .filter((s: string) => s.length > 0)
    )
  ).sort();

  if (cleanSeatIds.length === 0) {
    return res.status(400).json({ detail: 'At least one seat must be specified' });
  }

  if (cleanSeatIds.length > MAX_HOLD_SEATS) {
    return res.status(400).json({
      detail: `Maximum of ${MAX_HOLD_SEATS} seats can be held at once`,
    });
  }

  const missingSeats = cleanSeatIds.filter((sid) => !seatsMap.has(sid));
  if (missingSeats.length > 0) {
    return res.status(400).json({
      detail: `Invalid seat ID(s): ${missingSeats.join(', ')}`,
    });
  }

  const unavailable = cleanSeatIds.filter((sid) => seatsMap.get(sid)?.status !== 'available');
  if (unavailable.length > 0) {
    return res.status(409).json({
      detail: {
        message: 'One or more requested seats are unavailable',
        unavailable_seats: unavailable,
      },
    });
  }

  const now = new Date();
  const expiresAt = new Date(now.getTime() + HOLD_DURATION_SECONDS * 1000);
  const holdToken = crypto.randomUUID();
  const holdId = nextHoldId++;

  const hold: Hold = {
    id: holdId,
    hold_token: holdToken,
    user_id: req.body.user_id || 'default_user',
    status: 'ACTIVE',
    seats: cleanSeatIds,
    expires_at: expiresAt,
    created_at: now,
  };

  holdsList.push(hold);

  for (const sid of cleanSeatIds) {
    const seat = seatsMap.get(sid);
    if (seat) {
      seat.status = 'held';
    }
  }

  res.status(201).json({
    id: hold.id,
    hold_id: hold.id,
    hold_token: hold.hold_token,
    seats: cleanSeatIds,
    expires_at: hold.expires_at.toISOString(),
    expires_in_seconds: HOLD_DURATION_SECONDS,
    status: 'held',
    user_id: hold.user_id,
  });
});

// Release hold endpoint
app.delete('/holds/:id', (req: Request, res: Response) => {
  cleanupExpiredHolds();
  const identifier = req.params.id;
  const hold = findHold(identifier);

  if (!hold) {
    return res.status(404).json({ detail: 'Hold not found' });
  }

  if (hold.status === 'RELEASED') {
    return res.status(400).json({
      detail: 'Hold has already been released and cannot be confirmed',
    });
  }

  if (hold.status === 'CONFIRMED') {
    return res.status(400).json({
      detail: 'Hold has already been confirmed and cannot be released',
    });
  }

  const now = new Date();
  if (hold.status === 'EXPIRED' || hold.expires_at.getTime() <= now.getTime()) {
    hold.status = 'EXPIRED';
    for (const sid of hold.seats) {
      const seat = seatsMap.get(sid);
      if (seat && seat.status === 'held') {
        seat.status = 'available';
      }
    }
    return res.status(400).json({
      detail: 'Hold has expired and cannot be released',
    });
  }

  hold.status = 'RELEASED';
  for (const sid of hold.seats) {
    const seat = seatsMap.get(sid);
    if (seat && seat.status === 'held') {
      seat.status = 'available';
    }
  }

  res.json({
    status: 'released',
    hold_id: hold.id,
    message: 'Hold released successfully',
    released_seats: hold.seats,
  });
});

// Confirm hold by token parameter
app.post('/holds/:hold_token/confirm', (req: Request, res: Response) => {
  const result = confirmHoldLogic(req.params.hold_token, req.body.user_id);
  res.status(result.status).json(result.data);
});

// Create booking endpoint
app.post('/bookings', (req: Request, res: Response) => {
  const identifier = req.body.hold_id ?? req.body.holdId ?? req.body.hold_token;
  if (!identifier) {
    return res.status(400).json({
      detail: 'hold_id is required to create a booking',
    });
  }
  const result = confirmHoldLogic(identifier, req.body.user_id);
  res.status(result.status).json(result.data);
});

// List bookings endpoint
app.get('/bookings', (req: Request, res: Response) => {
  const list = [...bookingsList]
    .sort((a, b) => b.created_at.getTime() - a.created_at.getTime())
    .map((b) => ({
      id: b.id,
      booking_id: b.id,
      booking_reference: b.booking_reference,
      hold_id: b.hold_id,
      seats: b.seats,
      booked_seats: b.seats,
      user_id: b.user_id,
      status: b.status,
      created_at: b.created_at.toISOString(),
    }));
  res.json(list);
});

// Cleanup holds manual trigger
app.post('/holds/cleanup', (req: Request, res: Response) => {
  const cleaned = cleanupExpiredHolds();
  res.json({ status: 'ok', cleaned_holds: cleaned });
});

// Root API or SPA fallback
app.get('/', (req: Request, res: Response, next: NextFunction) => {
  if (req.accepts('html')) {
    return next();
  }
  res.json({
    message: 'Seat Booking System API is running',
    backend: 'Node.js + Express',
    database: 'In-Memory',
    event_spec: {
      total_rows: ROWS.length,
      seats_per_row: SEATS_PER_ROW,
      total_seats: TOTAL_SEATS,
    },
    status: 'ready',
  });
});

async function startServer() {
  if (process.env.NODE_ENV !== 'production') {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*all', (req: Request, res: Response) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`Seat Booking System server running at http://0.0.0.0:${PORT}`);
  });
}

startServer();
