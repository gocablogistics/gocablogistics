import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { confirmPayment } from "../api/rides";
import { ApiError } from "../api/http";
import { useAuth } from "../auth/AuthContext";
import Loader from "../components/Loader";
import RateRide from "../components/RateRide";

export default function PaymentCallback() {
  const { accessToken, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const rideId = Number(searchParams.get("ride_id"));
  const reference = searchParams.get("reference") ?? undefined;
  const confirmToken = searchParams.get("confirm_token") ?? undefined;

  const [status, setStatus] = useState<"checking" | "paid" | "pending" | "error">("checking");
  const [walletCreditApplied, setWalletCreditApplied] = useState<number | null>(null);
  // Paystack sends the rider back here after paying in the phone's browser
  // (the Android app opens checkout there) — a browser that has no GoCab
  // login. The payment is confirmed server-side either way; the app picks
  // it up when the rider switches back to it.
  const loggedOutReturn = !authLoading && !accessToken;
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (authLoading || !accessToken || !rideId) return;

    confirmPayment(rideId, accessToken, reference, confirmToken)
      .then((result) => {
        setStatus(result.payment_status === "paid" ? "paid" : "pending");
        setWalletCreditApplied(result.wallet_credit_applied);
      })
      .catch((err) => {
        setStatus("error");
        setError(err instanceof ApiError ? err.message : "Could not confirm payment.");
      });
  }, [authLoading, accessToken, rideId, reference]);

  if (loggedOutReturn) {
    return (
      <div className="fixed inset-0 flex flex-col items-center justify-center gap-5 bg-[#20241f] text-slate-100 px-8 text-center">
        <div className="w-16 h-16 rounded-full bg-[#1be451] flex items-center justify-center text-3xl text-neutral-900">
          <i className="fa-solid fa-check" />
        </div>
        <h1 className="text-white text-xl font-extrabold">You're all set</h1>
        <p className="text-slate-400">
          If your payment went through, it's confirmed. Switch back to the GoCab app, your trip
          updates there automatically.
        </p>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 flex flex-col items-center justify-center gap-5 bg-[#20241f] text-slate-100 px-8 text-center">
      {status === "checking" && (
        <Loader fullScreen={false} message="Confirming your payment" />
      )}

      {status === "paid" && (
        <>
          <div className="w-16 h-16 rounded-full bg-[#1be451] flex items-center justify-center text-3xl text-neutral-900">
            <i className="fa-solid fa-check" />
          </div>
          <h1 className="text-white text-xl font-extrabold">Payment received</h1>
          <p className="text-slate-400">Thank you, your trip is fully settled.</p>
          {!!walletCreditApplied && (
            <p className="text-[#1be451] text-sm font-semibold">
              ₦{walletCreditApplied.toLocaleString()} wallet credit applied
            </p>
          )}
          {accessToken && (
            <div className="w-full max-w-xs">
              <RateRide rideId={rideId} accessToken={accessToken} raterLabel="driver" />
            </div>
          )}
        </>
      )}

      {status === "pending" && (
        <>
          <div className="w-16 h-16 rounded-full bg-amber-500/20 flex items-center justify-center text-3xl text-amber-400">
            <i className="fa-solid fa-clock" />
          </div>
          <h1 className="text-white text-xl font-extrabold">Still confirming</h1>
          <p className="text-slate-400">
            We couldn't confirm payment yet. If you completed checkout, this can take a moment.
            check back from your dashboard.
          </p>
        </>
      )}

      {status === "error" && (
        <>
          <div className="w-16 h-16 rounded-full bg-red-500/20 flex items-center justify-center text-3xl text-red-400">
            <i className="fa-solid fa-triangle-exclamation" />
          </div>
          <h1 className="text-white text-xl font-extrabold">Something went wrong</h1>
          <p className="text-red-400">{error}</p>
        </>
      )}

      <button
        onClick={() => navigate("/rider")}
        className="mt-2 w-full max-w-xs py-4 rounded-full bg-[#1be451] text-neutral-900 font-bold text-lg"
      >
        Back to dashboard
      </button>
    </div>
  );
}
