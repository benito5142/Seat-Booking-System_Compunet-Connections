import { spawn, execSync } from 'child_process';
import fs from 'fs';

// 1. Ensure MariaDB database service is started
try {
  console.log('[DevRunner] Checking/starting MariaDB service...');
  execSync('/etc/init.d/mariadb status || /etc/init.d/mariadb start', { stdio: 'inherit' });
} catch (e) {
  console.warn('[DevRunner] MariaDB start notice:', e.message);
}

// 2. Ensure database schema and users exist
try {
  execSync(
    `mariadb -u root -e "CREATE DATABASE IF NOT EXISTS seat_booking; ALTER USER 'root'@'localhost' IDENTIFIED VIA mysql_native_password USING PASSWORD('your_mysql_password'); CREATE USER IF NOT EXISTS 'root'@'127.0.0.1' IDENTIFIED VIA mysql_native_password USING PASSWORD('your_mysql_password'); ALTER USER 'root'@'127.0.0.1' IDENTIFIED VIA mysql_native_password USING PASSWORD('your_mysql_password'); GRANT ALL PRIVILEGES ON *.* TO 'root'@'localhost' WITH GRANT OPTION; GRANT ALL PRIVILEGES ON *.* TO 'root'@'127.0.0.1' WITH GRANT OPTION; FLUSH PRIVILEGES;"`,
    { stdio: 'ignore' }
  );
  execSync(`mariadb -u root -pyour_mysql_password seat_booking < backend/schema.sql`, { stdio: 'ignore' });
} catch (e) {
  // If already configured or running, ignore
}

// 3. Ensure virtual environment exists
let uvicornBin = './backend/venv/bin/uvicorn';
if (!fs.existsSync(uvicornBin)) {
  if (fs.existsSync('/usr/local/bin/uvicorn')) {
    uvicornBin = '/usr/local/bin/uvicorn';
  } else if (fs.existsSync('/usr/bin/uvicorn')) {
    uvicornBin = '/usr/bin/uvicorn';
  } else {
    try {
      console.log('[DevRunner] Setting up python virtual environment...');
      execSync('python3 -m venv backend/venv && ./backend/venv/bin/pip install -r backend/requirements.txt', { stdio: 'inherit' });
    } catch (err) {
      console.error('[DevRunner] Failed to auto-create venv:', err.message);
    }
  }
}

// Start FastAPI Python Backend on port 8000
console.log('[DevRunner] Starting FastAPI Python backend on port 8000...');
const uvicorn = spawn(
  uvicornBin,
  ['backend.app.main:app', '--host', '127.0.0.1', '--port', '8000'],
  {
    stdio: 'inherit',
    env: {
      ...process.env,
      DB_HOST: '127.0.0.1',
      DB_PORT: '3306',
      DB_USER: 'root',
      DB_PASSWORD: 'your_mysql_password',
      DB_NAME: 'seat_booking',
    },
  }
);

uvicorn.on('error', (err) => {
  console.error('[DevRunner] Failed to start uvicorn:', err);
});

// 4. Start Vite Dev Server on port 3000
console.log('[DevRunner] Starting Vite frontend on port 3000...');
const vite = spawn(
  'npx',
  ['vite', '--host', '0.0.0.0', '--port', '3000'],
  { stdio: 'inherit' }
);

vite.on('error', (err) => {
  console.error('[DevRunner] Failed to start vite:', err);
});

const cleanExit = () => {
  console.log('[DevRunner] Shutting down dev processes...');
  try { uvicorn.kill('SIGTERM'); } catch (_) {}
  try { vite.kill('SIGTERM'); } catch (_) {}
  process.exit(0);
};

process.on('SIGINT', cleanExit);
process.on('SIGTERM', cleanExit);
process.on('exit', cleanExit);
