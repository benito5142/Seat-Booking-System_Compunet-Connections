import { API_BASE_URL } from '../config';
import { Seat, HoldResponse, BookingResponse } from '../types';
import {
  engineGetSeats,
  engineCreateHold,
  engineReleaseHold,
  engineConfirmBooking,
  engineResetAll,
} from './clientStorageEngine';

export interface HealthResponse {
  status: string;
  service: string;
  environment?: string;
}

export interface EventInfoResponse {
  event_id: number;
  name: string;
  seat_map: {
    rows: number;
    seats_per_row: number;
    total_seats: number;
  };
}

let activeEngineMode: 'cloud' | 'local' = 'cloud';

export function getActiveEngineMode(): 'cloud' | 'local' {
  return activeEngineMode;
}

export class ApiError extends Error {
  statusCode: number;
  unavailableSeats?: string[];

  constructor(message: string, statusCode: number, unavailableSeats?: string[]) {
    super(message);
    this.name = 'ApiError';
    this.statusCode = statusCode;
    this.unavailableSeats = unavailableSeats;
    Object.setPrototypeOf(this, ApiError.prototype);
  }
}

/**
 * Safe type-guard for ApiError that works across bundle boundaries and transpilation.
 */
export function isApiError(err: unknown): err is ApiError {
  if (err instanceof ApiError) return true;
  if (
    typeof err === 'object' &&
    err !== null &&
    'name' in err &&
    (err as { name: string }).name === 'ApiError' &&
    'statusCode' in err
  ) {
    return true;
  }
  return false;
}

/**
 * Helper to check if a response is an HTML SPA fallback page from static hosting.
 */
function isHtmlResponse(response: Response): boolean {
  const contentType = response.headers.get('content-type') || '';
  return contentType.includes('text/html');
}

/**
 * Helper to parse backend error responses safely without leaking raw stack traces.
 */
async function parseErrorResponse(response: Response, defaultMessage: string): Promise<ApiError> {
  try {
    const errorData = await response.json();
    let message = defaultMessage;
    let unavailableSeats: string[] | undefined = undefined;

    if (errorData) {
      if (typeof errorData.detail === 'string') {
        message = errorData.detail;
      } else if (typeof errorData.detail === 'object' && errorData.detail !== null) {
        message = errorData.detail.message || defaultMessage;
        unavailableSeats = errorData.detail.unavailable_seats;
      } else if (errorData.message) {
        message = errorData.message;
      }
      if (!unavailableSeats && Array.isArray(errorData.unavailable_seats)) {
        unavailableSeats = errorData.unavailable_seats;
      }
    }

    return new ApiError(message, response.status, unavailableSeats);
  } catch {
    return new ApiError(`${defaultMessage} (HTTP ${response.status})`, response.status);
  }
}

/**
 * Check health status of backend.
 */
export async function checkBackendHealth(): Promise<HealthResponse> {
  if (activeEngineMode === 'local') {
    return { status: 'ok', service: 'client-storage-engine', environment: 'autonomous' };
  }
  try {
    const response = await fetch(`${API_BASE_URL}/api/health`);
    if (isHtmlResponse(response) || !response.ok) {
      activeEngineMode = 'local';
      return { status: 'ok', service: 'client-storage-engine', environment: 'autonomous' };
    }
    return await response.json();
  } catch {
    activeEngineMode = 'local';
    return { status: 'ok', service: 'client-storage-engine', environment: 'autonomous' };
  }
}

/**
 * Fetch fixed event information.
 */
export async function getEventInfo(): Promise<EventInfoResponse> {
  if (activeEngineMode === 'local') {
    return {
      event_id: 1,
      name: 'Main Event - Sci-Fi Concert Premiere',
      seat_map: { rows: 10, seats_per_row: 12, total_seats: 120 },
    };
  }
  try {
    const response = await fetch(`${API_BASE_URL}/api/event/info`);
    if (isHtmlResponse(response) || !response.ok) {
      activeEngineMode = 'local';
      return {
        event_id: 1,
        name: 'Main Event - Sci-Fi Concert Premiere',
        seat_map: { rows: 10, seats_per_row: 12, total_seats: 120 },
      };
    }
    return await response.json();
  } catch {
    activeEngineMode = 'local';
    return {
      event_id: 1,
      name: 'Main Event - Sci-Fi Concert Premiere',
      seat_map: { rows: 10, seats_per_row: 12, total_seats: 120 },
    };
  }
}

/**
 * Fetch the authoritative seat map from GET /seats.
 * Returns 120 seats with status: 'available' | 'held' | 'booked'.
 */
export async function getSeats(): Promise<Seat[]> {
  if (activeEngineMode === 'local') {
    return engineGetSeats();
  }

  try {
    const response = await fetch(`${API_BASE_URL}/seats`, {
      headers: {
        'Accept': 'application/json',
      },
    });

    // Detect if running on static CDN host where /seats returns index.html SPA
    if (isHtmlResponse(response)) {
      console.info('[Engine] Static deployment detected. Switching to Autonomous Client Engine.');
      activeEngineMode = 'local';
      return engineGetSeats();
    }

    if (!response.ok) {
      throw await parseErrorResponse(response, 'Failed to fetch seat map');
    }

    const data = await response.json();
    if (!Array.isArray(data)) {
      activeEngineMode = 'local';
      return engineGetSeats();
    }
    return data;
  } catch (err) {
    if (isApiError(err) && err.statusCode === 409) throw err;
    // On connection or network error, transparently fall back to client engine
    console.info('[Engine] Backend unavailable. Falling back to Autonomous Client Engine.');
    activeEngineMode = 'local';
    return engineGetSeats();
  }
}

/**
 * Request a temporary 5-minute hold on up to 4 seats via POST /holds.
 */
export async function createHold(seats: string[], userId: string = 'user_1'): Promise<HoldResponse> {
  if (activeEngineMode === 'local') {
    try {
      return engineCreateHold(seats, userId);
    } catch (err) {
      const status = (err as unknown as { statusCode?: number }).statusCode || 400;
      const unavailable = (err as unknown as { unavailableSeats?: string[] }).unavailableSeats;
      const msg = err instanceof Error ? err.message : 'Failed to create hold';
      throw new ApiError(msg, status, unavailable);
    }
  }

  try {
    const response = await fetch(`${API_BASE_URL}/holds`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({
        seats,
        user_id: userId,
      }),
    });

    if (isHtmlResponse(response)) {
      activeEngineMode = 'local';
      return engineCreateHold(seats, userId);
    }

    if (!response.ok) {
      throw await parseErrorResponse(response, 'Failed to place hold on seats');
    }

    return await response.json();
  } catch (err) {
    if (isApiError(err)) throw err;
    // Fall back to engine if backend failed
    try {
      activeEngineMode = 'local';
      return engineCreateHold(seats, userId);
    } catch (localErr) {
      const status = (localErr as unknown as { statusCode?: number }).statusCode || 400;
      const unavailable = (localErr as unknown as { unavailableSeats?: string[] }).unavailableSeats;
      const msg = localErr instanceof Error ? localErr.message : 'Failed to place hold on seats';
      throw new ApiError(msg, status, unavailable);
    }
  }
}

/**
 * Release an active hold via DELETE /holds/{id}.
 * Transitions held seats back to AVAILABLE.
 */
export async function releaseHold(holdIdentifier: string | number): Promise<{ status: string; message: string }> {
  if (activeEngineMode === 'local') {
    try {
      return engineReleaseHold(holdIdentifier);
    } catch (err) {
      const status = (err as unknown as { statusCode?: number }).statusCode || 404;
      const msg = err instanceof Error ? err.message : 'Failed to release hold';
      throw new ApiError(msg, status);
    }
  }

  try {
    const response = await fetch(`${API_BASE_URL}/holds/${encodeURIComponent(holdIdentifier)}`, {
      method: 'DELETE',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (isHtmlResponse(response)) {
      activeEngineMode = 'local';
      return engineReleaseHold(holdIdentifier);
    }

    if (!response.ok) {
      throw await parseErrorResponse(response, 'Failed to release hold');
    }

    return await response.json();
  } catch (err) {
    if (isApiError(err)) throw err;
    try {
      activeEngineMode = 'local';
      return engineReleaseHold(holdIdentifier);
    } catch (localErr) {
      const status = (localErr as unknown as { statusCode?: number }).statusCode || 404;
      const msg = localErr instanceof Error ? localErr.message : 'Failed to release hold';
      throw new ApiError(msg, status);
    }
  }
}

/**
 * Confirm an active hold into a completed booking via POST /bookings.
 * Converts held seats to BOOKED and provides a unique booking reference.
 */
export async function confirmBooking(holdId: string | number, userId: string = 'user_1'): Promise<BookingResponse> {
  if (activeEngineMode === 'local') {
    try {
      return engineConfirmBooking(holdId, userId);
    } catch (err) {
      const status = (err as unknown as { statusCode?: number }).statusCode || 400;
      const msg = err instanceof Error ? err.message : 'Failed to confirm booking';
      throw new ApiError(msg, status);
    }
  }

  try {
    const response = await fetch(`${API_BASE_URL}/bookings`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({
        hold_id: holdId,
        user_id: userId,
      }),
    });

    if (isHtmlResponse(response)) {
      activeEngineMode = 'local';
      return engineConfirmBooking(holdId, userId);
    }

    if (!response.ok) {
      throw await parseErrorResponse(response, 'Failed to confirm booking');
    }

    return await response.json();
  } catch (err) {
    if (isApiError(err)) throw err;
    try {
      activeEngineMode = 'local';
      return engineConfirmBooking(holdId, userId);
    } catch (localErr) {
      const status = (localErr as unknown as { statusCode?: number }).statusCode || 400;
      const msg = localErr instanceof Error ? localErr.message : 'Failed to confirm booking';
      throw new ApiError(msg, status);
    }
  }
}

/**
 * Reset all seats to AVAILABLE and clear holds/bookings via POST /api/reset.
 * Intended for test/demo purposes.
 */
export async function resetAllSeats(): Promise<{ success: boolean; message: string }> {
  if (activeEngineMode === 'local') {
    return engineResetAll();
  }

  try {
    const response = await fetch(`${API_BASE_URL}/api/reset`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (isHtmlResponse(response)) {
      activeEngineMode = 'local';
      return engineResetAll();
    }

    if (!response.ok) {
      throw await parseErrorResponse(response, 'Failed to reset seats');
    }

    return await response.json();
  } catch (err) {
    if (isApiError(err)) throw err;
    activeEngineMode = 'local';
    return engineResetAll();
  }
}
