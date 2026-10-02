import { useState } from "react";
import type { DriverActiveRideOut, RideMessageOut } from "../api/rides";
import NotificationBell from "./NotificationBell";
import NavDrawer from "./NavDrawer";
import ChatPanel from "./ChatPanel";
import RideMap from "./RideMap";
import RateRide from "./RateRide";
import { formatDistance } from "../lib/formatDistance";
import { useElementHeight } from "../hooks/useElementHeight";
import { openNavigation } from "../lib/mapVisuals";

interface DriverActiveRideScreenProps {
  ride: DriverActiveRideOut;
  accessToken: string | null;
  driverPosition: { lat: number; lng: number } | null;
  actingOn: number | null;
  actionError: string | null;
  onStart: () => void;
  onComplete: () => void;
  onDriverCancel: () => void;
  cashCodeInput: string;
  onCashCodeChange: (v: string) => void;
  confirmingCash: boolean;
  cashError: string | null;
  onConfirmCash: () => void;
  reportReason: string;
  onReportReasonChange: (v: string) => void;
  reporting: boolean;
  reportError: string | null;
  onReportNonPayment: () => void;
  messages: RideMessageOut[];
  myUserId: number;
  unreadCount: number;
  chatOpen: boolean;
  onOpenChat: () => void;
  onCloseChat: () => void;
  sendingMessage: boolean;
  onSendMessage: (text: string) => void;
  onDone: () => void;
  onLogout: () => void;
}

const STATUS_BANNER: Record<string, string> = {
  accepted: "Courier ride accepted",
  started: "Courier trip in progress",
  completed: "Trip completed",
};

export default function DriverActiveRideScreen({
  ride,
  accessToken,
  driverPosition,
  actingOn,
  actionError,
  onStart,
  onComplete,
  onDriverCancel,
  cashCodeInput,
  onCashCodeChange,
  confirmingCash,
  cashError,
  onConfirmCash,
  reportReason,
  onReportReasonChange,
  reporting,
  reportError,
  onReportNonPayment,
  messages,
  myUserId,
  unreadCount,
  chatOpen,
  onOpenChat,
  onCloseChat,
  sendingMessage,
  onSendMessage,
  onDone,
  onLogout,
}: DriverActiveRideScreenProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [sheetRef, sheetHeight] = useElementHeight<HTMLDivElement>();

  // Where the driver is headed right now: the pickup first, then the drop-off.
  const navTarget =
    ride.status === "started"
      ? ride.destination_latitude != null && ride.destination_longitude != null
        ? { lat: ride.destination_latitude, lng: ride.destination_longitude }
        : null
      : ride.pickup_latitude != null && ride.pickup_longitude != null
        ? { lat: ride.pickup_latitude, lng: ride.pickup_longitude }
        : null;

  return (
    <div className="fixed inset-0 flex flex-col bg-[#20241f]">
      {(ride.status === "accepted" || ride.status === "started") && (
        <RideMap
          fullScreen
          dark
          pickup={
            ride.pickup_latitude != null && ride.pickup_longitude != null
              ? { lat: ride.pickup_latitude, lng: ride.pickup_longitude }
              : null
          }
          destination={
            ride.destination_latitude != null && ride.destination_longitude != null
              ? { lat: ride.destination_latitude, lng: ride.destination_longitude }
              : null
          }
          movingMarker={driverPosition}
          routeOrigin={driverPosition}
          routeDestination={navTarget}
          bottomInset={sheetHeight}
        />
      )}

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
        <div className="rounded-full bg-[#1be451] text-neutral-900 font-bold text-sm px-5 py-2.5 flex items-center justify-between">
          <span>{STATUS_BANNER[ride.status] || ride.status}</span>
          {ride.total_fare != null && <span>₦{ride.total_fare.toLocaleString()}</span>}
        </div>

        {ride.status === "accepted" && (
          <div
            className="rounded-2xl bg-white/5 border border-white/10 px-4 py-3 flex items-center gap-4"
            aria-live="polite"
          >
            <div className="w-12 h-12 shrink-0 rounded-full bg-[#1be451]/15 flex items-center justify-center text-[#1be451] text-lg">
              <i className="fa-solid fa-location-dot" />
            </div>
            {ride.pickup_eta_min == null ? (
              <p className="text-slate-400 text-sm">Working out the time to pickup…</p>
            ) : ride.pickup_eta_min === 0 ? (
              <div>
                <p className="text-white font-bold text-lg leading-tight">You're at the pickup point</p>
                <p className="text-slate-400 text-xs">Tap Start courier trip when you have the package</p>
              </div>
            ) : (
              <div className="flex-1">
                <p className="text-white font-extrabold text-2xl leading-none">
                  {ride.pickup_eta_min} <span className="text-base font-bold text-slate-300">min</span>
                </p>
                <p className="text-slate-400 text-xs mt-1">
                  to pickup
                  {ride.pickup_distance_km != null && ` · ${formatDistance(ride.pickup_distance_km)} away`}
                </p>
              </div>
            )}
          </div>
        )}

        <div className="flex items-center gap-3">
          <p className="flex-1 text-slate-300 text-sm">
            <strong className="text-white">{ride.current_location}</strong>
            {" → "}
            <strong className="text-white">{ride.destination}</strong>
          </p>
          {navTarget && (ride.status === "accepted" || ride.status === "started") && (
            <button
              type="button"
              onClick={() => openNavigation(navTarget)}
              aria-label={ride.status === "started" ? "Navigate to drop-off" : "Navigate to pickup"}
              className="shrink-0 flex flex-col items-center gap-1 text-[#1be451]"
            >
              <span className="w-11 h-11 rounded-full border border-[#1be451]/50 bg-[#1be451]/10 flex items-center justify-center">
                <i className="fa-solid fa-diamond-turn-right" />
              </span>
              <span className="text-[10px] font-semibold leading-none">Navigate</span>
            </button>
          )}
        </div>

        <div className="rounded-2xl bg-white/5 border border-white/10 p-4 flex items-center gap-3">
          <div className="w-12 h-12 rounded-full bg-white/10 flex items-center justify-center text-xl">
            <i className="fa-solid fa-user text-slate-300" />
          </div>
          <div className="flex-1">
            <p className="text-white font-semibold">{ride.passenger.name}</p>
            <p className="text-slate-400 text-xs">{ride.passenger.phone}</p>
          </div>
          <span className="text-[#1be451] text-xs font-semibold">
            <i className="fa-solid fa-star mr-1" />
            {ride.passenger.rating.toFixed(1)}
          </span>
        </div>

        {(ride.status === "accepted" || ride.status === "started") && (
          <div className="flex gap-2">
            <a
              href={`tel:${ride.passenger.phone}`}
              className="flex-1 py-3 rounded-full bg-white/10 border border-white/20 text-white font-semibold flex items-center justify-center gap-2"
            >
              <i className="fa-solid fa-phone" />
              Call passenger
            </a>
            <button
              onClick={onOpenChat}
              className="relative flex-1 py-3 rounded-full bg-white/10 border border-white/20 text-white font-semibold flex items-center justify-center gap-2"
            >
              <i className="fa-solid fa-comment-dots" />
              Message
              {unreadCount > 0 && (
                <span className="absolute -top-1.5 -right-1.5 bg-red-500 text-white rounded-full text-[10px] font-bold min-w-[16px] h-[16px] flex items-center justify-center px-1 leading-none">
                  {unreadCount > 9 ? "9+" : unreadCount}
                </span>
              )}
            </button>
          </div>
        )}

        {ride.status === "accepted" && (
          <div className="flex gap-2">
            <button
              onClick={onStart}
              disabled={actingOn === ride.ride_id}
              className="flex-1 py-3 rounded-full bg-[#1be451] text-neutral-900 font-bold disabled:opacity-50"
            >
              Start courier trip
            </button>
            <button
              onClick={onDriverCancel}
              disabled={actingOn === ride.ride_id}
              className="flex-1 py-3 rounded-full bg-white/10 border border-white/20 text-red-400 font-semibold disabled:opacity-50"
            >
              Cancel courier ride
            </button>
          </div>
        )}
        {ride.status === "started" && (
          <button
            onClick={onComplete}
            disabled={actingOn === ride.ride_id}
            className="w-full py-3 rounded-full bg-[#1be451] text-neutral-900 font-bold disabled:opacity-50"
          >
            Complete courier trip
          </button>
        )}
        {actionError && <p className="text-red-400 text-sm text-center">{actionError}</p>}

        {ride.status === "completed" && ride.payment_status === "paid" && (
          <div className="flex flex-col gap-3">
            <p className="text-[#1be451] font-semibold text-center">Paid</p>
            {accessToken && <RateRide rideId={ride.ride_id} accessToken={accessToken} raterLabel="passenger" />}
            <button onClick={onDone} className="w-full py-4 rounded-full bg-[#1be451] text-neutral-900 font-bold text-lg">
              Done
            </button>
          </div>
        )}

        {ride.status === "completed" &&
          (ride.payment_status === "reported" || ride.payment_status === "disputed") && (
            <div className="flex flex-col gap-3">
              <p className="text-amber-400 text-sm text-center">
                {ride.payment_status === "disputed"
                  ? "Reported as unpaid. An admin reviewed it and blocked the passenger from booking again until they pay."
                  : "Reported as unpaid. An admin will review it shortly."}
              </p>
              <button onClick={onDone} className="w-full py-4 rounded-full bg-[#1be451] text-neutral-900 font-bold text-lg">
                Done
              </button>
            </div>
          )}

        {ride.status === "completed" &&
          ride.payment_status !== "paid" &&
          ride.payment_status !== "reported" &&
          ride.payment_status !== "disputed" && (
            <div className="flex flex-col gap-3">
              {ride.payment_method === "cash" ? (
                <>
                  <div>
                    <p className="text-white text-sm mb-2">Enter the code the passenger gave you</p>
                    <input
                      value={cashCodeInput}
                      onChange={(e) => onCashCodeChange(e.target.value)}
                      maxLength={4}
                      inputMode="numeric"
                      className="w-full rounded-full px-4 py-3 bg-white/10 border border-white/20 text-white placeholder:text-slate-400 text-center text-2xl tracking-[0.3em]"
                    />
                  </div>
                  <button
                    onClick={onConfirmCash}
                    disabled={confirmingCash || !cashCodeInput.trim()}
                    className="w-full py-3 rounded-full bg-[#1be451] text-neutral-900 font-bold disabled:opacity-50"
                  >
                    {confirmingCash ? "Confirming…" : "Confirm cash received"}
                  </button>
                  {cashError && <p className="text-red-400 text-sm text-center">{cashError}</p>}
                </>
              ) : (
                <p className="text-slate-400 text-sm text-center">Waiting for the passenger to pay online.</p>
              )}

              <div className="flex flex-col gap-2">
                <textarea
                  value={reportReason}
                  onChange={(e) => onReportReasonChange(e.target.value)}
                  placeholder="What happened? (optional, helps admin review)"
                  rows={2}
                  className="w-full rounded-2xl px-4 py-3 bg-white/10 border border-white/20 text-white placeholder:text-slate-400"
                />
                <button
                  onClick={onReportNonPayment}
                  disabled={reporting}
                  className="w-full py-3 rounded-full bg-white/10 border border-white/20 text-white font-semibold disabled:opacity-50"
                >
                  {reporting ? "Reporting…" : "Report non-payment"}
                </button>
                {reportError && <p className="text-red-400 text-sm text-center">{reportError}</p>}
              </div>
            </div>
          )}
      </div>

      <ChatPanel
        open={chatOpen}
        onClose={onCloseChat}
        messages={messages}
        myUserId={myUserId}
        otherPartyName={ride.passenger.name}
        onSend={onSendMessage}
        sending={sendingMessage}
      />
    </div>
  );
}
