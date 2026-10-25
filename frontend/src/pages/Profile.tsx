import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { deleteAccount, getBankOptions, requestCode, type BankOption } from "../api/auth";
import { resolveBankAccount, updateBankDetails } from "../api/rides";
import { ApiError } from "../api/http";
import { useAutoDismiss } from "../hooks/useAutoDismiss";

type BankStep = "idle" | "entering" | "previewing" | "code" | "done";

export default function Profile() {
  const { user, accessToken, logout } = useAuth();
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useAutoDismiss(error, () => setError(null));

  // Driver bank-details change — see api/rides.ts's resolveBankAccount /
  // updateBankDetails. Three real safety steps the backend enforces, not
  // just this screen: Paystack must recognise the account before anything
  // can save, the driver has to see and accept whose name Paystack
  // resolved it to, and the save itself needs a fresh one-time code, not
  // just an existing session — none of that can be skipped from here.
  const [bankStep, setBankStep] = useState<BankStep>("idle");
  const [bankOptions, setBankOptions] = useState<BankOption[]>([]);
  const [bankCode, setBankCode] = useState("");
  const [accountNumber, setAccountNumber] = useState("");
  const [resolvedName, setResolvedName] = useState("");
  const [code, setCode] = useState("");
  const [bankLoading, setBankLoading] = useState(false);
  const [bankError, setBankError] = useState<string | null>(null);

  useAutoDismiss(bankError, () => setBankError(null));

  useEffect(() => {
    if (bankStep === "entering" && bankOptions.length === 0) {
      getBankOptions().then(setBankOptions);
    }
  }, [bankStep, bankOptions.length]);

  async function handlePreview() {
    if (!accessToken || !bankCode || accountNumber.length < 10) {
      setBankError("Select a bank and enter a valid account number.");
      return;
    }
    setBankLoading(true);
    setBankError(null);
    try {
      const result = await resolveBankAccount(bankCode, accountNumber, accessToken);
      setResolvedName(result.account_name);
      setBankStep("previewing");
    } catch (err) {
      setBankError(err instanceof ApiError ? err.message : "Could not verify that account.");
    } finally {
      setBankLoading(false);
    }
  }

  async function handleConfirmIdentity() {
    if (!user?.email) return;
    setBankLoading(true);
    setBankError(null);
    try {
      await requestCode(user.email);
      setBankStep("code");
    } catch (err) {
      setBankError(err instanceof ApiError ? err.message : "Could not send a verification code.");
    } finally {
      setBankLoading(false);
    }
  }

  async function handleSaveBankDetails() {
    if (!accessToken || code.length < 4) {
      setBankError("Enter the code we just sent you.");
      return;
    }
    setBankLoading(true);
    setBankError(null);
    try {
      await updateBankDetails(bankCode, accountNumber, code, accessToken);
      setBankStep("done");
    } catch (err) {
      setBankError(err instanceof ApiError ? err.message : "Could not save your bank details.");
    } finally {
      setBankLoading(false);
    }
  }

  function resetBankFlow() {
    setBankStep("idle");
    setBankCode("");
    setAccountNumber("");
    setResolvedName("");
    setCode("");
    setBankError(null);
  }

  async function handleDelete() {
    if (!accessToken) return;
    setDeleting(true);
    setError(null);
    try {
      await deleteAccount(accessToken);
      await logout();
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete your account.");
      setDeleting(false);
    }
  }

  return (
    <div className="fixed inset-0 flex flex-col bg-[#20241f] text-slate-100">
      <div className="flex items-center gap-3 px-4 pt-6 pb-4">
        <button
          onClick={() => navigate(-1)}
          className="w-9 h-9 rounded-full bg-white/10 flex items-center justify-center"
          aria-label="Back"
        >
          <i className="fa-solid fa-arrow-left" />
        </button>
        <h1 className="text-white text-xl font-extrabold">Profile</h1>
      </div>

      <div className="flex-1 overflow-y-auto px-4 pb-8 flex flex-col gap-6">
        <div className="rounded-2xl bg-white/5 border border-white/10 p-4 flex flex-col gap-3">
          <div>
            <p className="text-slate-400 text-xs">Full name</p>
            <p className="text-white font-semibold">{user?.full_name || "N/A"}</p>
          </div>
          <div>
            <p className="text-slate-400 text-xs">Phone number</p>
            <p className="text-white font-semibold">{user?.phone_number || "N/A"}</p>
          </div>
          <div>
            <p className="text-slate-400 text-xs">Email</p>
            <p className="text-white font-semibold">{user?.email || "N/A"}</p>
          </div>
          {user?.address && (
            <div>
              <p className="text-slate-400 text-xs">Address</p>
              <p className="text-white font-semibold">{user.address}</p>
            </div>
          )}
        </div>

        {user?.role === "driver" && (
          <div className="rounded-2xl bg-white/5 border border-white/10 p-4 flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <p className="text-white font-semibold">Payout bank details</p>
              {bankStep === "idle" && (
                <button
                  onClick={() => setBankStep("entering")}
                  className="text-[#1be451] text-sm font-semibold"
                >
                  Change
                </button>
              )}
            </div>

            {bankStep === "idle" && (
              <p className="text-slate-400 text-sm">
                Changing your bank requires a verification code and admin review for your safety.
              </p>
            )}

            {bankStep === "entering" && (
              <div className="flex flex-col gap-3">
                <select
                  value={bankCode}
                  onChange={(e) => setBankCode(e.target.value)}
                  className="w-full py-3 px-3 rounded-xl bg-white/10 text-white border border-white/20"
                >
                  <option value="" className="text-black">
                    {bankOptions.length === 0 ? "Loading banks…" : "Select your bank"}
                  </option>
                  {bankOptions.map((b, i) => (
                    <option key={`${b.code}-${i}`} value={b.code} className="text-black">
                      {b.name}
                    </option>
                  ))}
                </select>
                <input
                  value={accountNumber}
                  onChange={(e) => setAccountNumber(e.target.value.replace(/\D/g, ""))}
                  inputMode="numeric"
                  placeholder="Account number"
                  className="w-full py-3 px-3 rounded-xl bg-white/10 text-white border border-white/20 placeholder:text-slate-400"
                />
                {bankError && <p className="text-red-400 text-sm">{bankError}</p>}
                <div className="flex gap-2">
                  <button
                    onClick={resetBankFlow}
                    disabled={bankLoading}
                    className="flex-1 py-3 rounded-full bg-white/10 border border-white/20 text-white font-semibold disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handlePreview}
                    disabled={bankLoading}
                    className="flex-1 py-3 rounded-full bg-[#1be451] text-neutral-900 font-bold disabled:opacity-50"
                  >
                    {bankLoading ? "Checking…" : "Next"}
                  </button>
                </div>
              </div>
            )}

            {bankStep === "previewing" && (
              <div className="flex flex-col gap-3">
                <p className="text-slate-300 text-sm">Paystack says this account belongs to:</p>
                <p className="text-white font-bold text-lg">{resolvedName}</p>
                <p className="text-slate-400 text-sm">Is this you? We'll send a code to confirm.</p>
                {bankError && <p className="text-red-400 text-sm">{bankError}</p>}
                <div className="flex gap-2">
                  <button
                    onClick={resetBankFlow}
                    disabled={bankLoading}
                    className="flex-1 py-3 rounded-full bg-white/10 border border-white/20 text-white font-semibold disabled:opacity-50"
                  >
                    Not me
                  </button>
                  <button
                    onClick={handleConfirmIdentity}
                    disabled={bankLoading}
                    className="flex-1 py-3 rounded-full bg-[#1be451] text-neutral-900 font-bold disabled:opacity-50"
                  >
                    {bankLoading ? "Sending…" : "Yes, send code"}
                  </button>
                </div>
              </div>
            )}

            {bankStep === "code" && (
              <div className="flex flex-col gap-3">
                <p className="text-slate-300 text-sm">Enter the code sent to your email to confirm.</p>
                <input
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                  inputMode="numeric"
                  placeholder="Verification code"
                  className="w-full py-3 px-3 rounded-xl bg-white/10 text-white border border-white/20 placeholder:text-slate-400"
                />
                {bankError && <p className="text-red-400 text-sm">{bankError}</p>}
                <div className="flex gap-2">
                  <button
                    onClick={resetBankFlow}
                    disabled={bankLoading}
                    className="flex-1 py-3 rounded-full bg-white/10 border border-white/20 text-white font-semibold disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleSaveBankDetails}
                    disabled={bankLoading}
                    className="flex-1 py-3 rounded-full bg-[#1be451] text-neutral-900 font-bold disabled:opacity-50"
                  >
                    {bankLoading ? "Saving…" : "Confirm and save"}
                  </button>
                </div>
              </div>
            )}

            {bankStep === "done" && (
              <div className="flex flex-col gap-3">
                <p className="text-[#1be451] text-sm font-semibold">Bank details updated.</p>
                <button
                  onClick={resetBankFlow}
                  className="w-full py-3 rounded-full bg-white/10 border border-white/20 text-white font-semibold"
                >
                  Done
                </button>
              </div>
            )}
          </div>
        )}

        <div className="mt-auto flex flex-col gap-3">
          {!confirming ? (
            <button
              onClick={() => setConfirming(true)}
              className="w-full py-3 rounded-full bg-white/10 border border-white/20 text-red-400 font-semibold"
            >
              Delete account
            </button>
          ) : (
            <div className="rounded-2xl bg-red-500/10 border border-red-500/40 p-4 flex flex-col gap-3">
              <p className="text-red-400 text-sm">
                This deletes your GoCab account and logs you out immediately. This can't be undone from the app.
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setConfirming(false)}
                  disabled={deleting}
                  className="flex-1 py-3 rounded-full bg-white/10 border border-white/20 text-white font-semibold disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleDelete}
                  disabled={deleting}
                  className="flex-1 py-3 rounded-full bg-red-500 text-white font-bold disabled:opacity-50"
                >
                  {deleting ? "Deleting…" : "Yes, delete"}
                </button>
              </div>
              {error && <p className="text-red-400 text-sm">{error}</p>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
