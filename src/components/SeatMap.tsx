import React from 'react';
import { Seat } from '../types';
import { EVENT_SPEC } from '../config';

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
    <div id="seat-map-container" className="flex flex-col items-center w-full max-w-4xl mx-auto my-4">
      {/* Screen / Stage Visualization */}
      <div id="stage-banner" className="w-full max-w-2xl mb-8 flex flex-col items-center">
        <div className="w-full h-3 bg-gradient-to-r from-slate-200 via-slate-400 to-slate-200 rounded-full mb-2 shadow-inner" />
        <span className="text-xs uppercase tracking-widest text-slate-500 font-semibold">STAGE / SCREEN</span>
      </div>

      {/* Seat Map Legend */}
      <div
        id="seat-map-legend"
        className="flex flex-wrap items-center justify-center gap-6 mb-6 px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-700"
      >
        <div className="flex items-center gap-2">
          <span className="w-5 h-5 rounded border border-emerald-400 bg-emerald-100 flex items-center justify-center font-bold text-[10px] text-emerald-800">
            A
          </span>
          <span>Available</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-5 h-5 rounded border border-blue-700 bg-blue-600 text-white flex items-center justify-center font-bold text-[10px]">
            S
          </span>
          <span>Selected</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-5 h-5 rounded border border-amber-400 bg-amber-100 text-amber-800 flex items-center justify-center font-bold text-[10px]">
            H
          </span>
          <span>Held (5m TTL)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-5 h-5 rounded border border-slate-300 bg-slate-200 text-slate-500 flex items-center justify-center font-bold text-[10px]">
            B
          </span>
          <span>Booked</span>
        </div>
      </div>

      {/* Grid: 10 Rows (A-J) x 12 Seats (1-12) */}
      <div
        id="seats-grid"
        className="flex flex-col gap-2 p-4 bg-white border border-slate-200 rounded-xl shadow-xs overflow-x-auto w-full max-w-3xl"
      >
        {/* Column Number Headers */}
        <div className="flex items-center justify-center gap-1.5 mb-1 text-[11px] font-medium text-slate-400">
          <span className="w-6 text-center font-semibold" />
          <div className="flex items-center gap-1.5">
            {Array.from({ length: 6 }, (_, i) => i + 1).map((col) => (
              <span key={col} className="w-8 text-center">
                {col}
              </span>
            ))}
          </div>
          {/* Aisle Spacer */}
          <span className="w-4" />
          <div className="flex items-center gap-1.5">
            {Array.from({ length: 6 }, (_, i) => i + 7).map((col) => (
              <span key={col} className="w-8 text-center">
                {col}
              </span>
            ))}
          </div>
          <span className="w-6 text-center font-semibold" />
        </div>

        {/* 10 Rows */}
        {EVENT_SPEC.rows.map((rowLabel) => {
          return (
            <div key={rowLabel} className="flex items-center justify-center gap-1.5">
              {/* Left Row Indicator */}
              <span className="w-6 text-center font-bold text-slate-700 text-sm">
                {rowLabel}
              </span>

              {/* Seats 1-6 */}
              <div className="flex items-center gap-1.5">
                {Array.from({ length: 6 }, (_, idx) => idx + 1).map((seatNum) => {
                  const seatId = `${rowLabel}${seatNum}`;
                  return renderSeatButton(seatId);
                })}
              </div>

              {/* Central Aisle Gap */}
              <div className="w-4 flex items-center justify-center">
                <span className="h-4 w-px bg-slate-200" />
              </div>

              {/* Seats 7-12 */}
              <div className="flex items-center gap-1.5">
                {Array.from({ length: 6 }, (_, idx) => idx + 7).map((seatNum) => {
                  const seatId = `${rowLabel}${seatNum}`;
                  return renderSeatButton(seatId);
                })}
              </div>

              {/* Right Row Indicator */}
              <span className="w-6 text-center font-bold text-slate-700 text-sm">
                {rowLabel}
              </span>
            </div>
          );
        })}
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
      buttonClass = 'bg-blue-600 border-blue-700 text-white font-semibold shadow-xs ring-2 ring-blue-300';
      statusLabel = 'Selected';
    } else if (isHeld) {
      buttonClass = 'bg-amber-100 border-amber-300 text-amber-800 opacity-90 cursor-not-allowed';
      statusLabel = 'Held';
    } else if (isBooked) {
      buttonClass = 'bg-slate-200 border-slate-300 text-slate-400 opacity-70 cursor-not-allowed';
      statusLabel = 'Booked';
    } else {
      buttonClass =
        'bg-emerald-50 border-emerald-300 text-emerald-900 hover:bg-emerald-100 hover:border-emerald-400 cursor-pointer';
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
        className={`w-8 h-8 rounded text-xs font-mono font-medium border flex items-center justify-center transition-all ${buttonClass}`}
      >
        {seatId}
      </button>
    );
  }
};
