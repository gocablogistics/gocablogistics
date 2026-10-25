import { useState } from "react";
import { useBackHandler } from "../hooks/useBackHandler";
import { useMountTransition } from "../hooks/useMountTransition";

const TRANSITION_MS = 220;

interface ReceiptModalProps {
  rideId: number;
  pickup: string;
  destination: string;
  otherPartyName: string | null;
  amount: number | null;
  paymentMethod: string;
  paidAt: string | null;
  reference: string | null;
  onClose: () => void;
}

// Shown to the passenger right after payment (ActiveRideScreen.tsx) and
// from past rides (RideHistory.tsx) — the whole point is that it's
// something they can hand their phone over and show the driver as proof
// payment actually went through, so it's deliberately plain, large-text,
// and has nothing on it the passenger needs to explain.
export default function ReceiptModal({
  rideId,
  pickup,
  destination,
  otherPartyName,
  amount,
  paymentMethod,
  paidAt,
  reference,
  onClose,
}: ReceiptModalProps) {
  // No `open` prop here — this component is conditionally *mounted* by its
  // parent, which has no built-in delay before actually unmounting it, so
  // the exit animation is intercepted locally: play it first, then call the
  // real onClose once it's finished.
  const [closing, setClosing] = useState(false);
  const { isOpen } = useMountTransition(!closing, TRANSITION_MS);

  function handleClose() {
    setClosing(true);
    setTimeout(onClose, TRANSITION_MS);
  }

  useBackHandler(true, handleClose);

  return (
    <div
      className={`fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/70 px-4 pb-4 sm:pb-0 transition-opacity ease-out ${
        isOpen ? "opacity-100" : "opacity-0"
      }`}
      style={{ transitionDuration: `${TRANSITION_MS}ms` }}
      onClick={handleClose}
    >
      <div
        className={`w-full max-w-sm rounded-3xl bg-[#20241f] border border-white/10 p-6 flex flex-col gap-4 transition-transform ease-out ${
          isOpen ? "translate-y-0" : "translate-y-full sm:translate-y-8"
        }`}
        style={{ transitionDuration: `${TRANSITION_MS}ms` }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex flex-col items-center gap-2 pt-2">
          <div className="w-14 h-14 rounded-full bg-[#1be451]/15 flex items-center justify-center">
            <i className="fa-solid fa-check text-[#1be451] text-2xl" />
          </div>
          <p className="text-white text-lg font-extrabold">Payment Receipt</p>
          <p className="text-slate-400 text-xs">GoCab Logistics · Ride #{rideId}</p>
        </div>

        <div className="rounded-2xl bg-white/5 border border-white/10 p-4 flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <span className="text-slate-400 text-xs">Amount paid</span>
            <span className="text-white text-xl font-extrabold">
              {amount != null ? `₦${amount.toLocaleString()}` : "—"}
            </span>
          </div>
          <div className="h-px bg-white/10" />
          <div className="flex flex-col gap-2 text-sm">
            <Row label="Route" value={`${pickup} → ${destination}`} />
            {otherPartyName && <Row label="Driver" value={otherPartyName} />}
            <Row label="Payment method" value={paymentMethod === "cash" ? "Cash" : "Online"} />
            <Row
              label="Paid at"
              value={paidAt ? new Date(paidAt).toLocaleString(undefined, {
                day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit",
              }) : "—"}
            />
            {reference && <Row label="Reference" value={reference} mono />}
          </div>
        </div>

        <button
          onClick={handleClose}
          className="w-full py-3 rounded-full bg-[#1be451] text-neutral-900 font-bold"
        >
          Done
        </button>
      </div>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-slate-400 shrink-0">{label}</span>
      <span className={`text-white text-right ${mono ? "font-mono text-xs break-all" : ""}`}>{value}</span>
    </div>
  );
}
