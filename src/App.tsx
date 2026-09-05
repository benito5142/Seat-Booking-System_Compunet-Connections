import React, { useEffect, useState, useRef, useCallback } from 'react';
import { Seat, ActiveHold, BookingResponse } from './types';
import { EVENT_SPEC } from './config';
import { getSeats, createHold, releaseHold, confirmBooking, resetAllSeats, ApiError } from './api/client';
import { SeatMap } from './components/SeatMap';
import { HoldCountdown } from './components/HoldCountdown';
import movieBannerImg from './assets/images/movie_event_banner_1788586861818.jpg';
import eventPosterImg from './assets/images/event_poster_thumb_1788586878308.jpg';
import {
  AlertCircle,
  CheckCircle2,
  Lock,
  Unlock,
  Ticket,
  Info,
  RefreshCw,
  Film,
  MapPin,
  Calendar,
  Clock,
  Sparkles,
  ShieldCheck,
  Search,
  ChevronDown,
  Copy,
  Check,
  RotateCcw,
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
  const [copiedRef, setCopiedRef] = useState<boolean>(false);

  // Feedback and notification states
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [maxSeatsWarning, setMaxSeatsWarning] = useState<string | null>(null);

  // Action loading indicators
  const [holdSubmitting, setHoldSubmitting] = useState<boolean>(false);
  const [releaseSubmitting, setReleaseSubmitting] = useState<boolean>(false);
  const [confirmSubmitting, setConfirmSubmitting] = useState<boolean>(false);
  const [isResetting, setIsResetting] = useState<boolean>(false);
  const [justRefreshed, setJustRefreshed] = useState<boolean>(false);

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
      setErrorMessage(null);
    }

    try {
      const startTime = Date.now();
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

      if (isManualRefresh) {
        const elapsed = Date.now() - startTime;
        if (elapsed < 400) {
          await new Promise((resolve) => setTimeout(resolve, 400 - elapsed));
        }
        setJustRefreshed(true);
        setTimeout(() => setJustRefreshed(false), 2000);
      }
    } catch (err) {
      // If no seats are loaded yet or it was a manual refresh, display informative notice
      if (isManualRefresh || seats.length === 0) {
        setErrorMessage(
          err instanceof Error
            ? `Connection notice: ${err.message}`
            : 'Connecting to seat booking service...'
        );
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
   * Automatic Seat-Map Polling (~3-second interval)
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
   * Reset All Seats Flow: POST /api/reset (Project Demo Testing Tool)
   * Restores all 120 seats to AVAILABLE, clearing all holds and bookings.
   * Note: Normal page reloads and refreshes continue to preserve persistent state.
   */
  const handleResetAllSeats = async () => {
    setIsResetting(true);
    setErrorMessage(null);
    setMaxSeatsWarning(null);

    try {
      const result = await resetAllSeats();
      setActiveHold(null);
      setSelectedSeatIds([]);
      setConfirmedBooking(null);
      setInfoMessage(result.message || 'All seats have been reset to Available.');
      await loadSeats(false);
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('Failed to reset seats');
      }
    } finally {
      setIsResetting(false);
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

  const handleCopyBookingRef = (reference: string) => {
    navigator.clipboard.writeText(reference);
    setCopiedRef(true);
    setTimeout(() => setCopiedRef(false), 2000);
  };

  // Derive counts for summary
  const availableCount = seats.filter((s) => s.status.toLowerCase() === 'available').length;
  const heldCount = seats.filter((s) => s.status.toLowerCase() === 'held').length;
  const bookedCount = seats.filter((s) => s.status.toLowerCase() === 'booked').length;

  // Approximate pricing calculation for display realism
  const calculateTotalEstimate = () => {
    let total = 0;
    selectedSeatIds.forEach((id) => {
      const row = id[0];
      if (['A', 'B', 'C'].includes(row)) total += 350;
      else if (['D', 'E', 'F', 'G'].includes(row)) total += 250;
      else total += 150;
    });
    return total;
  };

  return (
    <div className="min-h-screen w-full max-w-full overflow-x-hidden bg-[#F5F5F7] text-slate-900 flex flex-col font-sans selection:bg-rose-500 selection:text-white">
      {/* BookMyShow Style Signature Dark Header Bar */}
      <header id="app-header" className="bg-[#1F2533] text-white sticky top-0 z-30 shadow-md">
        {/* Main Brand & Navigation Row */}
        <div className="max-w-6xl mx-auto px-3 sm:px-6 h-16 flex items-center justify-between gap-2 sm:gap-4">
          <div className="flex items-center gap-3 sm:gap-6 min-w-0">
            {/* BookMyShow Logo Emblem */}
            <div className="flex items-center gap-2 cursor-pointer select-none shrink-0">
              <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-xl bg-gradient-to-tr from-[#E03A58] to-[#F84464] flex items-center justify-center shadow-lg shadow-rose-600/30 shrink-0">
                <Ticket className="w-5 h-5 sm:w-6 sm:h-6 text-white transform -rotate-12" />
              </div>
              <div className="flex flex-col">
                <div className="text-lg sm:text-xl font-black tracking-tight leading-none whitespace-nowrap">
                  book<span className="text-[#F84464]">my</span>seat
                </div>
                <span className="text-[9px] sm:text-[10px] text-slate-400 font-semibold tracking-widest uppercase mt-0.5 whitespace-nowrap">
                  Cinema & Events
                </span>
              </div>
            </div>

            {/* Mock City & Search Input - Shown only on large desktop screens to prevent tablet header overflow */}
            <div className="hidden lg:flex items-center bg-[#2B3144] rounded-lg px-3 py-2 w-48 xl:w-72 text-xs text-slate-300 border border-slate-700/60 focus-within:border-[#F84464] transition-colors">
              <Search className="w-4 h-4 text-slate-400 mr-2 shrink-0" />
              <span className="text-slate-400 select-none truncate">
                Search Movies, Plays...
              </span>
            </div>
          </div>

          {/* Right Header Navigation & Actions - Fully responsive & compact on mobile/tablet */}
          <div className="flex items-center gap-1.5 sm:gap-2.5 shrink-0">
            {/* Location Selector Pill - Desktop only */}
            <div className="hidden xl:flex items-center gap-1.5 text-xs text-slate-300 hover:text-white cursor-pointer px-2 py-1 select-none shrink-0">
              <MapPin className="w-3.5 h-3.5 text-[#F84464]" />
              <span className="font-semibold">Bengaluru</span>
              <ChevronDown className="w-3 h-3 text-slate-400" />
            </div>

            {/* Live Polling Status Pill - Responsive (hidden on mobile/tablet to give action buttons priority) */}
            <div className="hidden md:inline-flex items-center gap-1.5 px-2.5 sm:px-3 py-1 rounded-full bg-[#111622] border border-emerald-500/30 text-emerald-400 text-xs shadow-2xs shrink-0">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="font-medium text-[11px] tracking-wide whitespace-nowrap">Live 3s Polling</span>
            </div>

            {/* Refresh Button */}
            <button
              id="refresh-seats-btn"
              type="button"
              onClick={() => loadSeats(true)}
              disabled={isRefreshing}
              title="Refresh seat map (automatic 3s polling active)"
              className="inline-flex items-center justify-center gap-1 sm:gap-1.5 px-2 sm:px-3 py-1.5 rounded-lg text-xs font-semibold text-white bg-[#2B3144] hover:bg-[#39415A] border border-slate-700 transition-all disabled:opacity-50 cursor-pointer shadow-xs active:scale-95 shrink-0 whitespace-nowrap"
            >
              {justRefreshed ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  <span className="text-emerald-400 font-medium text-[11px] sm:text-xs">Refreshed</span>
                </>
              ) : (
                <>
                  <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin text-[#F84464]' : 'text-slate-300'} shrink-0`} />
                  <span className="text-[11px] sm:text-xs">{isRefreshing ? 'Refreshing...' : 'Refresh'}</span>
                </>
              )}
            </button>

            {/* Project Demo Reset Button */}
            <button
              id="quick-reset-seats-btn"
              type="button"
              onClick={handleResetAllSeats}
              disabled={isResetting}
              title="Reset all 120 seats to Available"
              className="inline-flex items-center justify-center gap-1 sm:gap-1.5 text-xs text-slate-200 hover:text-white transition-all px-2 sm:px-3 py-1.5 rounded-lg bg-[#2B3144]/80 hover:bg-[#39415A] border border-slate-700 cursor-pointer disabled:opacity-50 shadow-xs active:scale-95 shrink-0 whitespace-nowrap"
            >
              <RotateCcw className={`w-3.5 h-3.5 ${isResetting ? 'animate-spin text-[#F84464]' : 'text-slate-400'} shrink-0`} />
              <span className="text-[11px] sm:text-xs font-medium">{isResetting ? 'Resetting...' : 'Reset Seats'}</span>
            </button>
          </div>
        </div>

        {/* Theatrical Subheader Strip */}
        <div className="bg-[#121622] border-t border-slate-800/80 px-3 sm:px-6 py-2">
          <div className="max-w-6xl mx-auto flex flex-col sm:flex-row sm:items-center justify-between gap-1.5 sm:gap-3 text-xs">
            <div className="flex flex-wrap items-center gap-1.5 sm:gap-2 text-slate-300">
              <span className="font-bold text-white text-xs sm:text-sm tracking-wide">
                {EVENT_SPEC.name}
              </span>
              <span className="text-slate-600">•</span>
              <span className="text-rose-400 font-semibold bg-rose-950/60 px-2 py-0.5 rounded border border-rose-800/40 text-[10px] sm:text-[11px]">
                IMAX 2D
              </span>
              <span className="text-slate-600">•</span>
              <span className="text-slate-400 text-[11px] sm:text-xs">PVR INOX: Grand Rex Audi 01</span>
            </div>

            <div className="flex items-center gap-2.5 sm:gap-3 text-slate-400 text-[11px] sm:text-xs">
              <span className="flex items-center gap-1">
                <Calendar className="w-3.5 h-3.5 text-[#F84464] shrink-0" /> Today, 07:30 PM
              </span>
              <span className="text-slate-600">•</span>
              <span className="flex items-center gap-1">
                <Film className="w-3.5 h-3.5 text-blue-400 shrink-0" /> Dolby Atmos 7.1
              </span>
            </div>
          </div>
        </div>
      </header>

      {/* Cinematic Hero Poster Banner */}
      <section className="relative w-full bg-[#0E121D] text-white overflow-hidden shadow-inner border-b border-slate-800">
        {/* Background Banner Image with Dark Vignette */}
        <div className="absolute inset-0 z-0 opacity-40 mix-blend-screen">
          <img
            src={movieBannerImg}
            alt="Event Stage Backdrop"
            referrerPolicy="no-referrer"
            className="w-full h-full object-cover object-center filter blur-[1px]"
          />
        </div>
        <div className="absolute inset-0 bg-gradient-to-t from-[#0E121D] via-[#0E121D]/75 to-transparent z-0" />
        <div className="absolute inset-0 bg-gradient-to-r from-[#0E121D] via-transparent to-[#0E121D] z-0" />

        {/* Banner Content */}
        <div className="relative z-10 max-w-6xl mx-auto px-3 sm:px-6 py-4 sm:py-7 flex flex-col md:flex-row items-center md:items-end justify-between gap-4 sm:gap-6">
          {/* Poster & Movie Title Block */}
          <div className="flex items-center gap-3.5 sm:gap-5 w-full md:w-auto">
            <div className="relative shrink-0 w-20 sm:w-28 rounded-xl overflow-hidden shadow-2xl border-2 border-white/20 bg-slate-900 group">
              <img
                src={eventPosterImg}
                alt="Event Poster"
                referrerPolicy="no-referrer"
                className="w-full h-28 sm:h-40 object-cover group-hover:scale-105 transition-transform duration-300"
              />
              <span className="absolute top-1 left-1 sm:top-1.5 sm:left-1.5 px-1.5 py-0.5 rounded bg-[#F84464] text-[8px] sm:text-[9px] font-black tracking-wider uppercase shadow-xs">
                LIVE
              </span>
            </div>

            <div className="flex flex-col gap-1 sm:gap-1.5 min-w-0">
              <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
                <span className="px-1.5 sm:px-2 py-0.5 rounded bg-white/10 text-white font-bold text-[9px] sm:text-[10px] border border-white/20">
                  UA 16+
                </span>
                <span className="px-1.5 sm:px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 font-semibold text-[9px] sm:text-[10px] border border-rose-500/30">
                  Sci-Fi Concert Premiere
                </span>
                <span className="text-slate-400 text-[11px] sm:text-xs flex items-center gap-1">
                  <Clock className="w-3 h-3 text-slate-400" /> 2h 45m
                </span>
              </div>

              <h2 className="text-xl sm:text-2xl md:text-3xl font-extrabold text-white tracking-tight leading-tight">
                {EVENT_SPEC.name}
              </h2>

              <p className="text-[11px] sm:text-xs text-slate-300 flex items-center gap-1.5 mt-0.5">
                <Sparkles className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                <span className="truncate">Auditorium Seating: 10 Rows × 12 Columns • 120 Seats</span>
              </p>
            </div>
          </div>

          {/* Real-time Inventory Pills */}
          <div className="flex items-center justify-around sm:justify-center gap-2 sm:gap-3 w-full md:w-auto shrink-0 bg-black/40 backdrop-blur-md p-2.5 sm:p-3 rounded-xl border border-white/10">
            <div className="text-center px-2 sm:px-3">
              <span className="block text-base sm:text-lg font-black text-emerald-400 leading-tight">
                {availableCount}
              </span>
              <span className="text-[9px] sm:text-[10px] uppercase tracking-wider font-semibold text-slate-400">
                Available
              </span>
            </div>
            <div className="w-px h-7 sm:h-8 bg-white/10" />
            <div className="text-center px-2 sm:px-3">
              <span className="block text-base sm:text-lg font-black text-amber-400 leading-tight">
                {heldCount}
              </span>
              <span className="text-[9px] sm:text-[10px] uppercase tracking-wider font-semibold text-slate-400">
                Held
              </span>
            </div>
            <div className="w-px h-7 sm:h-8 bg-white/10" />
            <div className="text-center px-2 sm:px-3">
              <span className="block text-base sm:text-lg font-black text-slate-400 leading-tight">
                {bookedCount}
              </span>
              <span className="text-[9px] sm:text-[10px] uppercase tracking-wider font-semibold text-slate-400">
                Booked
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* Main Content Area */}
      <main className="max-w-5xl mx-auto w-full px-4 sm:px-6 py-6 flex-1 flex flex-col gap-5">
        {/* Error Alert Banner */}
        {errorMessage && (
          <div
            id="error-alert-banner"
            role="alert"
            className="flex items-start justify-between gap-3 p-4 bg-rose-50 border-2 border-rose-300 rounded-xl text-rose-900 text-sm shadow-xs animate-shake"
          >
            <div className="flex items-start gap-3">
              <div className="p-1.5 bg-rose-100 rounded-lg text-rose-600 shrink-0 mt-0.5">
                <AlertCircle className="w-5 h-5" />
              </div>
              <div>
                <p className="font-bold text-rose-950">Seat Booking Conflict / Error</p>
                <p className="mt-0.5 text-rose-800 leading-relaxed">{errorMessage}</p>
              </div>
            </div>
            <button
              id="dismiss-error-btn"
              type="button"
              onClick={() => setErrorMessage(null)}
              className="text-rose-500 hover:text-rose-700 text-xs font-bold px-2 py-1 cursor-pointer"
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
            className="flex items-start justify-between gap-3 p-4 bg-blue-50 border-2 border-blue-200 rounded-xl text-blue-900 text-sm shadow-xs"
          >
            <div className="flex items-start gap-3">
              <div className="p-1.5 bg-blue-100 rounded-lg text-blue-600 shrink-0 mt-0.5">
                <Info className="w-5 h-5" />
              </div>
              <div>
                <p className="font-medium leading-relaxed">{infoMessage}</p>
              </div>
            </div>
            <button
              id="dismiss-info-btn"
              type="button"
              onClick={() => setInfoMessage(null)}
              className="text-blue-500 hover:text-blue-700 text-xs font-bold px-2 py-1 cursor-pointer"
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
            className="flex items-center justify-between gap-3 px-4 py-3 bg-amber-50 border-2 border-amber-300 rounded-xl text-amber-900 text-sm shadow-xs"
          >
            <div className="flex items-center gap-2.5">
              <AlertCircle className="w-5 h-5 text-amber-600 shrink-0" />
              <span className="font-medium">{maxSeatsWarning}</span>
            </div>
            <button
              id="dismiss-max-warning-btn"
              type="button"
              onClick={() => setMaxSeatsWarning(null)}
              className="text-amber-700 hover:text-amber-900 text-xs font-bold cursor-pointer"
            >
              ✕
            </button>
          </div>
        )}

        {/* Confirmed Booking Success Card (BookMyShow E-Ticket Style) */}
        {confirmedBooking && (
          <div
            id="confirmed-booking-card"
            className="p-6 bg-gradient-to-br from-emerald-50 via-white to-emerald-50 border-2 border-emerald-400 rounded-2xl flex flex-col md:flex-row items-start md:items-center justify-between gap-6 shadow-md"
          >
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-xl bg-emerald-600 text-white flex items-center justify-center shrink-0 shadow-md shadow-emerald-600/30">
                <Ticket className="w-7 h-7" />
              </div>
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                  <span className="text-xs font-black uppercase tracking-wider text-emerald-800">
                    Booking Confirmed • E-Ticket Issued
                  </span>
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-sm font-semibold text-slate-600">Reference:</span>
                  <span
                    id="booking-reference-code"
                    className="font-mono text-xl font-black text-emerald-950 bg-emerald-100/80 px-2.5 py-0.5 rounded border border-emerald-300"
                  >
                    {confirmedBooking.booking_reference}
                  </span>
                  <button
                    type="button"
                    onClick={() => handleCopyBookingRef(confirmedBooking.booking_reference)}
                    title="Copy Reference Code"
                    className="p-1 rounded hover:bg-emerald-200 text-emerald-800 transition-colors"
                  >
                    {copiedRef ? <Check className="w-4 h-4 text-emerald-700" /> : <Copy className="w-4 h-4" />}
                  </button>
                </div>
                <p className="text-xs text-slate-600 mt-1">
                  Confirmed Seats:{' '}
                  <span className="font-bold text-slate-900 text-sm">
                    {confirmedBooking.seats.join(', ')}
                  </span>{' '}
                  ({confirmedBooking.seats.length} ticket{confirmedBooking.seats.length > 1 ? 's' : ''}) • Auditorium 01
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3 w-full md:w-auto justify-end">
              <button
                id="dismiss-booking-card-btn"
                type="button"
                onClick={() => setConfirmedBooking(null)}
                className="px-4 py-2 text-xs font-bold text-emerald-900 bg-white hover:bg-emerald-100 border border-emerald-300 rounded-lg transition-colors cursor-pointer shadow-2xs"
              >
                Book More Seats
              </button>
            </div>
          </div>
        )}

        {/* Active Hold Control Panel (BookMyShow Payment / Timer Stage) */}
        {activeHold && (
          <div
            id="active-hold-panel"
            className="p-4 sm:p-5 bg-gradient-to-r from-amber-50 via-white to-amber-50 border-2 border-amber-400 rounded-2xl shadow-sm flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4"
          >
            <div className="flex flex-col gap-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-black bg-amber-400 text-amber-950 uppercase tracking-wider shadow-2xs">
                  <Lock className="w-3 h-3" /> Locked & Held
                </span>
                <span id="active-hold-id" className="text-xs font-mono text-slate-500">
                  Hold #{activeHold.id}
                </span>
              </div>
              <p className="text-sm font-bold text-slate-900">
                Held Seats:{' '}
                <span id="active-hold-seats-list" className="text-emerald-700 font-extrabold text-base">
                  {activeHold.seats.join(', ')}
                </span>
                <span className="text-slate-500 font-normal ml-2 text-xs sm:text-sm">
                  ({activeHold.seats.length} seat{activeHold.seats.length > 1 ? 's' : ''} reserved)
                </span>
              </p>
              <p className="text-xs text-slate-500 flex items-center gap-1">
                <Clock className="w-3 h-3 text-slate-400" />
                Backend Lock Expiry:{' '}
                <span className="font-mono font-semibold text-slate-700">
                  {new Date(activeHold.expiresAt).toLocaleTimeString()}
                </span>
              </p>
            </div>

            {/* Countdown and Action Buttons */}
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5 sm:gap-3 w-full lg:w-auto">
              <div className="self-center sm:self-auto">
                <HoldCountdown
                  expiresAt={activeHold.expiresAt}
                  onExpired={handleHoldExpired}
                />
              </div>

              <button
                id="release-hold-btn"
                type="button"
                onClick={handleReleaseHold}
                disabled={releaseSubmitting || confirmSubmitting}
                className="inline-flex items-center justify-center gap-1.5 px-3.5 py-2 text-xs font-bold text-slate-700 bg-white hover:bg-slate-100 border border-slate-300 rounded-lg transition-colors disabled:opacity-50 cursor-pointer shadow-2xs min-h-[40px]"
              >
                <Unlock className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                <span>{releaseSubmitting ? 'Releasing...' : 'Release Hold'}</span>
              </button>

              <button
                id="confirm-booking-btn"
                type="button"
                onClick={handleConfirmBooking}
                disabled={confirmSubmitting || releaseSubmitting}
                className="inline-flex items-center justify-center gap-1.5 px-5 py-2.5 text-xs font-extrabold text-white bg-gradient-to-r from-emerald-600 to-emerald-700 hover:from-emerald-700 hover:to-emerald-800 rounded-lg shadow-md shadow-emerald-600/30 transition-all disabled:opacity-50 cursor-pointer uppercase tracking-wider min-h-[40px]"
              >
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                <span>{confirmSubmitting ? 'Confirming Ticket...' : 'Confirm & Book Ticket'}</span>
              </button>
            </div>
          </div>
        )}

        {/* Selection and Hold Bar (BookMyShow Bottom Action Bar) */}
        {!activeHold && (
          <div
            id="selection-bar"
            className="p-4 sm:p-5 bg-white border border-slate-200/80 rounded-2xl shadow-sm flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4"
          >
            <div className="min-w-0">
              <p className="text-sm font-bold text-slate-900 flex flex-wrap items-center gap-1.5 sm:gap-2">
                <span>Selected Seats:</span>
                {selectedSeatIds.length > 0 ? (
                  <span id="selected-seats-display" className="text-emerald-700 font-extrabold text-sm sm:text-base">
                    {selectedSeatIds.join(', ')} ({selectedSeatIds.length}/{EVENT_SPEC.maxSelectableSeats})
                  </span>
                ) : (
                  <span id="no-seats-selected" className="text-slate-400 font-normal text-xs sm:text-sm">
                    None (Tap on up to 4 available seats in the map)
                  </span>
                )}
              </p>
              <p className="text-xs text-slate-500 mt-1 flex flex-wrap items-center gap-2">
                <span>Hold Duration: <strong>5 minutes</strong></span>
                {selectedSeatIds.length > 0 && (
                  <>
                    <span className="hidden xs:inline">•</span>
                    <span className="text-[#F84464] font-bold">
                      Estimated Total: ₹{calculateTotalEstimate()}
                    </span>
                  </>
                )}
              </p>
            </div>

            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5 shrink-0">
              {selectedSeatIds.length > 0 && (
                <button
                  id="clear-selection-btn"
                  type="button"
                  onClick={() => setSelectedSeatIds([])}
                  className="px-3.5 py-2 text-xs font-semibold text-slate-600 hover:text-slate-900 transition-colors cursor-pointer text-center"
                >
                  Clear Selection
                </button>
              )}

              <button
                id="hold-selected-seats-btn"
                type="button"
                disabled={selectedSeatIds.length === 0 || holdSubmitting || loading}
                onClick={handleCreateHold}
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-5 sm:px-6 py-2.5 rounded-xl text-xs font-black text-white bg-gradient-to-r from-[#F84464] to-[#E03A58] hover:from-[#E03A58] hover:to-[#D02846] disabled:from-slate-200 disabled:to-slate-200 disabled:text-slate-400 disabled:cursor-not-allowed shadow-md shadow-rose-600/20 transition-all uppercase tracking-wider cursor-pointer whitespace-nowrap min-h-[42px]"
              >
                <Lock className="w-3.5 h-3.5 shrink-0" />
                <span>
                  {holdSubmitting
                    ? 'Locking Seats...'
                    : `Hold ${selectedSeatIds.length > 0 ? `(${selectedSeatIds.length})` : ''} Selected Seat${
                        selectedSeatIds.length !== 1 ? 's' : ''
                      }`}
                </span>
              </button>
            </div>
          </div>
        )}

        {/* 120-Seat Venue Map Section */}
        <section id="venue-seat-map-section" className="flex-1 flex flex-col items-center">
          {loading && seats.length === 0 ? (
            <div id="loading-seats-indicator" className="py-20 text-center text-slate-500">
              <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-3 text-[#F84464]" />
              <p className="text-sm font-semibold">Connecting to live auditorium seat inventory...</p>
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

      {/* Professional BookMyShow Style Footer */}
      <footer id="app-footer" className="bg-[#1F2533] text-slate-400 border-t border-slate-800 mt-12">
        {/* Top Guarantee Strip */}
        <div className="border-b border-slate-800/80 py-6">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 grid grid-cols-1 md:grid-cols-3 gap-6 text-center md:text-left">
            <div className="flex items-center justify-center md:justify-start gap-3">
              <div className="w-10 h-10 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center text-[#F84464]">
                <ShieldCheck className="w-5 h-5" />
              </div>
              <div>
                <p className="text-white font-bold text-xs uppercase tracking-wider">
                  100% Guaranteed Booking
                </p>
                <p className="text-[11px] text-slate-400">Pessimistic row-locks prevent double-booking</p>
              </div>
            </div>

            <div className="flex items-center justify-center md:justify-start gap-3">
              <div className="w-10 h-10 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center text-amber-400">
                <Clock className="w-5 h-5" />
              </div>
              <div>
                <p className="text-white font-bold text-xs uppercase tracking-wider">
                  5-Minute Temporary Hold
                </p>
                <p className="text-[11px] text-slate-400">Automatic TTL cleanup guarantees seat turnover</p>
              </div>
            </div>

            <div className="flex items-center justify-center md:justify-start gap-3">
              <div className="w-10 h-10 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center text-emerald-400">
                <Ticket className="w-5 h-5" />
              </div>
              <div>
                <p className="text-white font-bold text-xs uppercase tracking-wider">
                  Instant Unique Reference
                </p>
                <p className="text-[11px] text-slate-400">Verifiable booking codes generated on confirmation</p>
              </div>
            </div>
          </div>
        </div>

        {/* Bottom Copyright & Assessment Details */}
        <div className="py-6 text-center text-xs text-slate-500">
          <p className="font-medium text-slate-400">
            BookMySeat • Cinema & Event Ticketing Platform
          </p>
          <p className="mt-1 text-[11px] text-slate-500">
            Hardened with FastAPI, MySQL 8.0 ACID Transactions, Row-Level Locking (<code className="font-mono text-slate-400">SELECT ... FOR UPDATE</code>), and Multi-Threaded Barrier Safety.
          </p>
          <div className="mt-2.5 flex items-center justify-center gap-3 text-[11px] text-slate-500">
            <span>© 2026 Entertainment Ticketing Systems Ltd. All Rights Reserved.</span>
            <span>•</span>
            <button
              id="footer-reset-seats-btn"
              type="button"
              onClick={handleResetAllSeats}
              disabled={isResetting}
              title="Reset all 120 seats to Available for evaluation/testing"
              className="inline-flex items-center gap-1 text-slate-500 hover:text-rose-400 transition-colors cursor-pointer underline text-[11px] disabled:opacity-50"
            >
              <RotateCcw className={`w-3 h-3 ${isResetting ? 'animate-spin text-[#F84464]' : ''}`} />
              <span>{isResetting ? 'Resetting All Seats...' : 'Reset All Seats (Demo Tool)'}</span>
            </button>
          </div>
        </div>
      </footer>
    </div>
  );
}
