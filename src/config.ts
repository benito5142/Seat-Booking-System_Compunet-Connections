// Frontend configuration for API endpoints and fixed event specifications

export const API_BASE_URL =
  import.meta.env.VITE_API_URL || '';

export const EVENT_SPEC = {
  name: 'Main Event',
  totalRows: 10,
  seatsPerRow: 12,
  totalSeats: 120,
};
