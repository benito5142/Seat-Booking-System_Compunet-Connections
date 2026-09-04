export const API_BASE_URL =
  import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const EVENT_SPEC = {
  name: 'Main Event',
  totalRows: 10,
  seatsPerRow: 12,
  totalSeats: 120,
};
