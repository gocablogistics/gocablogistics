import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { isTauri } from "@tauri-apps/api/core";
import { useAuth } from "../auth/AuthContext";
import { getReferrals, type ReferralSummaryOut } from "../api/rides";

// window.location.origin is meaningless inside the Android app (it's the
// WebView's own internal origin, not a real address a friend could open) —
// only worth appending to the share text on the web build.
function shareLink(code: string): string | null {
  if (isTauri()) return null;
  return `${window.location.origin}/signup?ref=${code}`;
}

function buildShareText(summary: ReferralSummaryOut): string {
  const link = shareLink(summary.referral_code);
  const amount = `₦${summary.referral_reward_amount.toLocaleString()}`;
  return link
    ? `Use my GoCab referral code ${summary.referral_code} when you sign up, or just tap this link: ${link}. I'll get ${amount} in ride credit once you complete your first paid ride.`
    : `Use my GoCab referral code ${summary.referral_code} when you sign up. I'll get ${amount} in ride credit once you complete your first paid ride.`;
}

export default function Referrals() {
  const { accessToken } = useAuth();
  const navigate = useNavigate();
  const [summary, setSummary] = useState<ReferralSummaryOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!accessToken) return;
    getReferrals(accessToken)
      .then(setSummary)
      .catch(() => setError("Could not load your referral info."));
  }, [accessToken]);

  async function handleShare() {
    if (!summary) return;
    const text = buildShareText(summary);
    try {
      if (navigator.share) {
        await navigator.share({ text });
        return;
      }
    } catch {
      // User cancelled the share sheet, or the platform doesn't actually
      // support it despite the API being present — fall through to copy.
    }
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard blocked (e.g. no permission) — nothing more we can do
      // silently; the code is still shown on screen to copy by hand.
    }
  }

  return (
    <div className="fixed inset-0 flex flex-col bg-[#20241f] text-slate-100">
      <div className="flex items-center gap-3 px-4 pt-6 pb-4">
        <button
          onClick={() => navigate("/rider")}
          className="w-9 h-9 rounded-full bg-white/10 flex items-center justify-center"
          aria-label="Back"
        >
          <i className="fa-solid fa-arrow-left" />
        </button>
        <h1 className="text-white text-xl font-extrabold">Refer a friend</h1>
      </div>

      <div className="flex-1 overflow-y-auto px-4 pb-8 flex flex-col gap-4">
        {error && <p className="text-red-400 text-sm text-center mt-4">{error}</p>}

        {summary && (
          <>
            <div className="rounded-2xl bg-white/5 border border-white/10 p-5 flex flex-col gap-3">
              <p className="text-slate-300/80 text-sm">
                Share your code. When someone you invite completes their first paid
                ride, you get ₦{summary.referral_reward_amount.toLocaleString()} in ride
                credit, automatically applied to your next trip.
              </p>

              <div className="rounded-xl bg-white/10 border border-white/20 px-4 py-3 flex items-center justify-between">
                <span className="text-white text-2xl font-extrabold tracking-widest">
                  {summary.referral_code}
                </span>
              </div>

              <button
                onClick={handleShare}
                className="w-full py-3 rounded-full bg-[#1be451] text-neutral-900 font-bold"
              >
                {copied ? "Copied!" : "Share code"}
              </button>
            </div>

            <div className="rounded-2xl bg-white/5 border border-white/10 p-4 flex items-center justify-between">
              <p className="text-slate-400 text-xs">Wallet credit</p>
              <p className="text-[#1be451] text-lg font-bold">
                ₦{summary.wallet_credit_balance.toLocaleString()}
              </p>
            </div>

            <div>
              <h2 className="text-white font-semibold mb-2">
                Your referrals ({summary.referrals.length})
              </h2>
              {summary.referrals.length === 0 ? (
                <p className="text-slate-400 text-sm">
                  Nobody has signed up with your code yet.
                </p>
              ) : (
                <div className="flex flex-col gap-2">
                  {summary.referrals.map((r, i) => (
                    <div
                      key={i}
                      className="rounded-2xl bg-white/5 border border-white/10 p-3 flex items-center justify-between"
                    >
                      <div>
                        <p className="text-white text-sm font-semibold">{r.full_name}</p>
                        <p className="text-slate-400 text-xs">
                          Joined{" "}
                          {new Date(r.joined_at).toLocaleDateString(undefined, {
                            day: "numeric", month: "short", year: "numeric",
                          })}
                        </p>
                      </div>
                      <p className={`text-xs font-semibold ${r.reward_earned ? "text-[#1be451]" : "text-slate-400"}`}>
                        {r.reward_earned ? "Reward earned" : "Awaiting first paid ride"}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
