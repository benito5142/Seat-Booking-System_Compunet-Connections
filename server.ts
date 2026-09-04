import express, { Request, Response, NextFunction } from "express";
import path from "path";
import crypto from "crypto";
import { createServer as createViteServer } from "vite";

interface Seat {
  id: string;
  row: string;
  seat_number: number;
  status: "available" | "held" | "booked";
}

interface Hold {
  id: number;
  hold_token: string;
  seats: string[];
  user_id: string;
  status: "ACTIVE" | "RELEASED" | "EXPIRED" | "CONFIRMED";
  expires_at: Date;
  created_at: Date;
}

interface Booking {
  id: number;
  booking_id: number;
  booking_reference: string;
  hold_id: number;
  seats: string[];
  booked_seats: string[];
  user_id: string;
  status: string;
  created_at: string;
}

// Fixed venue configuration: 10 rows (A-J) x 12 seats per row = 120 seats
const TOTAL_ROWS = 10;
const SEATS_PER_ROW = 12;
const TOTAL_SEATS = 120;
const ROW_LABELS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"];

// In-memory data store
const seatsMap = new Map<string, Seat>();
const seatsList: Seat[] = [];

for (const row of ROW_LABELS) {
  for (let num = 1; num <= SEATS_PER_ROW; num++) {
    const id = `${row}${num}`;
    const seat: Seat = {
      id,
      row,
      seat_number: num,
      status: "available",
    };
    seatsMap.set(id, seat);
    seatsList.push(seat);
  }
}

let nextHoldId = 0;
let nextBookingId = 0;
const holdsById = new Map<number, Hold>();
const holdsByToken = new Map<string, Hold>();
const bookings: Booking[] = [];

/**
 * Sweep and expire active holds past their 5-minute TTL.
 */
function cleanupExpiredHolds(now: Date = new Date()): number {
  let cleanedCount = 0;
  for (const hold of holdsById.values()) {
    if (hold.status === "ACTIVE" && hold.expires_at.getTime() <= now.getTime()) {
      hold.status = "EXPIRED";
      cleanedCount++;
      for (const seatId of hold.seats) {
        const seat = seatsMap.get(seatId);
        if (seat && seat.status === "held") {
          // Check if any other active hold claims this seat
          let isStillHeld = false;
          for (const otherHold of holdsById.values()) {
            if (otherHold.status === "ACTIVE" && otherHold.seats.includes(seatId)) {
              isStillHeld = true;
              break;
            }
          }
          if (!isStillHeld) {
            seat.status = "available";
          }
        }
      }
    }
  }
  return cleanedCount;
}

// Background cleanup timer every 15 seconds
setInterval(() => {
  try {
    cleanupExpiredHolds();
  } catch (err) {
    console.error("Cleanup error:", err);
  }
}, 15000);

function findHold(identifier: string | number): Hold | undefined {
  if (typeof identifier === "number") {
    return holdsById.get(identifier);
  }
  const numericId = Number(identifier);
  if (!isNaN(numericId) && holdsById.has(numericId)) {
    return holdsById.get(numericId);
  }
  return holdsByToken.get(String(identifier));
}

async function startServer() {
  const app = express();
  const PORT = 3000;

  // Middleware for CORS
  app.use((req: Request, res: Response, next: NextFunction) => {
    const origin = req.headers.origin || "*";
    res.header("Access-Control-Allow-Origin", origin);
    res.header("Access-Control-Allow-Credentials", "true");
    res.header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS, PATCH");
    res.header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, Accept");
    if (req.method === "OPTIONS") {
      res.sendStatus(200);
      return;
    }
    next();
  });

  app.use(express.json());

  // Root endpoint: provides API status for API consumers or hands off to SPA for HTML requests
  app.get("/", (req: Request, res: Response, next: NextFunction) => {
    const accept = req.headers.accept || "";
    if (accept.includes("text/html")) {
      return next();
    }
    res.json({
      message: "Seat Booking System API is running",
      event_spec: {
        total_rows: TOTAL_ROWS,
        seats_per_row: SEATS_PER_ROW,
        total_seats: TOTAL_SEATS,
      },
      status: "ready",
    });
  });

  // Health check endpoint
  app.get("/api/health", (_req: Request, res: Response) => {
    res.json({
      status: "ok",
      service: "seat-booking-backend",
      environment: process.env.APP_ENV || "development",
    });
  });

  // Event info endpoint
  app.get("/api/event/info", (_req: Request, res: Response) => {
    res.json({
      event_id: 1,
      name: "Main Event",
      seat_map: {
        rows: TOTAL_ROWS,
        seats_per_row: SEATS_PER_ROW,
        total_seats: TOTAL_SEATS,
      },
    });
  });

  // Complete seat map (120 seats)
  app.get("/seats", (_req: Request, res: Response) => {
    cleanupExpiredHolds();
    res.json(seatsList);
  });

  // Create hold (1-4 seats, 5-minute TTL)
  app.post("/holds", (req: Request, res: Response) => {
    cleanupExpiredHolds();
    const rawSeats: unknown = req.body?.seats ?? req.body?.seat_ids;

    if (!Array.isArray(rawSeats) || rawSeats.length === 0) {
      res.status(400).json({ detail: "At least one seat must be specified" });
      return;
    }

    const cleanIds = Array.from(
      new Set(
        rawSeats
          .map((s) => String(s).trim().toUpperCase())
          .filter((s) => s.length > 0)
      )
    );

    if (cleanIds.length === 0) {
      res.status(400).json({ detail: "At least one seat must be specified" });
      return;
    }

    if (cleanIds.length > 4) {
      res.status(400).json({ detail: "Maximum of 4 seats can be held at once" });
      return;
    }

    // Check valid seats
    for (const sid of cleanIds) {
      if (!seatsMap.has(sid)) {
        res.status(400).json({ detail: `Invalid seat ID: ${sid}` });
        return;
      }
    }

    // Check availability: all requested seats must be available
    const unavailable: string[] = [];
    for (const sid of cleanIds) {
      const seat = seatsMap.get(sid)!;
      if (seat.status !== "available") {
        unavailable.push(sid);
      }
    }

    if (unavailable.length > 0) {
      res.status(409).json({
        detail: {
          message: "One or more requested seats are unavailable",
          unavailable_seats: unavailable,
        },
      });
      return;
    }

    // Atomically reserve all seats
    const holdId = ++nextHoldId;
    const holdToken = crypto.randomUUID();
    const now = new Date();
    const expiresAt = new Date(now.getTime() + 300 * 1000); // 300 seconds

    const hold: Hold = {
      id: holdId,
      hold_token: holdToken,
      seats: cleanIds,
      user_id: req.body?.user_id || "default_user",
      status: "ACTIVE",
      expires_at: expiresAt,
      created_at: now,
    };

    holdsById.set(holdId, hold);
    holdsByToken.set(holdToken, hold);

    for (const sid of cleanIds) {
      const seat = seatsMap.get(sid)!;
      seat.status = "held";
    }

    res.status(201).json({
      id: hold.id,
      hold_id: hold.id,
      hold_token: hold.hold_token,
      seats: hold.seats,
      expires_at: hold.expires_at.toISOString(),
      expires_in_seconds: 300,
      status: "held",
      user_id: hold.user_id,
    });
  });

  // Confirm hold handler (shared between /holds/:hold_token/confirm and /bookings)
  const handleConfirmHold = (req: Request, res: Response, paramToken?: string) => {
    cleanupExpiredHolds();
    const rawId =
      paramToken ||
      (req.body?.hold_id ??
        req.body?.holdId ??
        req.body?.id ??
        req.body?.hold_token ??
        req.query?.hold_id);

    if (rawId === undefined || rawId === null || String(rawId).trim() === "") {
      res.status(400).json({ detail: "hold_id is required to create a booking" });
      return;
    }

    const hold = findHold(String(rawId).trim());
    if (!hold) {
      res.status(404).json({ detail: "Hold not found" });
      return;
    }

    if (hold.status === "RELEASED") {
      res.status(400).json({ detail: "Hold has already been released and cannot be confirmed" });
      return;
    }

    if (hold.status === "CONFIRMED") {
      res.status(400).json({ detail: "Hold has already been confirmed" });
      return;
    }

    const now = new Date();
    if (hold.status === "EXPIRED" || hold.expires_at.getTime() <= now.getTime()) {
      hold.status = "EXPIRED";
      for (const sid of hold.seats) {
        const s = seatsMap.get(sid);
        if (s && s.status === "held") {
          s.status = "available";
        }
      }
      res.status(400).json({ detail: "Hold has expired and cannot be confirmed" });
      return;
    }

    // Verify all seats still belong to this hold and are currently HELD
    const unavailableSeats: string[] = [];
    for (const sid of hold.seats) {
      const seat = seatsMap.get(sid);
      if (!seat || seat.status !== "held") {
        unavailableSeats.push(sid);
      }
    }

    if (unavailableSeats.length > 0) {
      res.status(409).json({
        detail: {
          message: "One or more seats are unavailable",
          unavailable_seats: unavailableSeats,
        },
      });
      return;
    }

    // Confirm booking
    hold.status = "CONFIRMED";
    for (const sid of hold.seats) {
      const seat = seatsMap.get(sid);
      if (seat) {
        seat.status = "booked";
      }
    }

    const bookingId = ++nextBookingId;
    const refCode = `BK-${crypto.randomBytes(4).toString("hex").toUpperCase()}`;
    const booking: Booking = {
      id: bookingId,
      booking_id: bookingId,
      booking_reference: refCode,
      hold_id: hold.id,
      seats: [...hold.seats],
      booked_seats: [...hold.seats],
      user_id: req.body?.user_id || hold.user_id || "default_user",
      status: "confirmed",
      created_at: new Date().toISOString(),
    };

    bookings.push(booking);
    res.status(201).json(booking);
  };

  app.post("/holds/:hold_token/confirm", (req: Request, res: Response) => {
    handleConfirmHold(req, res, req.params.hold_token);
  });

  app.post("/bookings", (req: Request, res: Response) => {
    handleConfirmHold(req, res);
  });

  // Get all bookings
  app.get("/bookings", (_req: Request, res: Response) => {
    res.json(bookings);
  });

  // Release hold
  app.delete("/holds/:id", (req: Request, res: Response) => {
    cleanupExpiredHolds();
    const rawId = req.params.id;
    if (!rawId || String(rawId).trim() === "") {
      res.status(404).json({ detail: "Hold not found" });
      return;
    }

    const hold = findHold(String(rawId).trim());
    if (!hold) {
      res.status(404).json({ detail: "Hold not found" });
      return;
    }

    if (hold.status === "RELEASED") {
      res.status(400).json({ detail: "Hold has already been released and cannot be confirmed" });
      return;
    }

    if (hold.status === "CONFIRMED") {
      res.status(400).json({ detail: "Hold has already been confirmed and cannot be released" });
      return;
    }

    const now = new Date();
    if (hold.status === "EXPIRED" || hold.expires_at.getTime() <= now.getTime()) {
      hold.status = "EXPIRED";
      for (const sid of hold.seats) {
        const s = seatsMap.get(sid);
        if (s && s.status === "held") {
          s.status = "available";
        }
      }
      res.status(400).json({ detail: "Hold has expired and cannot be released" });
      return;
    }

    // Release this hold's seats only
    hold.status = "RELEASED";
    for (const sid of hold.seats) {
      const seat = seatsMap.get(sid);
      if (seat && seat.status === "held") {
        seat.status = "available";
      }
    }

    res.json({
      status: "released",
      hold_id: hold.id,
      message: "Hold released successfully",
      released_seats: hold.seats,
    });
  });

  // Manual cleanup endpoint
  app.post("/holds/cleanup", (_req: Request, res: Response) => {
    const cleaned = cleanupExpiredHolds();
    res.json({ status: "ok", cleaned_holds: cleaned });
  });

  // Vite middleware for development / Static file serving for production
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (_req: Request, res: Response) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Seat Booking System server running on http://0.0.0.0:${PORT}`);
  });
}

startServer();
