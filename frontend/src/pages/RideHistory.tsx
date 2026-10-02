import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import Loader from "../components/Loader";
import { getDriverRideHistory, getRideHistory, type RideHistoryOut } from "../api/rides";
import RateRide from "../components/RateRide";

const STATUS_LABEL: Record<string, string> = {
  completed: "Completed",
  cancelled: "Cancelled",
};

const STATUS_COLOR: Record<string, string> = {
  completed: "text-[#1be451]",
  cancelled: "text-red-400",
};

export default function RideHistory() {
  const { accessToken, user } = useAuth();
  const navigate = useNavigate();
  const [rides, setRides] = useState<RideHistoryOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ratingRideId, setRatingRideId] = useState<number | null>(null);
  const isDriver = user?.role === "driver";

  useEffect(() => {
    if (!accessToken || !user) return;
    const fetcher = user.role === "driver" ? getDriverRideHistory : getRideHistory;
    fetcher(accessToken)
      .then(setRides)
      .catch(() => setError("Could not load your ride history."));
  }, [accessToken, user]);

  return (
    <div className="fixed inset-0 flex flex-col bg-[#20241f] text-slate-100">
      <div className="flex items-center gap-3 px-4 pt-6 pb-4">
        <button
          onClick={() => navigate(user?.role === "driver" ? "/driver" : "/rider")}
          className="w-9 h-9 rounded-full bg-white/10 flex items-center justify-center"
          aria-label="Back"
        >
          <i className="fa-solid fa-arrow-left" />
        </button>
        <h1 className="text-white text-xl font-extrabold">Ride history</h1>
      </div>

      <div className="flex-1 overflow-y-auto px-4 pb-8 flex flex-col gap-3">
        {error && <p className="text-red-400 text-sm text-center mt-4">{error}</p>}
        {!error && rides === null && <Loader fullScreen={false} compact message="Loading your rides" />}
        {rides !== null && rides.length === 0 && (
          <p className="text-slate-400 text-sm text-center mt-4">No past rides yet.</p>
        )}
        {rides?.map((r) => (
          <div key={r.ride_id} className="rounded-2xl bg-white/5 border border-white/10 p-4 flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <span className={`text-xs font-semibold ${STATUS_COLOR[r.status] || "text-amber-400"}`}>
                {STATUS_LABEL[r.status] || r.status}
              </span>
              <span className="text-slate-400 text-xs">
                {new Date(r.requested_at).toLocaleDateString(undefined, {
                  day: "numeric", month: "short", year: "numeric",
                })}
              </span>
            </div>
            <p className="text-sm text-slate-200">
              <strong className="text-white">{r.current_location}</strong>
              {" → "}
              <strong className="text-white">{r.destination}</strong>
            </p>
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>{r.other_party_name || "N/A"}</span>
              {r.total_fare != null && <span className="text-white font-semibold">₦{r.total_fare.toLocaleString()}</span>}
            </div>

            {r.status === "completed" && r.payment_status === "paid" && (
              r.my_rating_submitted ? (
                <p className="text-[#1be451] text-xs font-semibold mt-1">
                  <i className="fa-solid fa-star mr-1" />
                  You rated this {isDriver ? "rider" : "driver"}
                </p>
              ) : ratingRideId === r.ride_id ? (
                accessToken && (
                  <div className="mt-1">
                    <RateRide
                      rideId={r.ride_id}
                      accessToken={accessToken}
                      raterLabel={isDriver ? "rider" : "driver"}
                      onSubmitted={() => {
                        setRides((prev) =>
                          prev?.map((row) =>
                            row.ride_id === r.ride_id ? { ...row, my_rating_submitted: true } : row,
                          ) ?? prev,
                        );
                      }}
                    />
                  </div>
                )
              ) : (
                <button
                  type="button"
                  onClick={() => setRatingRideId(r.ride_id)}
                  className="self-start text-[#1be451] text-xs font-semibold mt-1"
                >
                  <i className="fa-solid fa-star mr-1" />
                  Rate this {isDriver ? "rider" : "driver"}
                </button>
              )
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
