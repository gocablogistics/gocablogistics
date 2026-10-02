import { useEffect, useState } from "react";
import type { ActiveRideOut, RideMessageOut } from "../api/rides";
import { getFeatureFlags } from "../api/flags";
import NotificationBell from "./NotificationBell";
import NavDrawer from "./NavDrawer";
import ChatPanel from "./ChatPanel";
import RideMap from "./RideMap";
import RateRide from "./RateRide";
import { formatDistance } from "../lib/formatDistance";
import { useElementHeight } from "../hooks/useElementHeight";

interface ActiveRideScreenProps {
  ride: ActiveRideOut;
  accessToken: string | null;
  liveMessage: string | null;
  driverPosition: { lat: number; lng: number } | null;
  pickupEta: { min: number; km: number } | null;
  cancelling: boolean;
  cancelError: string | null;
  onCancel: () => void;
  paying: boolean;
  payError: string | null;
  cashCode: string | null;
  onPay: () => void;
  onPayCash: () => void;
  disputeStatement: string;
  onDisputeStatementChange: (v: string) => void;
  submittingDispute: boolean;
  disputeError: string | null;
  disputeSubmitted: boolean;
  onRespondToDispute: () => void;
  reportDriverReason: string;
  onReportDriverReasonChange: (v: string) => void;
  reportingDriver: boolean;
  reportDriverError: string | null;
  reportDriverSubmitted: boolean;
  onReportDriver: () => void;
  messages: RideMessageOut[];
  myUserId: number;
  unreadCount: number;
  chatOpen: boolean;
  onOpenChat: () => void;
  onCloseChat: () => void;
  sendingMessage: boolean;
  onSendMessage: (text: string) => void;
  onBookAnother: () => void;
  onLogout: () => void;
}

const CANCELLABLE_STATUSES = ["pending", "accepted"];

const STATUS_BANNER: Record<string, string> = {
  pending: "Looking for a nearby driver…",
  accepted: "Your driver is on the way",
  started: "Trip in progress",
  completed: "Trip completed",
};

export default function ActiveRideScreen({
  ride,
  accessToken,
  liveMessage,
  driverPosition,
  pickupEta,
  cancelling,
  cancelError,
  onCancel,
  paying,
  payError,
  cashCode,
  onPay,
  onPayCash,
  disputeStatement,
  onDisputeStatementChange,
  submittingDispute,
  disputeError,
  disputeSubmitted,
  onRespondToDispute,
  reportDriverReason,
  onReportDriverReasonChange,
  reportingDriver,
  reportDriverError,
  reportDriverSubmitted,
  onReportDriver,
  messages,
  myUserId,
  unreadCount,
  chatOpen,
  onOpenChat,
  onCloseChat,
  sendingMessage,
  onSendMessage,
  onBookAnother,
  onLogout,
}: ActiveRideScreenProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [cashEnabled, setCashEnabled] = useState(false);
  const [noDriversMinutes, setNoDriversMinutes] = useState(45);
  const [supportPhone, setSupportPhone] = useState("");
  // Ticks once a minute so the "no drivers nearby" message can appear
  // without the rider needing to reload — nothing else on this screen
  // otherwise re-renders on a fixed clock while a ride just sits pending.
  const [now, setNow] = useState(() => Date.now());
  const [showReportDriver, setShowReportDriver] = useState(false);
  const [trackingShared, setTrackingShared] = useState(false);
  const [sheetRef, sheetHeight] = useElementHeight<HTMLDivElement>();

  async function handleShareTracking() {
    if (!ride.tracking_url) return;
    const text = `Track your GoCab delivery here: ${ride.tracking_url}`;
    try {
      if (navigator.share) {
        await navigator.share({ text });
        return;
      }
    } catch {
      // Cancelled the share sheet, or the platform doesn't really support
      // it despite the API being present — fall through to copy.
    }
    try {
      await navigator.clipboard.writeText(text);
      setTrackingShared(true);
      setTimeout(() => setTrackingShared(false), 2000);
    } catch {
      // Clipboard blocked — nothing more to do silently.
    }
  }

  useEffect(() => {
    getFeatureFlags().then((flags) => {
      setCashEnabled(flags.cash_payments_enabled);
      setNoDriversMinutes(flags.no_drivers_message_minutes);
      setSupportPhone(flags.support_phone_number);
    });
  }, []);

  useEffect(() => {
    if (ride.status !== "pending") return;
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, [ride.status]);

  const pendingMinutes = (now - new Date(ride.requested_at).getTime()) / 60_000;
  const showNoDriversMessage = ride.status === "pending" && pendingMinutes >= noDriversMinutes;

  return (
    <div className="fixed inset-0 flex flex-col bg-[#20241f]">
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
        bottomInset={sheetHeight}
        routeOrigin={driverPosition}
        routeDestination={
          ride.status === "started"
            ? ride.destination_latitude != null && ride.destination_longitude != null
              ? { lat: ride.destination_latitude, lng: ride.destination_longitude }
              : null
            : ride.pickup_latitude != null && ride.pickup_longitude != null
              ? { lat: ride.pickup_latitude, lng: ride.pickup_longitude }
              : null
        }
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

      <NavDrawer open={menuOpen} onClose={() => setMenuOpen(false)} role="rider" onLogout={onLogout} />

      <div ref={sheetRef} className="relative mt-auto rounded-t-3xl bg-[#181c17] px-6 pt-6 pb-8 flex flex-col gap-4 text-slate-100 max-h-[55vh] overflow-y-auto">
        <div className="rounded-full bg-[#1be451] text-neutral-900 font-bold text-sm px-5 py-2.5 flex items-center justify-between">
          <span>{liveMessage || STATUS_BANNER[ride.status] || ride.status}</span>
          {ride.total_fare != null && <span>₦{ride.total_fare.toLocaleString()}</span>}
        </div>

        {showNoDriversMessage && (
          <div className="rounded-2xl bg-amber-500/10 border border-amber-500/30 px-4 py-3 flex flex-col gap-2.5">
            <p className="text-slate-200 text-sm leading-relaxed">
              Drivers are busy or unavailable in your area right now. You can keep waiting,
              cancel and try again, or call GoCab support for help finding you a ride.
            </p>
            {supportPhone && (
              <a
                href={`tel:${supportPhone}`}
                className="text-center py-2.5 rounded-full bg-amber-500/15 text-amber-300 font-semibold text-sm"
              >
                <i className="fa-solid fa-phone mr-2" />
                Call GoCab support
              </a>
            )}
          </div>
        )}

        {ride.status === "accepted" && (
          <div
            className="rounded-2xl bg-white/5 border border-white/10 px-4 py-3 flex items-center gap-4"
            aria-live="polite"
          >
            <div className="w-12 h-12 shrink-0 rounded-full bg-[#1be451]/15 flex items-center justify-center text-[#1be451] text-lg">
              <i className="fa-solid fa-clock" />
            </div>
            {pickupEta == null ? (
              <p className="text-slate-400 text-sm">Working out when your driver arrives…</p>
            ) : pickupEta.min === 0 ? (
              <div>
                <p className="text-white font-bold text-lg leading-tight">Arriving now</p>
                <p className="text-slate-400 text-xs">Your driver is at the pickup point</p>
              </div>
            ) : (
              <div className="flex-1">
                <p className="text-white font-extrabold text-2xl leading-none">
                  {pickupEta.min} <span className="text-base font-bold text-slate-300">min</span>
                </p>
                <p className="text-slate-400 text-xs mt-1">
                  until your driver arrives · {formatDistance(pickupEta.km)} away
                </p>
              </div>
            )}
          </div>
        )}

        <p className="text-slate-300 text-sm">
          <strong className="text-white">{ride.current_location}</strong>
          {" → "}
          <strong className="text-white">{ride.destination}</strong>
        </p>

        {ride.driver && (
          <div className="rounded-2xl bg-white/5 border border-white/10 p-4 flex items-center gap-3">
            {ride.driver.photo ? (
              <img
                src={ride.driver.photo}
                alt={ride.driver.name}
                className="w-12 h-12 rounded-full object-cover shrink-0"
              />
            ) : (
              <div className="w-12 h-12 rounded-full bg-white/10 flex items-center justify-center text-xl shrink-0">
                <i className="fa-solid fa-user text-slate-300" />
              </div>
            )}
            <div className="flex-1">
              <p className="text-white font-semibold">{ride.driver.name}</p>
              <p className="text-slate-400 text-xs">{ride.driver.car_model}</p>
            </div>
            <div className="flex flex-col items-end gap-1">
              <span className="bg-white text-neutral-900 text-xs font-bold rounded-full px-3 py-1">
                {ride.driver.license_plate}
              </span>
              <span className="text-[#1be451] text-xs font-semibold">
                <i className="fa-solid fa-star mr-1" />
                {ride.driver.rating.toFixed(1)}
              </span>
            </div>
          </div>
        )}

        {ride.driver && (ride.status === "accepted" || ride.status === "started") && (
          <div className="flex gap-2">
            <a
              href={`tel:${ride.driver.phone}`}
              className="flex-1 py-3 rounded-full bg-white/10 border border-white/20 text-white font-semibold flex items-center justify-center gap-2"
            >
              <i className="fa-solid fa-phone" />
              Call driver
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

        {ride.tracking_url && (ride.status === "accepted" || ride.status === "started") && (
          <button
            onClick={handleShareTracking}
            className="w-full py-3 rounded-full bg-white/10 border border-white/20 text-white font-semibold flex items-center justify-center gap-2"
          >
            <i className="fa-solid fa-share-nodes" />
            {trackingShared ? "Copied!" : "Share tracking with recipient"}
          </button>
        )}

        {CANCELLABLE_STATUSES.includes(ride.status) && (
          <button
            onClick={onCancel}
            disabled={cancelling}
            className="w-full py-3 rounded-full bg-white/10 border border-white/20 text-red-400 font-semibold disabled:opacity-50"
          >
            {cancelling ? "Cancelling…" : "Cancel ride"}
          </button>
        )}
        {cancelError && <p className="text-red-400 text-sm text-center">{cancelError}</p>}

        {ride.status === "completed" && ride.payment_status === "paid" && (
          <div className="flex flex-col gap-3">
            <p className="text-[#1be451] font-semibold text-center">Paid</p>
            {accessToken && <RateRide rideId={ride.ride_id} accessToken={accessToken} raterLabel="driver" />}
            <button
              onClick={onBookAnother}
              className="w-full py-4 rounded-full bg-[#1be451] text-neutral-900 font-bold text-lg"
            >
              Book another ride
            </button>
          </div>
        )}

        {ride.status === "completed" && ride.payment_status !== "paid" && (
          <div className="flex flex-col gap-3">
            {(ride.payment_status === "reported" || ride.payment_status === "disputed") && (
              <div className="rounded-2xl bg-amber-500/10 border border-amber-500/40 p-4 flex flex-col gap-3">
                <p className="text-amber-400 text-sm font-semibold">
                  {ride.payment_status === "disputed"
                    ? "Your driver reported this ride as unpaid, and an admin has reviewed it. You won't be able to book another ride until this is resolved. Explain your side below for another look."
                    : "Your driver reported this ride as unpaid. Pay it to keep booking, and an admin will also review the report. Feel free to explain your side below."}
                </p>
                {disputeSubmitted ? (
                  <p className="text-[#1be451] text-sm">
                    Your response has been recorded. An admin will review this and may contact you.
                  </p>
                ) : (
                  <>
                    <textarea
                      value={disputeStatement}
                      onChange={(e) => onDisputeStatementChange(e.target.value)}
                      placeholder="I already paid, or this report is wrong. Explain what happened"
                      rows={3}
                      className="w-full rounded-2xl px-4 py-3 bg-white/10 border border-white/20 text-white placeholder:text-slate-400"
                    />
                    <button
                      onClick={onRespondToDispute}
                      disabled={submittingDispute || !disputeStatement.trim()}
                      className="w-full py-3 rounded-full bg-white/10 border border-white/20 text-white font-semibold disabled:opacity-50"
                    >
                      {submittingDispute ? "Submitting…" : "Submit response"}
                    </button>
                    {disputeError && <p className="text-red-400 text-sm">{disputeError}</p>}
                  </>
                )}
              </div>
            )}

            {ride.payment_method === "cash" ? (
              cashCode ? (
                <div className="rounded-2xl bg-white/5 border border-white/10 p-4 text-center">
                  <p className="text-slate-300 text-sm mb-1">Give this code to your driver once you've paid:</p>
                  <p className="text-white text-3xl font-bold tracking-[0.3em]">{cashCode}</p>
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  <p className="text-slate-400 text-sm text-center">Waiting for the driver to confirm cash payment.</p>
                  <button
                    onClick={onPayCash}
                    disabled={paying}
                    className="w-full py-3 rounded-full bg-white/10 border border-white/20 text-white font-semibold disabled:opacity-50"
                  >
                    {paying ? "Generating…" : "Show cash code again"}
                  </button>
                </div>
              )
            ) : (
              <div className="flex gap-2">
                <button
                  onClick={onPay}
                  disabled={paying}
                  className={
                    cashEnabled
                      ? "flex-1 py-3 rounded-full bg-[#1be451] text-neutral-900 font-bold disabled:opacity-50"
                      : "w-full py-4 rounded-full bg-[#1be451] text-neutral-900 font-bold text-lg disabled:opacity-50"
                  }
                >
                  {paying ? "Starting…" : "Pay online"}
                </button>
                {cashEnabled && (
                  <button
                    onClick={onPayCash}
                    disabled={paying}
                    className="flex-1 py-3 rounded-full bg-white/10 border border-white/20 text-white font-semibold disabled:opacity-50"
                  >
                    Pay with cash
                  </button>
                )}
              </div>
            )}
            {payError && <p className="text-red-400 text-sm text-center">{payError}</p>}
          </div>
        )}

        {ride.status === "completed" && ride.driver && (
          <div className="flex flex-col gap-2">
            {reportDriverSubmitted ? (
              <p className="text-[#1be451] text-sm text-center">
                Your report has been recorded. An admin will review it.
              </p>
            ) : showReportDriver ? (
              <div className="rounded-2xl bg-white/5 border border-white/10 p-4 flex flex-col gap-3">
                <textarea
                  value={reportDriverReason}
                  onChange={(e) => onReportDriverReasonChange(e.target.value)}
                  placeholder="What happened? An admin will review this."
                  rows={3}
                  className="w-full rounded-2xl px-4 py-3 bg-white/10 border border-white/20 text-white placeholder:text-slate-400"
                />
                <button
                  onClick={onReportDriver}
                  disabled={reportingDriver || !reportDriverReason.trim()}
                  className="w-full py-3 rounded-full bg-white/10 border border-white/20 text-white font-semibold disabled:opacity-50"
                >
                  {reportingDriver ? "Submitting…" : "Submit report"}
                </button>
                {reportDriverError && <p className="text-red-400 text-sm text-center">{reportDriverError}</p>}
              </div>
            ) : (
              <button
                onClick={() => setShowReportDriver(true)}
                className="text-slate-400 text-xs underline self-center"
              >
                Report an issue with this driver
              </button>
            )}
          </div>
        )}
      </div>

      <ChatPanel
        open={chatOpen}
        onClose={onCloseChat}
        messages={messages}
        myUserId={myUserId}
        otherPartyName={ride.driver?.name}
        onSend={onSendMessage}
        sending={sendingMessage}
      />
    </div>
  );
}
