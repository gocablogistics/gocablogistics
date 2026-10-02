import { useState } from "react";
import RideMap from "./RideMap";
import NotificationBell from "./NotificationBell";
import NavDrawer from "./NavDrawer";
import { useElementHeight } from "../hooks/useElementHeight";
import type { AvailabilityOut, DriverSummaryOut, NearbyRideOut, PayoutOut } from "../api/rides";

interface DriverBrowseScreenProps {
  accessToken: string | null;
  driverPosition: { lat: number; lng: number } | null;
  availability: AvailabilityOut | null;
  summary: DriverSummaryOut | null;
  payouts: PayoutOut[];
  nearbyRides: NearbyRideOut[];
  toggling: boolean;
  toggleError: string | null;
  onToggleOnline: () => void;
  actingOn: number | null;
  actionError: string | null;
  onAccept: (rideId: number) => void;
  onLogout: () => void;
}

export default function DriverBrowseScreen({
  accessToken,
  driverPosition,
  availability,
  summary,
  payouts,
  nearbyRides,
  toggling,
  toggleError,
  onToggleOnline,
  actingOn,
  actionError,
  onAccept,
  onLogout,
}: DriverBrowseScreenProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [showPayouts, setShowPayouts] = useState(false);
  const [sheetRef, sheetHeight] = useElementHeight<HTMLDivElement>();

  const requestPins = availability?.is_online
    ? nearbyRides.flatMap((r) =>
        r.pickup_latitude != null && r.pickup_longitude != null
          ? [{ lat: r.pickup_latitude, lng: r.pickup_longitude }]
          : [],
      )
    : [];

  return (
    <div className="fixed inset-0 flex flex-col bg-[#20241f]">
      <RideMap
        fullScreen
        dark
        pickup={null}
        destination={null}
        movingMarker={driverPosition}
        requestPins={requestPins}
        bottomInset={sheetHeight}
      />

      <button
        onClick={() => setMenuOpen(true)}
        className="absolute top-4 left-4 z-10 bg-black/40 rounded-full w-10 h-10 flex items-center justify-center text-white"
        aria-label="Menu"
      >
        <i className="fa-solid fa-bars" />
      </button>

      {accessToken && (
        <div className="absolute top-4 right-4 z-10 bg-black/40 rounded-full p-1.5 text-white">
          <NotificationBell accessToken={accessToken} />
        </div>
      )}

      <NavDrawer open={menuOpen} onClose={() => setMenuOpen(false)} role="driver" onLogout={onLogout} />

      <div ref={sheetRef} className="relative mt-auto rounded-t-3xl bg-[#181c17] px-6 pt-6 pb-8 flex flex-col gap-4 text-slate-100 max-h-[80vh] overflow-y-auto">
        {summary && (
          <div className="rounded-2xl bg-white/5 border border-white/10 p-4 flex flex-col gap-1">
            <p className="text-white font-bold text-lg">₦{summary.todays_earnings.toLocaleString()} <span className="text-slate-400 text-xs font-normal">today</span></p>
            <p className="text-slate-400 text-xs">
              ₦{summary.total_earnings.toLocaleString()} all time · {summary.completed_trips} trips · {summary.completion_rate}% completion
            </p>
            {summary.cash_debt > 0 && (
              <p className={`text-xs font-semibold ${summary.cash_debt_blocked ? "text-red-400" : "text-amber-400"}`}>
                Cash commission owed: ₦{summary.cash_debt.toLocaleString()}
                {summary.cash_debt_blocked && ", you're blocked from going online until this is settled"}
              </p>
            )}
            <button
              onClick={() => setShowPayouts((v) => !v)}
              className="self-start text-[#1be451] text-xs font-semibold mt-1"
            >
              {showPayouts ? "Hide payouts" : `Payouts (${payouts.length})`}
            </button>
            {showPayouts && (
              <div className="mt-1 flex flex-col gap-1">
                {payouts.length === 0 ? (
                  <p className="text-slate-400 text-xs">No card-paid trips yet. Cash trips are paid to you directly.</p>
                ) : (
                  payouts.map((p) => (
                    <div key={p.id} className="flex justify-between text-xs border-t border-white/10 pt-1">
                      <span className="text-slate-300">Ride #{p.ride_id}, ₦{p.amount.toLocaleString()}</span>
                      <span
                        className={
                          p.status === "paid"
                            ? "text-[#1be451]"
                            : p.status === "failed"
                              ? "text-red-400"
                              : "text-amber-400"
                        }
                      >
                        {p.status}
                      </span>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        )}

        {availability && (
          <div>
            <button
              onClick={onToggleOnline}
              disabled={toggling}
              className={`w-full py-4 rounded-full font-bold text-lg disabled:opacity-50 ${
                availability.is_online
                  ? "bg-white/10 border border-white/20 text-white"
                  : "bg-[#1be451] text-neutral-900"
              }`}
            >
              {toggling ? "Updating…" : availability.is_online ? "Go offline" : "Go online"}
            </button>
            {toggleError && <p className="text-red-400 text-sm text-center mt-2">{toggleError}</p>}
          </div>
        )}

        {availability?.is_online ? (
          <div className="flex flex-col gap-2">
            <h3 className="text-white font-semibold">Nearby requests</h3>
            {nearbyRides.length === 0 && (
              <p className="text-slate-400 text-sm">No pending requests nearby.</p>
            )}
            {nearbyRides.map((ride) => (
              <div key={ride.id} className="rounded-2xl bg-white/5 border border-white/10 p-4 flex flex-col gap-2">
                <p className="text-white text-sm">
                  <strong>{ride.current_location}</strong>
                  {" → "}
                  <strong>{ride.destination}</strong>
                </p>
                <p className="text-slate-400 text-xs">
                  {ride.distance_from_driver != null && `${ride.distance_from_driver}km away`}
                  {ride.estimated_pickup_time != null && ` · ~${ride.estimated_pickup_time}min pickup`}
                  {ride.total_fare != null && ` · ₦${ride.total_fare.toLocaleString()}`}
                </p>
                <p className="text-slate-300 text-xs">
                  {ride.passenger_name} ({ride.passenger_rating.toFixed(1)}★), {ride.passenger_phone}
                </p>
                <button
                  onClick={() => onAccept(ride.id)}
                  disabled={actingOn === ride.id}
                  className="w-full py-3 rounded-full bg-[#1be451] text-neutral-900 font-bold disabled:opacity-50"
                >
                  {actingOn === ride.id ? "Accepting…" : "Accept"}
                </button>
              </div>
            ))}
            {actionError && <p className="text-red-400 text-sm text-center">{actionError}</p>}
          </div>
        ) : (
          <p className="text-slate-400 text-sm text-center">You're offline. Go online to see nearby requests.</p>
        )}
      </div>
    </div>
  );
}
