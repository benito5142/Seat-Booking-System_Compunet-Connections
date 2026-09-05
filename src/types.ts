/**
 * Core type definitions for the Seat Booking System.
 */

export type SeatStatus = 'available' | 'held' | 'booked';

export interface Seat {
  id: string; // e.g. 'A1', 'A12', 'J1', 'J12'
  row: string; // 'A' through 'J'
  seat_number: number; // 1 through 12
  status: SeatStatus;
}

export interface HoldResponse {
  id: number;
  hold_id?: number;
  hold_token: string;
  seats: string[];
  expires_at: string;
  expires_in_seconds: number;
  status: string;
  user_id: string;
}

export interface ActiveHold {
  id: number | string;
  holdToken: string;
  seats: string[];
  expiresAt: string;
  status: string;
  userId?: string;
}

export interface BookingResponse {
  id: number;
  booking_reference: string;
  hold_id: number;
  seats: string[];
  status: string;
  confirmed_at: string;
  created_at: string;
  user_id: string;
}

export interface ApiErrorDetail {
  message?: string;
  unavailable_seats?: string[];
  detail?: string | { message?: string; unavailable_seats?: string[] };
}
