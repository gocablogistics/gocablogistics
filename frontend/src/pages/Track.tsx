import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { getTracking, type TrackingOut } from "../api/rides";
import { ApiError } from "../api/http";
import RideMap from "../components/RideMap";
import Loader from "../components/Loader";
import { useElementHeight } from "../hooks/useElementHeight";

// Public, no-login page a recipient opens from a link the sender shares
// (see ActiveRideScreen.tsx's "Share tracking" button and
// api/rides.ts:getTracking) — same idea as Uber's trip-share link. Polls
// rather than using the authenticated WebSocket layer, since there's no
// account here to authenticate as.
const POLL_MS = 5000;

const STATUS_TEXT: Record<string, string> = {
  pending: "Waiting for a driver to accept this delivery…",
  accepted: "On the way to pick up the package",
  started: "On the way to you",
  completed: "Delivered",
  cancelled: "This delivery was cancelled",
};

export default function Track() {
  const { token } = useParams<{ token: string }>();
  const [data, setData] = useState<TrackingOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [cardRef, cardHeight] = useElementHeight<HTMLDivElement>();
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!token) {
      setError("This tracking link is invalid.");
      setLoading(false);
      return;
    }

    let cancelled = false;
    const poll = () => {
      getTracking(token)
        .then((result) => {
          if (cancelled) return;
          setData(result);
          setError(null);
          // Nothing left to watch once the trip is over — stop hammering
          // the endpoint for a recipient who's left the page open.
          if ((result.status === "completed" || result.status === "cancelled") && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        })
        .catch((err) => {
          if (cancelled) return;
          setError(err instanceof ApiError ? err.message : "Could not load this tracking link.");
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    };

    poll();
    pollRef.current = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [token]);

  if (loading) {
    return <Loader fullScreen message="Loading tracking info" />;
  }

  if (error || !data) {
    return (
      <div className="fixed inset-0 flex flex-col items-center justify-center gap-4 bg-[#20241f] text-slate-100 px-8 text-center">
        <div className="w-16 h-16 rounded-full bg-red-500/20 flex items-center justify-center text-3xl text-red-400">
          <i className="fa-solid fa-triangle-exclamation" />
        </div>
        <h1 className="text-white text-xl font-extrabold">Can't load this link</h1>
        <p className="text-slate-400">{error || "This tracking link is invalid or has expired."}</p>
      </div>
    );
  }

  const driverPosition =
    data.driver_latitude != null && data.driver_longitude != null
      ? { lat: data.driver_latitude, lng: data.driver_longitude }
      : null;
  const destination =
    data.destination_latitude != null && data.destination_longitude != null
      ? { lat: data.destination_latitude, lng: data.destination_longitude }
      : null;

  return (
    <div className="fixed inset-0 flex flex-col bg-[#20241f]">
      <RideMap
        fullScreen
        dark
        pickup={null}
        destination={destination}
        movingMarker={driverPosition}
        bottomInset={cardHeight}
        routeOrigin={driverPosition}
        routeDestination={destination}
      />

      <div
        ref={cardRef}
        className="relative mt-auto rounded-t-3xl bg-[#181c17] px-6 pt-6 pb-8 flex flex-col gap-4 text-slate-100"
      >
        <div className="rounded-full bg-[#1be451] text-neutral-900 font-bold text-sm px-5 py-2.5 text-center">
          {STATUS_TEXT[data.status] || data.status}
        </div>

        <p className="text-slate-300 text-sm">
          Delivering to <strong className="text-white">{data.destination}</strong>
        </p>

        {data.pickup_eta_min != null && (
          <p className="text-slate-400 text-sm">
            About <span className="text-white font-semibold">{data.pickup_eta_min} min</span> to pickup
          </p>
        )}

        {data.driver_name && (
          <div className="rounded-2xl bg-white/5 border border-white/10 p-4 flex items-center gap-3">
            {data.driver_photo ? (
              <img
                src={data.driver_photo}
                alt={data.driver_name}
                className="w-12 h-12 rounded-full object-cover shrink-0"
              />
            ) : (
              <div className="w-12 h-12 rounded-full bg-white/10 flex items-center justify-center text-xl shrink-0">
                <i className="fa-solid fa-user text-slate-300" />
              </div>
            )}
            <div className="flex-1">
              <p className="text-white font-semibold">{data.driver_name}</p>
              <p className="text-slate-400 text-xs">{data.vehicle_type}</p>
            </div>
          </div>
        )}

        <p className="text-slate-500 text-xs text-center">Tracked with GoCab</p>
      </div>
    </div>
  );
}
