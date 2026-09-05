// Frontend configuration for API endpoints and fixed event specifications

// When VITE_API_URL is configured (e.g. in local standalone mode), use it.
// In container or production mode, default to '' to use relative paths with the reverse proxy.
export const API_BASE_URL =
  import.meta.env.VITE_API_URL !== undefined
    ? import.meta.env.VITE_API_URL
    : '';

export const EVENT_SPEC = {
  name: 'Main Event',
  totalRows: 10,
  seatsPerRow: 12,
  totalSeats: 120,
  rows: ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J'] as const,
  maxSelectableSeats: 4,
  defaultUserId: 'user_1',
  /**
   * Automatic Seat-Map Polling Interval (3000ms / 3 seconds):
   * 
   * A 3-second polling interval was chosen because:
   * 1. It is responsive enough for a small booking application to feel up-to-date.
   * 2. It provides reasonably quick visibility of other users' actions (holds, bookings, releases).
   * 3. It generates low request volume and minimal overhead on the server and database.
   * 4. It is simple, highly reliable, and appropriate for the assessment without requiring
   *    unnecessary WebSocket infrastructure.
   */
  pollingIntervalMs: 3000,
};
