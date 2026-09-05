import { API_BASE_URL } from '../config';
import { Seat, HoldResponse, BookingResponse } from '../types';

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
 * Check health status of FastAPI backend.
 */
export async function checkBackendHealth(): Promise<HealthResponse> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/health`);
    if (!response.ok) {
      throw await parseErrorResponse(response, 'Health check failed');
    }
    return response.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError('Unable to connect to backend service', 0);
  }
}

/**
 * Fetch fixed event information.
 */
export async function getEventInfo(): Promise<EventInfoResponse> {
  const response = await fetch(`${API_BASE_URL}/api/event/info`);
  if (!response.ok) {
    throw await parseErrorResponse(response, 'Failed to fetch event info');
  }
  return response.json();
}

/**
 * Fetch the authoritative seat map from GET /seats.
 * Returns 120 seats with status: 'available' | 'held' | 'booked'.
 */
export async function getSeats(): Promise<Seat[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/seats`, {
      headers: {
        'Accept': 'application/json',
      },
    });
    if (!response.ok) {
      throw await parseErrorResponse(response, 'Failed to fetch seat map');
    }
    const data = await response.json();
    if (!Array.isArray(data)) {
      throw new ApiError('Invalid seat data format received from server', response.status);
    }
    return data;
  } catch (err) {
    if (isApiError(err)) throw err;
    const msg = err instanceof Error ? err.message : 'Network error while loading seat map';
    throw new ApiError(msg, 0);
  }
}

/**
 * Request a temporary 5-minute hold on up to 4 seats via POST /holds.
 */
export async function createHold(seats: string[], userId: string = 'user_1'): Promise<HoldResponse> {
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

    if (!response.ok) {
      throw await parseErrorResponse(response, 'Failed to place hold on seats');
    }

    return await response.json();
  } catch (err) {
    if (isApiError(err)) throw err;
    const msg = err instanceof Error ? err.message : 'Network error while placing hold';
    throw new ApiError(msg, 0);
  }
}

/**
 * Release an active hold via DELETE /holds/{id}.
 * Transitions held seats back to AVAILABLE.
 */
export async function releaseHold(holdIdentifier: string | number): Promise<{ status: string; message: string }> {
  try {
    const response = await fetch(`${API_BASE_URL}/holds/${encodeURIComponent(holdIdentifier)}`, {
      method: 'DELETE',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      throw await parseErrorResponse(response, 'Failed to release hold');
    }

    return await response.json();
  } catch (err) {
    if (isApiError(err)) throw err;
    const msg = err instanceof Error ? err.message : 'Network error while releasing hold';
    throw new ApiError(msg, 0);
  }
}

/**
 * Confirm an active hold into a completed booking via POST /bookings.
 * Converts held seats to BOOKED and provides a unique booking reference.
 */
export async function confirmBooking(holdId: string | number, userId: string = 'user_1'): Promise<BookingResponse> {
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

    if (!response.ok) {
      throw await parseErrorResponse(response, 'Failed to confirm booking');
    }

    return await response.json();
  } catch (err) {
    if (isApiError(err)) throw err;
    const msg = err instanceof Error ? err.message : 'Network error while confirming booking';
    throw new ApiError(msg, 0);
  }
}

/**
 * Reset all seats to AVAILABLE and clear holds/bookings via POST /api/reset.
 * Intended for test/demo purposes.
 */
export async function resetAllSeats(): Promise<{ success: boolean; message: string }> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/reset`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      throw await parseErrorResponse(response, 'Failed to reset seats');
    }

    return await response.json();
  } catch (err) {
    if (isApiError(err)) throw err;
    const msg = err instanceof Error ? err.message : 'Network error while resetting seats';
    throw new ApiError(msg, 0);
  }
}
