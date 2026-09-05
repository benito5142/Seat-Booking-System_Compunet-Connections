import { Seat, HoldResponse, BookingResponse } from '../types';
import { EVENT_SPEC } from '../config';

const STORAGE_KEY_SEATS = 'seat_booking_app_seats_v2';
const STORAGE_KEY_HOLDS = 'seat_booking_app_holds_v2';
const STORAGE_KEY_BOOKINGS = 'seat_booking_app_bookings_v2';

interface StoredHold {
  id: number;
  hold_token: string;
  seats: string[];
  expires_at: string;
  status: 'held' | 'released' | 'confirmed';
  user_id: string;
}

interface StoredBooking {
  booking_id: number;
  booking_reference: string;
  seats: string[];
  confirmed_at: string;
  user_id: string;
  total_amount: number;
  currency: string;
}

/**
 * Generate standard 120-seat layout (Rows A–J, Columns 1–12)
 */
function createInitialSeats(): Seat[] {
  const seats: Seat[] = [];
  for (const row of EVENT_SPEC.rows) {
    for (let col = 1; col <= EVENT_SPEC.seatsPerRow; col++) {
      seats.push({
        id: `${row}${col}`,
        row,
        seat_number: col,
        status: 'available',
      });
    }
  }
  return seats;
}

function getStoredSeats(): Seat[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_SEATS);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length === EVENT_SPEC.totalSeats) {
        return parsed;
      }
    }
  } catch {
    // fallback to initial
  }
  const initial = createInitialSeats();
  saveStoredSeats(initial);
  return initial;
}

function saveStoredSeats(seats: Seat[]) {
  try {
    localStorage.setItem(STORAGE_KEY_SEATS, JSON.stringify(seats));
  } catch (err) {
    console.warn('Storage save failed:', err);
  }
}

function getStoredHolds(): StoredHold[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_HOLDS);
    if (raw) {
      return JSON.parse(raw);
    }
  } catch {
    // empty
  }
  return [];
}

function saveStoredHolds(holds: StoredHold[]) {
  try {
    localStorage.setItem(STORAGE_KEY_HOLDS, JSON.stringify(holds));
  } catch (err) {
    console.warn('Storage save failed:', err);
  }
}

function getStoredBookings(): StoredBooking[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_BOOKINGS);
    if (raw) {
      return JSON.parse(raw);
    }
  } catch {
    // empty
  }
  return [];
}

function saveStoredBookings(bookings: StoredBooking[]) {
  try {
    localStorage.setItem(STORAGE_KEY_BOOKINGS, JSON.stringify(bookings));
  } catch (err) {
    console.warn('Storage save failed:', err);
  }
}

/**
 * Sweeps expired holds and resets their seats to available.
 */
function sweepExpiredHolds(): { seats: Seat[]; holds: StoredHold[] } {
  const now = new Date().getTime();
  const seats = getStoredSeats();
  const holds = getStoredHolds();
  let changed = false;

  const seatMap = new Map(seats.map((s) => [s.id, s]));

  for (const hold of holds) {
    if (hold.status === 'held') {
      const expireTime = new Date(hold.expires_at).getTime();
      if (expireTime <= now) {
        hold.status = 'released';
        changed = true;
        for (const seatId of hold.seats) {
          const seat = seatMap.get(seatId);
          if (seat && seat.status === 'held') {
            seat.status = 'available';
          }
        }
      }
    }
  }

  if (changed) {
    saveStoredHolds(holds);
    saveStoredSeats(seats);
  }

  return { seats, holds };
}

/**
 * Client-Side Engine: GET /seats
 */
export function engineGetSeats(): Seat[] {
  const { seats } = sweepExpiredHolds();
  return seats;
}

/**
 * Client-Side Engine: POST /holds
 */
export function engineCreateHold(seatsRequested: string[], userId: string = 'user_1'): HoldResponse {
  if (!seatsRequested || seatsRequested.length === 0) {
    throw new Error('At least one seat must be specified');
  }
  if (seatsRequested.length > EVENT_SPEC.maxSelectableSeats) {
    throw new Error(`Cannot hold more than ${EVENT_SPEC.maxSelectableSeats} seats at once`);
  }

  const { seats, holds } = sweepExpiredHolds();
  const seatMap = new Map(seats.map((s) => [s.id, s]));

  // Check validity and availability
  const unavailable: string[] = [];
  for (const seatId of seatsRequested) {
    const seat = seatMap.get(seatId);
    if (!seat) {
      throw new Error(`Invalid seat identifier: ${seatId}`);
    }
    if (seat.status !== 'available') {
      unavailable.push(seatId);
    }
  }

  if (unavailable.length > 0) {
    const err = new Error(`One or more requested seats are unavailable: ${unavailable.join(', ')}`);
    (err as unknown as { statusCode: number; unavailableSeats: string[] }).statusCode = 409;
    (err as unknown as { statusCode: number; unavailableSeats: string[] }).unavailableSeats = unavailable;
    throw err;
  }

  // Create hold with 5-minute TTL
  const holdId = Date.now();
  const holdToken = Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
  const now = new Date();
  const expiresAt = new Date(now.getTime() + 300 * 1000).toISOString();

  // Mark seats as held
  for (const seatId of seatsRequested) {
    const seat = seatMap.get(seatId);
    if (seat) {
      seat.status = 'held';
    }
  }

  const newHold: StoredHold = {
    id: holdId,
    hold_token: holdToken,
    seats: [...seatsRequested],
    expires_at: expiresAt,
    status: 'held',
    user_id: userId,
  };

  holds.push(newHold);

  saveStoredSeats(seats);
  saveStoredHolds(holds);

  return {
    id: holdId,
    hold_id: holdId,
    hold_token: holdToken,
    seats: [...seatsRequested],
    expires_at: expiresAt,
    expires_in_seconds: 300,
    status: 'held',
    user_id: userId,
  };
}

/**
 * Client-Side Engine: DELETE /holds/:id
 */
export function engineReleaseHold(holdIdentifier: string | number): { status: string; message: string } {
  const { seats, holds } = sweepExpiredHolds();
  const hold = holds.find(
    (h) => String(h.id) === String(holdIdentifier) || h.hold_token === String(holdIdentifier)
  );

  if (!hold) {
    const err = new Error('Hold not found');
    (err as unknown as { statusCode: number }).statusCode = 404;
    throw err;
  }

  if (hold.status !== 'held') {
    return { status: 'already_released', message: 'Hold was already released or expired' };
  }

  hold.status = 'released';
  const seatMap = new Map(seats.map((s) => [s.id, s]));

  for (const seatId of hold.seats) {
    const seat = seatMap.get(seatId);
    if (seat && seat.status === 'held') {
      seat.status = 'available';
    }
  }

  saveStoredSeats(seats);
  saveStoredHolds(holds);

  return { status: 'released', message: 'Hold successfully released' };
}

/**
 * Client-Side Engine: POST /bookings
 */
export function engineConfirmBooking(holdIdentifier: string | number, userId: string = 'user_1'): BookingResponse {
  const { seats, holds } = sweepExpiredHolds();
  const hold = holds.find(
    (h) => String(h.id) === String(holdIdentifier) || h.hold_token === String(holdIdentifier)
  );

  if (!hold) {
    const err = new Error('Hold not found or has expired');
    (err as unknown as { statusCode: number }).statusCode = 404;
    throw err;
  }

  if (hold.status === 'released') {
    const err = new Error('Hold has expired or was released');
    (err as unknown as { statusCode: number }).statusCode = 400;
    throw err;
  }

  if (hold.status === 'confirmed') {
    const err = new Error('Hold has already been confirmed');
    (err as unknown as { statusCode: number }).statusCode = 400;
    throw err;
  }

  // Calculate tier total
  let totalAmount = 0;
  for (const seatId of hold.seats) {
    const row = seatId.charAt(0);
    const tierPrice = ['A', 'B', 'C'].includes(row) ? 350 : ['D', 'E', 'F', 'G'].includes(row) ? 250 : 150;
    totalAmount += tierPrice;
  }

  // Transition to confirmed
  hold.status = 'confirmed';
  const seatMap = new Map(seats.map((s) => [s.id, s]));

  for (const seatId of hold.seats) {
    const seat = seatMap.get(seatId);
    if (seat) {
      seat.status = 'booked';
    }
  }

  const bookingRef = `BK-${Math.random().toString(36).substring(2, 8).toUpperCase()}`;
  const nowIso = new Date().toISOString();

  const newBooking: StoredBooking = {
    booking_id: Date.now(),
    booking_reference: bookingRef,
    seats: [...hold.seats],
    confirmed_at: nowIso,
    user_id: userId,
    total_amount: totalAmount,
    currency: 'INR',
  };

  const bookings = getStoredBookings();
  bookings.push(newBooking);

  saveStoredSeats(seats);
  saveStoredHolds(holds);
  saveStoredBookings(bookings);

  return {
    id: newBooking.booking_id,
    booking_reference: bookingRef,
    hold_id: hold.id,
    seats: [...hold.seats],
    status: 'confirmed',
    confirmed_at: nowIso,
    created_at: nowIso,
    user_id: userId,
  };
}

/**
 * Client-Side Engine: POST /api/reset
 */
export function engineResetAll(): { success: boolean; message: string } {
  const initialSeats = createInitialSeats();
  saveStoredSeats(initialSeats);
  saveStoredHolds([]);
  saveStoredBookings([]);
  return { success: true, message: 'All 120 seats reset to Available' };
}
