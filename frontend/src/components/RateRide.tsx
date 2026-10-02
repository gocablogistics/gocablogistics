import { useState } from "react";
import { rateRide } from "../api/rides";
import { ApiError } from "../api/http";
import { useAutoDismiss } from "../hooks/useAutoDismiss";

interface RateRideProps {
  rideId: number;
  accessToken: string;
  raterLabel: string;
  /** Called once the rating actually lands — lets a list screen (ride
   * history) update its own "already rated" state without a full refetch. */
  onSubmitted?: () => void;
}

export default function RateRide({ rideId, accessToken, raterLabel, onSubmitted }: RateRideProps) {
  const [stars, setStars] = useState(0);
  const [hoverStars, setHoverStars] = useState(0);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  useAutoDismiss(error, () => setError(null));

  async function handleSubmit() {
    if (stars < 1) return;
    setSubmitting(true);
    setError(null);
    try {
      await rateRide(rideId, stars, accessToken, comment);
      setSubmitted(true);
      onSubmitted?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't submit your rating");
    } finally {
      setSubmitting(false);
    }
  }

  if (submitted) {
    return (
      <div className="rounded-2xl bg-[#1be451]/10 border border-[#1be451]/30 px-4 py-3 flex items-center gap-3">
        <div className="w-9 h-9 shrink-0 rounded-full bg-[#1be451]/15 flex items-center justify-center text-[#1be451]">
          <i className="fa-solid fa-check" />
        </div>
        <p className="text-[#1be451] text-sm font-semibold">Thanks for rating your {raterLabel}!</p>
      </div>
    );
  }

  const displayStars = hoverStars || stars;

  return (
    <div className="rounded-2xl bg-white/5 border border-white/10 p-4 flex flex-col gap-3">
      <p className="text-white text-sm font-semibold">Rate your {raterLabel}</p>
      <div className="flex gap-1 text-3xl leading-none">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            type="button"
            key={n}
            onClick={() => setStars(n)}
            onMouseEnter={() => setHoverStars(n)}
            onMouseLeave={() => setHoverStars(0)}
            className={n <= displayStars ? "text-amber-400" : "text-white/15"}
            aria-label={`${n} star${n > 1 ? "s" : ""}`}
          >
            ★
          </button>
        ))}
      </div>
      <textarea
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder="Optional comment"
        rows={2}
        className="w-full rounded-xl px-3 py-2 bg-white/5 border border-white/10 text-white text-sm placeholder:text-slate-500 resize-none"
      />
      <button
        type="button"
        onClick={handleSubmit}
        disabled={submitting || stars < 1}
        className="w-full py-2.5 rounded-full bg-[#1be451] text-neutral-900 font-bold text-sm disabled:opacity-50"
      >
        {submitting ? "Submitting…" : "Submit rating"}
      </button>
      {error && <p className="text-red-400 text-xs">{error}</p>}
    </div>
  );
}
