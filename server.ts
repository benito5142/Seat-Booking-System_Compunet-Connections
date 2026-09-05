import express from 'express';
import path from 'path';
import { spawn } from 'child_process';
import http from 'http';
import { createProxyMiddleware } from 'http-proxy-middleware';
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

async function ensureBackend(): Promise<void> {
  const healthy = await checkBackendHealth();
  if (healthy) {
    console.log('[Server] Python backend is already running and healthy.');
    return;
  }

  console.log('[Server] Launching Python backend via start_backend.py...');
  spawn('python3', ['start_backend.py'], {
    stdio: 'inherit',
    cwd: process.cwd(),
  });

  // Wait up to 15 seconds for backend to become healthy
  for (let i = 0; i < 30; i++) {
    await new Promise((r) => setTimeout(r, 500));
    if (await checkBackendHealth()) {
      console.log('[Server] Python backend is now healthy on http://127.0.0.1:8001');
      return;
    }
  }
  console.warn('[Server] Warning: Python backend did not report healthy within timeout.');
}

async function startServer() {
  const app = express();

  // 1. Ensure Python FastAPI backend is started
  await ensureBackend();

  // 2. Proxy API routes to Python backend on port 8001
  const apiProxy = createProxyMiddleware({
    target: 'http://127.0.0.1:8001',
    changeOrigin: true,
    on: {
      error: (err, req, res) => {
        console.error('[API Proxy Error]', req.method, req.url, err.message);
        const resObj = res as express.Response;
        if (resObj && !resObj.headersSent && typeof resObj.status === 'function') {
          resObj.status(502).json({
            detail: 'Seat booking service is warming up or temporarily busy. Please retry.',
          });
        }
      },
    },
  });

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
