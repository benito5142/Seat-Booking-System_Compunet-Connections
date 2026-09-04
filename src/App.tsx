import { useEffect, useState } from 'react';
import { API_BASE_URL, EVENT_SPEC } from './config';
import { checkBackendHealth, HealthResponse } from './api/client';
import { Server, CheckCircle2, AlertCircle, RefreshCw } from 'lucide-react';

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchHealth = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await checkBackendHealth();
      setHealth(data);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Unable to connect to FastAPI backend at ' + API_BASE_URL
      );
      setHealth(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHealth();
  }, []);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col justify-between font-sans">
      <main className="max-w-2xl mx-auto w-full px-6 py-16">
        <header className="mb-10 text-center">
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">
            Seat Booking System
          </h1>
          <p className="mt-2 text-sm text-slate-600">
            Coding Assessment: Single Event Fixed Seat Map
          </p>
        </header>

        {/* Fixed Event Specifications */}
        <section
          id="event-specs-card"
          className="bg-white border border-slate-200 rounded-xl p-6 mb-6 shadow-xs"
        >
          <h2 className="text-base font-semibold text-slate-800 mb-4">
            Event Specifications
          </h2>
          <div className="grid grid-cols-3 gap-4 text-center">
            <div className="bg-slate-50 p-3 rounded-lg border border-slate-100">
              <span className="block text-2xl font-bold text-slate-900">
                {EVENT_SPEC.totalRows}
              </span>
              <span className="text-xs text-slate-500 font-medium">Rows</span>
            </div>
            <div className="bg-slate-50 p-3 rounded-lg border border-slate-100">
              <span className="block text-2xl font-bold text-slate-900">
                {EVENT_SPEC.seatsPerRow}
              </span>
              <span className="text-xs text-slate-500 font-medium">
                Seats per Row
              </span>
            </div>
            <div className="bg-slate-50 p-3 rounded-lg border border-slate-100">
              <span className="block text-2xl font-bold text-slate-900">
                {EVENT_SPEC.totalSeats}
              </span>
              <span className="text-xs text-slate-500 font-medium">
                Total Seats
              </span>
            </div>
          </div>
        </section>

        {/* Backend API Configuration & Status */}
        <section
          id="api-status-card"
          className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs"
        >
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center space-x-2">
              <Server className="w-5 h-5 text-slate-600" />
              <h2 className="text-base font-semibold text-slate-800">
                Backend API Connection
              </h2>
            </div>
            <button
              id="refresh-health-btn"
              onClick={fetchHealth}
              disabled={loading}
              className="inline-flex items-center text-xs font-medium text-slate-600 hover:text-slate-900 px-2.5 py-1.5 rounded-md hover:bg-slate-100 transition-colors cursor-pointer disabled:opacity-50"
            >
              <RefreshCw
                className={`w-3.5 h-3.5 mr-1.5 ${loading ? 'animate-spin' : ''}`}
              />
              Check Status
            </button>
          </div>

          <div className="text-xs text-slate-500 mb-3">
            Configured API Base URL:{' '}
            <code className="bg-slate-100 px-1.5 py-0.5 rounded text-slate-700 font-mono">
              {API_BASE_URL}
            </code>
          </div>

          {loading ? (
            <div className="p-4 bg-slate-50 rounded-lg text-xs text-slate-600 flex items-center">
              <span className="w-2 h-2 rounded-full bg-amber-400 mr-2 animate-pulse" />
              Connecting to backend service...
            </div>
          ) : health ? (
            <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-lg text-xs text-emerald-800 flex items-start space-x-2.5">
              <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold">Backend Connected:</span>{' '}
                {health.status} ({health.service})
              </div>
            </div>
          ) : (
            <div className="p-4 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-600 flex items-start space-x-2.5">
              <AlertCircle className="w-4 h-4 text-slate-400 shrink-0 mt-0.5" />
              <div>
                <span className="font-medium text-slate-700">
                  Backend offline or awaiting start:
                </span>{' '}
                {error || 'No active connection'}.
              </div>
            </div>
          )}
        </section>
      </main>

      <footer className="text-center py-6 text-xs text-slate-400 border-t border-slate-200">
        Project Initialization & Configuration • Step 1
      </footer>
    </div>
  );
}
