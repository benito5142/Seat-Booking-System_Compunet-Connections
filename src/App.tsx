import React, { useEffect, useState, useRef, useCallback } from 'react';
import { Seat, ActiveHold, BookingResponse } from './types';
import { EVENT_SPEC } from './config';
import { getSeats, createHold, releaseHold, confirmBooking, ApiError } from './api/client';
import { SeatMap } from './components/SeatMap';
import { HoldCountdown } from './components/HoldCountdown';
import {
  AlertCircle,
  CheckCircle2,
  Lock,
  Unlock,
  Ticket,
  Info,
  RefreshCw,
} from 'lucide-react';

export default function App() {
  // Authoritative seat list from GET /seats
  const [seats, setSeats] = useState<Seat[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);

  // User selections (up to 4 seats)
  const [selectedSeatIds, setSelectedSeatIds] = useState<string[]>([]);

  // Active hold state (5-minute TTL)
  const [activeHold, setActiveHold] = useState<ActiveHold | null>(null);

  // Confirmed booking state
  const [confirmedBooking, setConfirmedBooking] = useState<BookingResponse | null>(null);

  // Feedback and notification states
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [maxSeatsWarning, setMaxSeatsWarning] = useState<string | null>(null);

  // Action loading indicators
  const [holdSubmitting, setHoldSubmitting] = useState<boolean>(false);
  const [releaseSubmitting, setReleaseSubmitting] = useState<boolean>(false);
  const [confirmSubmitting, setConfirmSubmitting] = useState<boolean>(false);

  // Polling in-flight guard to prevent duplicate overlapping network requests
  const isPollingRef = useRef<boolean>(false);
  const selectedSeatsRef = useRef<string[]>([]);
  selectedSeatsRef.current = selectedSeatIds;

  /**
   * Fetch authoritative seat map from GET /seats.
   * Compares with current selection to remove any stale seats.
   */
  const loadSeats = useCallback(async (isManualRefresh: boolean = false) => {
    if (isPollingRef.current) return;
    isPollingRef.current = true;

    if (isManualRefresh) {
      setIsRefreshing(true);
    }

    try {
      const seatData = await getSeats();
      setSeats(seatData);

      // Verify currently selected seats against fresh backend data
      const currentSelected = selectedSeatsRef.current;
      if (currentSelected.length > 0) {
        const unavailable = currentSelected.filter((seatId) => {
          const seat = seatData.find((s) => s.id === seatId);
          return seat && seat.status.toLowerCase() !== 'available';
        });

        if (unavailable.length > 0) {
          // Remove stale selections as backend is authoritative
          setSelectedSeatIds((prev) => prev.filter((id) => !unavailable.includes(id)));
          setInfoMessage(
            `Notice: Seat${unavailable.length > 1 ? 's' : ''} ${unavailable.join(', ')} ${
              unavailable.length > 1 ? 'were' : 'was'
            } held or booked by another user and removed from your selection.`
          );
        }
      }
    } catch (err) {
      // In automatic polling, keep errors subtle; in manual refresh, display error
      if (isManualRefresh) {
        setErrorMessage(err instanceof Error ? err.message : 'Failed to refresh seat map');
      }
    } finally {
      setLoading(false);
      setIsRefreshing(false);
      isPollingRef.current = false;
    }
  }, []);

  // Initial load
  useEffect(() => {
    loadSeats();
  }, [loadSeats]);

  /**
   * Automatic Seat-Map Polling (~3-second interval):
   * 
   * Chosen specifications & rationale:
   * - 3 seconds provides quick, responsive visibility of other users' actions (holds, bookings, releases).
   * - Generates negligible network and database overhead for single-event booking.
   * - Simple, robust, and clean without introducing complex WebSocket infrastructure.
   * - Guarded by in-flight ref and cleaned up on unmount.
   */
  useEffect(() => {
    const pollInterval = setInterval(() => {
      loadSeats(false);
    }, EVENT_SPEC.pollingIntervalMs);

    return () => {
      clearInterval(pollInterval);
    };
  }, [loadSeats]);

  /**
   * Handle seat selection toggle.
   * Maximum 4 seats allowed.
   */
  const handleToggleSeat = (seatId: string) => {
    // Dismiss max seats warning on click
    setMaxSeatsWarning(null);

    // If seat is currently selected, deselect it
    if (selectedSeatIds.includes(seatId)) {
      setSelectedSeatIds((prev) => prev.filter((id) => id !== seatId));
      return;
    }

    // Check maximum 4 seats constraint
    if (selectedSeatIds.length >= EVENT_SPEC.maxSelectableSeats) {
      setMaxSeatsWarning(
        `You can select a maximum of ${EVENT_SPEC.maxSelectableSeats} seats. Deselect a seat first to choose another.`
      );
      return;
    }

    // Add to selection
    setSelectedSeatIds((prev) => [...prev, seatId]);
  };

  /**
   * Hold Flow: POST /holds
   * Places a 5-minute temporary hold on selected seats.
   */
  const handleCreateHold = async () => {
    if (selectedSeatIds.length === 0) return;

    setHoldSubmitting(true);
    setErrorMessage(null);
    setInfoMessage(null);
    setMaxSeatsWarning(null);

    try {
      const response = await createHold(selectedSeatIds, EVENT_SPEC.defaultUserId);

      // Store and display active hold
      const newHold: ActiveHold = {
        id: response.id || response.hold_id || response.hold_token,
        holdToken: response.hold_token,
        seats: response.seats || selectedSeatIds,
        expiresAt: response.expires_at,
        status: response.status || 'ACTIVE',
        userId: response.user_id,
      };

      setActiveHold(newHold);
      setConfirmedBooking(null);
      setInfoMessage(
        `Hold placed successfully! You have 5 minutes to confirm booking for seat(s): ${newHold.seats.join(', ')}.`
      );

      // Refresh seat map immediately to reflect HELD status from backend
      await loadSeats(false);
    } catch (err) {
      if (err instanceof ApiError) {
        // Concurrency conflict / stale seat scenario
        if (err.statusCode === 409) {
          const conflictSeats = err.unavailableSeats?.join(', ') || 'one or more selected seats';
          setErrorMessage(
            `Seat reservation conflict: ${conflictSeats} is no longer available because another user held it. Please choose another seat.`
          );
          // Remove unavailable seats from user selection
          if (err.unavailableSeats && err.unavailableSeats.length > 0) {
            setSelectedSeatIds((prev) => prev.filter((id) => !err.unavailableSeats!.includes(id)));
          }
        } else {
          setErrorMessage(err.message);
        }
      } else {
        setErrorMessage('An unexpected error occurred while placing hold');
      }

      // Authoritative backend refresh
      await loadSeats(false);
    } finally {
      setHoldSubmitting(false);
    }
  };

  /**
   * Release Hold Flow: DELETE /holds/{id}
   */
  const handleReleaseHold = async () => {
    if (!activeHold) return;

    setReleaseSubmitting(true);
    setErrorMessage(null);
    setMaxSeatsWarning(null);

    try {
      await releaseHold(activeHold.id);
      setActiveHold(null);
      setSelectedSeatIds([]);
      setInfoMessage('Hold released successfully. The seats are now available for selection.');
      await loadSeats(false);
    } catch (err) {
      if (err instanceof ApiError) {
        // If already expired or released, clear hold locally
        if (err.statusCode === 404 || err.statusCode === 400) {
          setActiveHold(null);
          setSelectedSeatIds([]);
          setInfoMessage('Hold had already expired or was already released.');
          await loadSeats(false);
          return;
        }
        setErrorMessage(err.message);
      } else {
        setErrorMessage('Failed to release hold');
      }
    } finally {
      setReleaseSubmitting(false);
    }
  };

  /**
   * Confirm Booking Flow: POST /bookings
   */
  const handleConfirmBooking = async () => {
    if (!activeHold) return;

    setConfirmSubmitting(true);
    setErrorMessage(null);
    setMaxSeatsWarning(null);

    try {
      const response = await confirmBooking(activeHold.id, EVENT_SPEC.defaultUserId);
      setConfirmedBooking(response);
      setActiveHold(null);
      setSelectedSeatIds([]);
      setInfoMessage(
        `Booking Confirmed! Reference: ${response.booking_reference} for seat(s): ${response.seats.join(', ')}`
      );
      await loadSeats(false);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.statusCode === 400 || err.statusCode === 409 || err.statusCode === 410) {
          setErrorMessage(
            `Unable to confirm booking: ${err.message}. If your hold has expired, please select seats again.`
          );
          setActiveHold(null);
          await loadSeats(false);
          return;
        }
        setErrorMessage(err.message);
      } else {
        setErrorMessage('An unexpected network error occurred while confirming booking');
      }
    } finally {
      setConfirmSubmitting(false);
    }
  };

  /**
   * Active hold expired countdown callback (when remaining reaches 0).
   */
  const handleHoldExpired = useCallback(() => {
    setActiveHold(null);
    setSelectedSeatIds([]);
    setInfoMessage('Your 5-minute seat hold has expired. The seats have been released back to available.');
    loadSeats(false);
  }, [loadSeats]);

  // Derive counts for summary
  const availableCount = seats.filter((s) => s.status.toLowerCase() === 'available').length;
  const heldCount = seats.filter((s) => s.status.toLowerCase() === 'held').length;
  const bookedCount = seats.filter((s) => s.status.toLowerCase() === 'booked').length;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col font-sans">
      {/* Top Application Bar */}
      <header id="app-header" className="bg-white border-b border-slate-200 sticky top-0 z-20">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-blue-600 text-white flex items-center justify-center font-bold text-base shadow-xs">
              SB
            </div>
            <div>
              <h1 className="text-base font-semibold text-slate-900 leading-tight">
                Seat Booking System
              </h1>
              <p className="text-xs text-slate-500">
                {EVENT_SPEC.name} • 10 Rows × 12 Seats (120 Total)
              </p>
            </div>
          </div>

          {/* Quick Stats & Polling Status */}
          <div className="flex items-center gap-4">
            <div className="hidden sm:flex items-center gap-3 text-xs">
              <span className="text-emerald-700 font-medium">
                {availableCount} Available
              </span>
              <span className="text-slate-300">•</span>
              <span className="text-amber-700 font-medium">
                {heldCount} Held
              </span>
              <span className="text-slate-300">•</span>
              <span className="text-slate-600 font-medium">
                {bookedCount} Booked
              </span>
            </div>

            <button
              id="refresh-seats-btn"
              type="button"
              onClick={() => loadSeats(true)}
              disabled={isRefreshing}
              title="Refresh seat map (automatic 3s polling active)"
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 border border-slate-200 transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">Refresh</span>
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="max-w-5xl mx-auto w-full px-4 sm:px-6 py-6 flex-1 flex flex-col gap-5">
        {/* Error Alert Banner */}
        {errorMessage && (
          <div
            id="error-alert-banner"
            role="alert"
            className="flex items-start justify-between gap-3 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm"
          >
            <div className="flex items-start gap-2.5">
              <AlertCircle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold">Action Failed</p>
                <p className="mt-0.5">{errorMessage}</p>
              </div>
            </div>
            <button
              id="dismiss-error-btn"
              type="button"
              onClick={() => setErrorMessage(null)}
              className="text-red-500 hover:text-red-700 text-xs font-bold px-2 py-1"
            >
              ✕
            </button>
          </div>
        )}

        {/* Info Alert Banner */}
        {infoMessage && (
          <div
            id="info-alert-banner"
            role="status"
            className="flex items-start justify-between gap-3 p-4 bg-blue-50 border border-blue-200 rounded-lg text-blue-900 text-sm"
          >
            <div className="flex items-start gap-2.5">
              <Info className="w-5 h-5 text-blue-600 shrink-0 mt-0.5" />
              <div>
                <p>{infoMessage}</p>
              </div>
            </div>
            <button
              id="dismiss-info-btn"
              type="button"
              onClick={() => setInfoMessage(null)}
              className="text-blue-500 hover:text-blue-700 text-xs font-bold px-2 py-1"
            >
              ✕
            </button>
          </div>
        )}

        {/* Max Seats Selection Warning */}
        {maxSeatsWarning && (
          <div
            id="max-seats-warning"
            role="alert"
            className="flex items-center justify-between gap-3 px-4 py-3 bg-amber-50 border border-amber-200 rounded-lg text-amber-900 text-sm"
          >
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-amber-600 shrink-0" />
              <span>{maxSeatsWarning}</span>
            </div>
            <button
              id="dismiss-max-warning-btn"
              type="button"
              onClick={() => setMaxSeatsWarning(null)}
              className="text-amber-700 hover:text-amber-900 text-xs font-bold"
            >
              ✕
            </button>
          </div>
        )}

        {/* Confirmed Booking Success Card */}
        {confirmedBooking && (
          <div
            id="confirmed-booking-card"
            className="p-5 bg-emerald-50 border border-emerald-300 rounded-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 shadow-xs"
          >
            <div className="flex items-start gap-3">
              <div className="p-2 bg-emerald-100 rounded-lg text-emerald-700">
                <Ticket className="w-6 h-6" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                  <span className="text-xs font-bold uppercase tracking-wider text-emerald-800">
                    Booking Confirmed
                  </span>
                </div>
                <p className="text-lg font-bold text-slate-900 mt-0.5">
                  Reference:{' '}
                  <span id="booking-reference-code" className="font-mono text-emerald-900">
                    {confirmedBooking.booking_reference}
                  </span>
                </p>
                <p className="text-xs text-slate-600 mt-1">
                  Seats: <strong className="text-slate-900">{confirmedBooking.seats.join(', ')}</strong> (
                  {confirmedBooking.seats.length} seat{confirmedBooking.seats.length > 1 ? 's' : ''})
                </p>
              </div>
            </div>
            <button
              id="dismiss-booking-card-btn"
              type="button"
              onClick={() => setConfirmedBooking(null)}
              className="px-3 py-1.5 text-xs font-medium text-emerald-800 bg-emerald-100 hover:bg-emerald-200 border border-emerald-300 rounded-md transition-colors"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Active Hold Control Panel */}
        {activeHold && (
          <div
            id="active-hold-panel"
            className="p-5 bg-white border-2 border-amber-300 rounded-xl shadow-xs flex flex-col md:flex-row items-start md:items-center justify-between gap-4"
          >
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold bg-amber-100 text-amber-900 border border-amber-300 uppercase">
                  <Lock className="w-3 h-3" /> Active Hold
                </span>
                <span id="active-hold-id" className="text-xs font-mono text-slate-500">
                  ID: #{activeHold.id}
                </span>
              </div>
              <p className="text-sm font-semibold text-slate-800">
                Held Seats:{' '}
                <span id="active-hold-seats-list" className="text-blue-700 font-bold">
                  {activeHold.seats.join(', ')}
                </span>
              </p>
              <p className="text-xs text-slate-500">
                Backend Expiry:{' '}
                <span className="font-mono">
                  {new Date(activeHold.expiresAt).toLocaleTimeString()}
                </span>
              </p>
            </div>

            {/* Countdown and Action Buttons */}
            <div className="flex flex-wrap items-center gap-3 w-full md:w-auto">
              <HoldCountdown
                expiresAt={activeHold.expiresAt}
                onExpired={handleHoldExpired}
              />

              <button
                id="release-hold-btn"
                type="button"
                onClick={handleReleaseHold}
                disabled={releaseSubmitting || confirmSubmitting}
                className="inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 border border-slate-300 rounded-md transition-colors disabled:opacity-50"
              >
                <Unlock className="w-3.5 h-3.5" />
                <span>{releaseSubmitting ? 'Releasing...' : 'Release Hold'}</span>
              </button>

              <button
                id="confirm-booking-btn"
                type="button"
                onClick={handleConfirmBooking}
                disabled={confirmSubmitting || releaseSubmitting}
                className="inline-flex items-center justify-center gap-1.5 px-4 py-2 text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-700 rounded-md shadow-xs transition-colors disabled:opacity-50"
              >
                <CheckCircle2 className="w-3.5 h-3.5" />
                <span>{confirmSubmitting ? 'Confirming...' : 'Confirm Booking'}</span>
              </button>
            </div>
          </div>
        )}

        {/* Selection and Hold Bar (when no active hold) */}
        {!activeHold && (
          <div
            id="selection-bar"
            className="p-4 bg-white border border-slate-200 rounded-xl shadow-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3"
          >
            <div>
              <p className="text-sm font-semibold text-slate-900">
                Selected Seats:{' '}
                {selectedSeatIds.length > 0 ? (
                  <span id="selected-seats-display" className="text-blue-600 font-bold">
                    {selectedSeatIds.join(', ')} ({selectedSeatIds.length}/{EVENT_SPEC.maxSelectableSeats})
                  </span>
                ) : (
                  <span id="no-seats-selected" className="text-slate-400 font-normal">
                    None (Click on up to 4 available seats below)
                  </span>
                )}
              </p>
              <p className="text-xs text-slate-500 mt-0.5">
                Seats are held for 5 minutes once submitted.
              </p>
            </div>

            <div className="flex items-center gap-2 w-full sm:w-auto">
              {selectedSeatIds.length > 0 && (
                <button
                  id="clear-selection-btn"
                  type="button"
                  onClick={() => setSelectedSeatIds([])}
                  className="px-3 py-2 text-xs font-medium text-slate-600 hover:text-slate-900 transition-colors"
                >
                  Clear
                </button>
              )}

              <button
                id="hold-selected-seats-btn"
                type="button"
                disabled={selectedSeatIds.length === 0 || holdSubmitting || loading}
                onClick={handleCreateHold}
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg text-xs font-bold text-white bg-blue-600 hover:bg-blue-700 disabled:bg-slate-200 disabled:text-slate-400 disabled:cursor-not-allowed shadow-xs transition-colors"
              >
                <Lock className="w-3.5 h-3.5" />
                <span>
                  {holdSubmitting
                    ? 'Placing Hold...'
                    : `Hold ${selectedSeatIds.length > 0 ? `(${selectedSeatIds.length})` : ''} Selected Seat${
                        selectedSeatIds.length !== 1 ? 's' : ''
                      }`}
                </span>
              </button>
            </div>
          </div>
        )}

        {/* 120-Seat Venue Map */}
        <section id="venue-seat-map-section" className="flex-1 flex flex-col items-center">
          {loading && seats.length === 0 ? (
            <div id="loading-seats-indicator" className="py-20 text-center text-slate-500">
              <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-2 text-slate-400" />
              <p className="text-sm">Loading seat map from server...</p>
            </div>
          ) : (
            <SeatMap
              seats={seats}
              selectedSeatIds={selectedSeatIds}
              activeHoldSeatIds={activeHold ? activeHold.seats : []}
              onToggleSeat={handleToggleSeat}
              disabled={Boolean(activeHold)}
            />
          )}
        </section>
      </main>

      {/* Simple assessment footer */}
      <footer id="app-footer" className="bg-white border-t border-slate-200 py-4 text-center text-xs text-slate-500">
        <p>
          Seat Booking System Assessment • Backend Concurrency Hardened (SELECT FOR UPDATE + Atomic State Transitions)
        </p>
      </footer>
    </div>
  );
}
