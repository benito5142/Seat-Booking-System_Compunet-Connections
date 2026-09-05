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
      className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
        isUrgent
          ? 'bg-red-50 text-red-700 border border-red-200 animate-pulse'
          : 'bg-amber-50 text-amber-800 border border-amber-200'
      }`}
    >
      <Clock className="w-4 h-4" />
      <span>Hold Expires In:</span>
      <span id="countdown-timer-display" className="font-mono font-bold text-base">
        {formattedTime}
      </span>
    </div>
  );
};
