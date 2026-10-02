import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { requestCode, verifyCode } from "../api/auth";
import { ApiError } from "../api/http";
import { useAuth } from "../auth/AuthContext";
import { resumePendingBookingIfAny } from "../booking/pendingBooking";
import { useAutoDismiss } from "../hooks/useAutoDismiss";

type Step = "email" | "code";

// A phone browser tab switched away to (e.g.) WhatsApp and back is often
// reclaimed and reloaded fresh by the OS, which would otherwise silently
// wipe this in-memory state and drop someone who'd already requested a
// code back to square one. sessionStorage survives that reload (and only
// that — it's gone once the tab/app actually closes, which is fine here
// since a login attempt shouldn't outlive the tab anyway).
const STORAGE_KEY = "gocab_login_state";

function loadSavedState(): { step: Step; email: string } | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && (parsed.step === "email" || parsed.step === "code") && typeof parsed.email === "string") {
      return parsed;
    }
    return null;
  } catch {
    return null;
  }
}

export default function Login() {
  const { setSession } = useAuth();
  const navigate = useNavigate();
  const saved = loadSavedState();

  const [step, setStep] = useState<Step>(saved?.step ?? "email");
  const [email, setEmail] = useState(saved?.email ?? "");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [resending, setResending] = useState(false);
  const [resent, setResent] = useState(false);

  useAutoDismiss(error, () => setError(null));

  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ step, email }));
    } catch {
      /* private browsing / storage blocked — worst case, back to normal behavior */
    }
  }, [step, email]);

  function clearSavedState() {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* best-effort */
    }
  }

  async function handleSendCode(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await requestCode(email.trim());
      setStep("code");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send code.");
    } finally {
      setLoading(false);
    }
  }

  async function handleResendCode() {
    setError(null);
    setResent(false);
    setResending(true);
    try {
      await requestCode(email.trim());
      setResent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not resend code.");
    } finally {
      setResending(false);
    }
  }

  async function handleVerify(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const tokens = await verifyCode(email.trim(), code.trim());
      setSession(tokens);
      clearSavedState();

      const dashboard = tokens.user.role === "driver" ? "/driver" : "/rider";
      const resume = await resumePendingBookingIfAny(tokens.access, tokens.user.role);
      navigate(dashboard, {
        state: resume.resumed
          ? { bookedRideId: resume.rideId }
          : resume.error
            ? { bookingError: resume.error }
            : undefined,
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        // The code just entered already proved this email — hand the
        // verified_token forward so signup doesn't make them do it twice.
        const verifiedToken = (err.body as { verified_token?: string } | null)?.verified_token;
        clearSavedState();
        navigate("/signup", { state: { email: email.trim(), verifiedToken } });
        return;
      }
      setError(err instanceof ApiError ? err.message : "Could not verify code.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative w-full max-w-[480px] mx-auto min-h-dvh bg-[#20241f] flex flex-col items-center justify-center text-slate-100 px-8 gap-4">
      {step === "code" && (
        <button
          onClick={() => {
            setError(null);
            setStep("email");
          }}
          className="self-start text-slate-400 text-sm"
        >
          ← Back
        </button>
      )}

      {step === "email" && (
        <form onSubmit={handleSendCode} className="w-full max-w-[320px] flex flex-col gap-4">
          <h1 className="text-white text-2xl font-extrabold">Join us via email</h1>
          <p className="text-slate-300/80 text-sm -mt-2">We'll send a code to your email.</p>
          <input
            autoFocus
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email address"
            className="w-full rounded-full px-4 py-3 bg-white/10 border border-white/20 text-white placeholder:text-slate-400"
          />
          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 rounded-full bg-[#1be451] text-neutral-900 font-bold disabled:opacity-50"
          >
            {loading ? "Sending…" : "Next"}
          </button>
        </form>
      )}

      {step === "code" && (
        <form onSubmit={handleVerify} className="w-full max-w-[320px] flex flex-col gap-4">
          <h1 className="text-white text-2xl font-extrabold">Enter your code</h1>
          <p className="text-slate-300/80 text-sm">
            We sent a 6-digit code to <span className="text-white font-semibold">{email}</span>.
          </p>
          <input
            autoFocus
            type="text"
            inputMode="numeric"
            maxLength={6}
            required
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            placeholder="6-digit code"
            className="w-full rounded-full px-4 py-3 bg-white/10 border border-white/20 text-white placeholder:text-slate-400"
          />
          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 rounded-full bg-[#1be451] text-neutral-900 font-bold disabled:opacity-50"
          >
            {loading ? "Verifying…" : "Verify"}
          </button>
          <p className="text-slate-400 text-xs text-center">
            Didn't get a code?{" "}
            <button
              type="button"
              onClick={handleResendCode}
              disabled={resending}
              className="text-[#1be451] font-semibold"
            >
              {resending ? "Resending…" : "Resend code"}
            </button>
            {resent && <span className="text-[#1be451] ml-2">Sent!</span>}
          </p>
        </form>
      )}

      {error && <p className="text-red-400 text-sm">{error}</p>}
    </div>
  );
}
