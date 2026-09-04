import { API_BASE_URL } from '../config';

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

export async function checkBackendHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/api/health`);
  if (!response.ok) {
    throw new Error(`Health check failed with status: ${response.status}`);
  }
  return response.json();
}

export async function getEventInfo(): Promise<EventInfoResponse> {
  const response = await fetch(`${API_BASE_URL}/api/event/info`);
  if (!response.ok) {
    throw new Error(`Failed to fetch event info: ${response.status}`);
  }
  return response.json();
}
