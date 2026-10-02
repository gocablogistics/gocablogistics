import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { deleteAccount } from "../api/auth";
import { ApiError } from "../api/http";
import { useAutoDismiss } from "../hooks/useAutoDismiss";

export default function Profile() {
  const { user, accessToken, logout } = useAuth();
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useAutoDismiss(error, () => setError(null));

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
