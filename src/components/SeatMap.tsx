import React from 'react';
import { Seat } from '../types';
import { EVENT_SPEC } from '../config';
import { Film, Lock } from 'lucide-react';

interface SeatMapProps {
  seats: Seat[];
  selectedSeatIds: string[];
  activeHoldSeatIds?: string[];
  onToggleSeat: (seatId: string) => void;
  disabled?: boolean;
}

export const SeatMap: React.FC<SeatMapProps> = ({
  seats,
  selectedSeatIds,
  activeHoldSeatIds = [],
  onToggleSeat,
  disabled = false,
}) => {
  // Fast lookup map for seat data by ID
  const seatMap = React.useMemo(() => {
    const map = new Map<string, Seat>();
    seats.forEach((seat) => map.set(seat.id, seat));
    return map;
  }, [seats]);

  return (
    <div id="seat-map-container" className="flex flex-col items-center w-full max-w-4xl mx-auto my-2 sm:my-3">
      {/* Curved Cinema Screen with Theatrical Light Glow */}
      <div id="stage-banner" className="w-full max-w-2xl mb-6 sm:mb-8 flex flex-col items-center relative px-2">
        <div className="w-full h-3.5 sm:h-4 bg-gradient-to-r from-rose-500/20 via-rose-500 to-rose-500/20 rounded-t-full shadow-[0_4px_20px_rgba(244,63,94,0.4)]" />
        <div className="w-3/4 h-6 sm:h-8 bg-gradient-to-b from-rose-500/15 to-transparent blur-md -mt-1 pointer-events-none" />
        <div className="flex items-center gap-2 mt-1">
          <Film className="w-3.5 h-3.5 text-rose-500 shrink-0" />
          <span className="text-[10px] sm:text-[11px] uppercase tracking-[0.2em] sm:tracking-[0.25em] text-slate-500 font-bold">
            All Eyes This Way Please • Screen
          </span>
        </div>
      </div>

      {/* Seat Map Legend */}
      <div
        id="seat-map-legend"
        className="flex flex-wrap items-center justify-center gap-3 sm:gap-6 mb-4 sm:mb-6 px-3.5 sm:px-6 py-2.5 sm:py-3 bg-white border border-slate-200 rounded-xl shadow-xs text-xs text-slate-700 w-full sm:w-auto"
      >
        <div className="flex items-center gap-2">
          <span className="w-5 h-5 rounded-t-md rounded-b-xs border-2 border-slate-300 bg-white flex items-center justify-center shadow-2xs" />
          <span className="font-medium text-slate-600 text-xs">Available</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-5 h-5 rounded-t-md rounded-b-xs border-2 border-emerald-600 bg-emerald-600 text-white flex items-center justify-center font-bold text-[10px] shadow-xs">
            ✓
          </span>
          <span className="font-semibold text-emerald-800 text-xs">Selected</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-5 h-5 rounded-t-md rounded-b-xs border-2 border-amber-400 bg-amber-100 text-amber-800 flex items-center justify-center font-bold text-[10px]">
            <Lock className="w-2.5 h-2.5" />
          </span>
          <span className="font-medium text-amber-800 text-xs">Held (5m TTL)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-5 h-5 rounded-t-md rounded-b-xs border border-slate-300 bg-slate-200 text-slate-400 flex items-center justify-center font-bold text-[10px]">
            ✕
          </span>
          <span className="font-medium text-slate-400 text-xs">Booked</span>
        </div>
      </div>

      {/* Mobile Swipe Guidance Banner */}
      <div className="sm:hidden flex items-center justify-between px-3 py-1.5 mb-2.5 bg-slate-100/90 border border-slate-200 text-slate-600 rounded-lg text-xs font-medium w-full max-w-3xl select-none">
        <span className="flex items-center gap-1 text-[11px] font-semibold text-slate-700">
          <span>Row & Seats 1–6</span>
        </span>
        <span className="text-[10px] text-rose-600 font-bold uppercase tracking-wider">
          ↔ Swipe for Seats 7–12
        </span>
        <span className="flex items-center gap-1 text-[11px] font-semibold text-slate-700">
          <span>Seats 7–12</span>
        </span>
      </div>

      {/* Grid: 10 Rows (A-J) x 12 Seats (1-12) */}
      <div
        id="seats-grid"
        className="w-full max-w-3xl overflow-x-auto p-3 sm:p-6 bg-white border border-slate-200/90 rounded-2xl shadow-xs touch-pan-x"
      >
        <div className="w-max min-w-full flex flex-col gap-2.5 sm:gap-3 items-start sm:items-center">
          {/* Column Number Headers */}
          <div className="flex items-center justify-start sm:justify-center gap-2 mb-1 text-[11px] font-semibold text-slate-400 w-full">
            <span className="w-7 text-center font-bold text-slate-400 text-[10px] uppercase">Row</span>
            <div className="flex items-center gap-1.5 sm:gap-2">
              {Array.from({ length: 6 }, (_, i) => i + 1).map((col) => (
                <span key={col} className="w-8 sm:w-9 text-center">
                  {col}
                </span>
              ))}
            </div>
            {/* Aisle Spacer */}
            <span className="w-6 text-center text-[10px] text-slate-300 font-mono">||</span>
            <div className="flex items-center gap-1.5 sm:gap-2">
              {Array.from({ length: 6 }, (_, i) => i + 7).map((col) => (
                <span key={col} className="w-8 sm:w-9 text-center">
                  {col}
                </span>
              ))}
            </div>
            <span className="w-7 text-center font-bold text-slate-400 text-[10px] uppercase">Row</span>
          </div>

          {/* 10 Rows with Tier Category Header Indicators */}
          {EVENT_SPEC.rows.map((rowLabel) => {
            let categoryHeader = null;
            if (rowLabel === 'A') {
              categoryHeader = (
                <div className="w-full flex items-center gap-3 pt-1 pb-1">
                  <span className="text-[11px] font-bold text-rose-700 uppercase tracking-wider bg-rose-50 px-2.5 py-0.5 rounded-full border border-rose-200">
                    VIP Recliner • ₹350
                  </span>
                  <div className="flex-1 h-px bg-rose-100" />
                </div>
              );
            } else if (rowLabel === 'D') {
              categoryHeader = (
                <div className="w-full flex items-center gap-3 pt-3 pb-1">
                  <span className="text-[11px] font-bold text-blue-700 uppercase tracking-wider bg-blue-50 px-2.5 py-0.5 rounded-full border border-blue-200">
                    Prime Executive • ₹250
                  </span>
                  <div className="flex-1 h-px bg-blue-100" />
                </div>
              );
            } else if (rowLabel === 'H') {
              categoryHeader = (
                <div className="w-full flex items-center gap-3 pt-3 pb-1">
                  <span className="text-[11px] font-bold text-slate-700 uppercase tracking-wider bg-slate-100 px-2.5 py-0.5 rounded-full border border-slate-200">
                    Classic Standard • ₹150
                  </span>
                  <div className="flex-1 h-px bg-slate-200" />
                </div>
              );
            }

            return (
              <React.Fragment key={rowLabel}>
                {categoryHeader}
                <div className="flex items-center justify-start sm:justify-center gap-2 w-full">
                  {/* Left Row Indicator */}
                  <span className="w-7 text-center font-bold text-slate-700 text-xs sm:text-sm bg-slate-100/90 py-1 rounded">
                    {rowLabel}
                  </span>

                  {/* Seats 1-6 */}
                  <div className="flex items-center gap-1.5 sm:gap-2">
                    {Array.from({ length: 6 }, (_, idx) => idx + 1).map((seatNum) => {
                      const seatId = `${rowLabel}${seatNum}`;
                      return renderSeatButton(seatId);
                    })}
                  </div>

                  {/* Central Aisle Gap */}
                  <div className="w-6 flex items-center justify-center">
                    <span className="h-6 w-px bg-slate-200" />
                  </div>

                  {/* Seats 7-12 */}
                  <div className="flex items-center gap-1.5 sm:gap-2">
                    {Array.from({ length: 6 }, (_, idx) => idx + 7).map((seatNum) => {
                      const seatId = `${rowLabel}${seatNum}`;
                      return renderSeatButton(seatId);
                    })}
                  </div>

                  {/* Right Row Indicator */}
                  <span className="w-7 text-center font-bold text-slate-700 text-xs sm:text-sm bg-slate-100/90 py-1 rounded">
                    {rowLabel}
                  </span>
                </div>
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </div>
  );

  function renderSeatButton(seatId: string) {
    const seat = seatMap.get(seatId);
    const isSelected = selectedSeatIds.includes(seatId);
    const isHeldByCurrentHold = activeHoldSeatIds.includes(seatId);

    // Default to available if not loaded yet
    const rawStatus = seat ? seat.status.toLowerCase() : 'available';
    const isHeld = rawStatus === 'held' || isHeldByCurrentHold;
    const isBooked = rawStatus === 'booked';
    const isAvailable = !isHeld && !isBooked;

    let buttonClass = '';
    let statusLabel = 'Available';

    if (isSelected) {
      buttonClass =
        'bg-emerald-600 border-emerald-700 text-white font-bold shadow-sm shadow-emerald-600/30 scale-105 ring-2 ring-emerald-300';
      statusLabel = 'Selected';
    } else if (isHeld) {
      buttonClass =
        'bg-amber-100 border-amber-300 text-amber-800 opacity-90 cursor-not-allowed';
      statusLabel = 'Held';
    } else if (isBooked) {
      buttonClass =
        'bg-slate-200 border-slate-300 text-slate-400 opacity-80 cursor-not-allowed';
      statusLabel = 'Booked';
    } else {
      buttonClass =
        'bg-white border-slate-300 text-slate-700 hover:border-emerald-500 hover:bg-emerald-50 hover:text-emerald-800 hover:scale-105 cursor-pointer shadow-2xs';
      statusLabel = 'Available';
    }

    const isButtonDisabled = disabled || isHeld || isBooked;

    return (
      <button
        key={seatId}
        id={`seat-btn-${seatId}`}
        type="button"
        disabled={isButtonDisabled}
        onClick={() => {
          if (!isHeld && !isBooked) {
            onToggleSeat(seatId);
          }
        }}
        aria-label={`Seat ${seatId} (${statusLabel})`}
        aria-pressed={isSelected}
        title={`Seat ${seatId} - ${statusLabel}`}
        className={`w-8 h-8 sm:w-9 sm:h-9 rounded-t-lg rounded-b-xs text-xs font-mono font-medium border flex items-center justify-center transition-all ${buttonClass}`}
      >
        {isSelected ? (
          '✓'
        ) : isHeld ? (
          <Lock className="w-3 h-3" />
        ) : isBooked ? (
          <div className="relative flex items-center justify-center w-full h-full select-none">
            <span className="text-[10px] sm:text-[11px] font-mono font-medium text-slate-400/90 select-none">
              {seatId}
            </span>
            <span className="absolute inset-0 flex items-center justify-center text-xs font-bold text-slate-400/60 pointer-events-none select-none">
              ✕
            </span>
          </div>
        ) : (
          seatId
        )}
      </button>
    );
  }
};
