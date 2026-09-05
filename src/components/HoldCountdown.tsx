import React, { useEffect, useState } from 'react';
import { Clock } from 'lucide-react';

interface HoldCountdownProps {
  expiresAt: string; // ISO 8601 string from backend
  onExpired: () => void;
}

export const HoldCountdown: React.FC<HoldCountdownProps> = ({ expiresAt, onExpired }) => {
  const calculateRemainingSeconds = () => {
    const expireTime = new Date(expiresAt).getTime();
    const now = Date.now();
    return Math.max(0, Math.floor((expireTime - now) / 1000));
  };

  const [remainingSeconds, setRemainingSeconds] = useState<number>(calculateRemainingSeconds);

  useEffect(() => {
    // Immediate initial sync
    const initial = calculateRemainingSeconds();
    setRemainingSeconds(initial);
    if (initial <= 0) {
      onExpired();
      return;
    }

    // Interval to calculate remaining time dynamically from backend timestamp
    const interval = setInterval(() => {
      const remaining = calculateRemainingSeconds();
      setRemainingSeconds(remaining);
      if (remaining <= 0) {
        clearInterval(interval);
        onExpired();
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [expiresAt, onExpired]);

  const minutes = Math.floor(remainingSeconds / 60);
  const seconds = remainingSeconds % 60;
  const formattedTime = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  const isUrgent = remainingSeconds <= 60;

  return (
    <div
      id="active-hold-countdown"
      className={`inline-flex items-center gap-2.5 px-4 py-2 rounded-lg text-sm font-semibold shadow-xs transition-all ${
        isUrgent
          ? 'bg-rose-50 text-rose-700 border-2 border-rose-300 animate-pulse ring-2 ring-rose-200'
          : 'bg-amber-50 text-amber-900 border-2 border-amber-300 ring-2 ring-amber-100'
      }`}
    >
      <Clock className={`w-4 h-4 ${isUrgent ? 'text-rose-600 animate-spin' : 'text-amber-600'}`} />
      <span className="text-xs uppercase tracking-wider">Hold Expires In:</span>
      <span
        id="countdown-timer-display"
        className="font-mono font-extrabold text-base tracking-wider px-2 py-0.5 rounded bg-white/90 shadow-2xs border border-amber-200"
      >
        {formattedTime}
      </span>
    </div>
  );
};
