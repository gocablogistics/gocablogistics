import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  cancelRide,
  getActiveRide,
  getRideMessages,
  initiatePayment,
  confirmPayment,
  payCash,
  reportDriver,
  respondToDispute,
  rideUpdatesSocketUrl,
  sendRideMessage,
  updateRiderLocation,
  type ActiveRideOut,
  type RideMessageOut,
} from "../api/rides";
import { ApiError } from "../api/http";
import { useAuth } from "../auth/AuthContext";
import { useAutoDismiss } from "../hooks/useAutoDismiss";
import { getCurrentPosition } from "../lib/geolocation";
import { openExternal } from "../lib/openExternal";
import { isTauri } from "@tauri-apps/api/core";
import Loader from "../components/Loader";
import BookingScreen from "../components/BookingScreen";
import ActiveRideScreen from "../components/ActiveRideScreen";
import { savePendingBooking } from "../booking/pendingBooking";

const LOCATION_PING_MS = 15000;
// Only pre-pickup — once the trip has "started" the rider is physically in
// the vehicle with the driver, so sharing their own position separately
// adds nothing (and just burns battery/bandwidth).
const RIDER_LOCATION_SHARING_STATUSES = ["pending", "accepted"];
const STATUS_POLL_MS = 10000;
const ACTIVE_STATUSES = ["pending", "accepted", "started"];
const RECONNECT_DELAY_MS = 2000;

export default function RiderHome() {
  const { accessToken, logout, myUserId } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const navState = location.state as
    | { bookedRideId?: number; bookingError?: string }
    | null;

  const [ride, setRide] = useState<ActiveRideOut | null>(null);
  const [loadingRide, setLoadingRide] = useState(true);
  const [liveMessage, setLiveMessage] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [paying, setPaying] = useState(false);
  const [payError, setPayError] = useState<string | null>(null);
  const [cashCode, setCashCode] = useState<string | null>(null);
  const [disputeStatement, setDisputeStatement] = useState("");
  const [submittingDispute, setSubmittingDispute] = useState(false);
  const [disputeError, setDisputeError] = useState<string | null>(null);
  const [disputeSubmitted, setDisputeSubmitted] = useState(false);
  const [driverPosition, setDriverPosition] = useState<{ lat: number; lng: number } | null>(null);
  // Minutes until the driver reaches the pickup point — seeded from the REST
  // snapshot, then refreshed by every live driver_location message.
  const [pickupEta, setPickupEta] = useState<{ min: number; km: number } | null>(null);
  const [reportDriverReason, setReportDriverReason] = useState("");
  const [reportingDriver, setReportingDriver] = useState(false);
  const [reportDriverError, setReportDriverError] = useState<string | null>(null);
  const [reportDriverSubmitted, setReportDriverSubmitted] = useState(false);
  const [messages, setMessages] = useState<RideMessageOut[]>([]);
  const [chatOpen, setChatOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [sendingMessage, setSendingMessage] = useState(false);
  const chatOpenRef = useRef(chatOpen);
  chatOpenRef.current = chatOpen;

  useAutoDismiss(cancelError, () => setCancelError(null));
  useAutoDismiss(payError, () => setPayError(null));
  useAutoDismiss(disputeError, () => setDisputeError(null));
  useAutoDismiss(reportDriverError, () => setReportDriverError(null));

  function appendMessage(msg: RideMessageOut) {
    setMessages((prev) => (prev.some((m) => m.id === msg.id) ? prev : [...prev, msg]));
  }

  // Seeds the map's driver dot from the REST snapshot's last-known position.
  // Only called from REST fetches, not from the websocket's live updates —
  // those go straight to setDriverPosition so a stale REST re-fetch (e.g.
  // triggered by an unrelated event) can't overwrite a fresher live pin.
  function applyRide(r: ActiveRideOut) {
    setRide((prev) => {
      if (!prev || prev.ride_id !== r.ride_id) {
        // A genuinely new ride (not just a status update on the same one)
        // starts with a clean chat thread instead of carrying over the
        // previous trip's messages.
        setMessages([]);
        setUnreadCount(0);
      }
      return r;
    });
    setPickupEta(
      r.pickup_eta_min != null ? { min: r.pickup_eta_min, km: r.driver_distance_km ?? 0 } : null,
    );
    if (r.driver?.latitude != null && r.driver?.longitude != null) {
      setDriverPosition({ lat: r.driver.latitude, lng: r.driver.longitude });
    }
  }

  // Only the first load of a login session should block the screen behind
  // a full-page spinner — accessToken also changes every ~20 min when
  // AuthContext silently rotates it, and without this guard that would
  // unmount the entire active-ride screen (map, chat, pay button) mid-trip
  // every time. Reset on logout so a fresh login still loads normally.
  const hasLoadedRideRef = useRef(false);
  useEffect(() => {
    if (!accessToken) {
      hasLoadedRideRef.current = false;
      return;
    }
    if (hasLoadedRideRef.current) return;
    hasLoadedRideRef.current = true;

    // No "cancelled" flag / cleanup here on purpose: StrictMode runs this
    // effect, cleans it up, and runs it again in dev — the once-only guard
    // above skips that second run, so a cleanup that discards this fetch's
    // result would leave the screen stuck on "Checking for an active trip…"
    // forever. Setting state after an unmount is harmless in React 18.
    setLoadingRide(true);
    getActiveRide(accessToken)
      .then((r) => applyRide(r))
      .catch((err) => {
        if (!(err instanceof ApiError && err.status === 404)) {
          console.error("Failed to load active ride", err);
        }
      })
      .finally(() => setLoadingRide(false));
  }, [accessToken]);

  useEffect(() => {
    if (!accessToken || !ride) return;
    let cancelled = false;
    getRideMessages(ride.ride_id, accessToken)
      .then((msgs) => {
        if (!cancelled) setMessages(msgs);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [accessToken, ride?.ride_id]);

  useEffect(() => {
    if (!accessToken || !ride) return;

    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      if (cancelled) return;
      socket = new WebSocket(rideUpdatesSocketUrl(accessToken!));

      socket.onopen = () => {
        socket!.send(JSON.stringify({ action: "subscribe", ride_id: ride!.ride_id }));
      };

      socket.onclose = () => {
        // The dev server's autoreloader (or any transient network blip) can
        // drop this without the tab ever knowing — without a reconnect, the
        // rider's screen would silently freeze on whatever status it last
        // saw (e.g. stuck on "accepted" after the driver has since started
        // the trip) until they manually refresh. Re-fetching on reconnect
        // catches up on anything missed while disconnected.
        if (cancelled) return;
        reconnectTimer = setTimeout(() => {
          getActiveRide(accessToken!).then(applyRide).catch(() => {});
          connect();
        }, RECONNECT_DELAY_MS);
      };

      socket.onmessage = handleMessage;
    }

    function handleMessage(event: MessageEvent) {
      const msg = JSON.parse(event.data);
      const status: string | undefined = msg.data?.status ?? msg.event;

      if (msg.type === "chat_message") {
        appendMessage(msg as RideMessageOut);
        if (!chatOpenRef.current) setUnreadCount((n) => n + 1);
      } else if (msg.type === "driver_location") {
        if (typeof msg.lat === "number" && typeof msg.lng === "number") {
          setDriverPosition({ lat: msg.lat, lng: msg.lng });
        }
        if (typeof msg.eta_min === "number") {
          setPickupEta({ min: msg.eta_min, km: typeof msg.distance_km === "number" ? msg.distance_km : 0 });
        }
      } else if (msg.type === "ride_accepted" || status === "accepted") {
        setLiveMessage(msg.message ?? "A rider has accepted your request.");
        // The websocket payload's driver-info shape varies by event source
        // and doesn't line up with ActiveRideOut — re-fetch the REST
        // endpoint instead of trying to reconcile the two shapes.
        getActiveRide(accessToken!).then(applyRide).catch(() => {});
      } else if (msg.type === "ride_update" && msg.event === "payment_completed") {
        // Not a ride-lifecycle status — a separate payment event riding the
        // same "ride_update" type, so it needs its own branch rather than
        // falling into the generic status assignment below.
        setLiveMessage("Payment received, thank you!");
        setRide((prev) => (prev ? { ...prev, payment_status: "paid" } : prev));
      } else if (msg.type === "ride_update" && msg.event === "driver_cancelled") {
        // "driver_cancelled" is an event label, not a real RideRequest
        // status — the ride actually reverts to "pending" server-side (back
        // in the pool for another driver). Re-fetch instead of assigning
        // the literal event string as the status.
        setLiveMessage("The driver cancelled. Looking for another driver.");
        getActiveRide(accessToken!).then(applyRide).catch(() => {});
      } else if (msg.type === "ride_update" && msg.event === "payment_reported") {
        // A driver's report — doesn't block booking on its own, just opens
        // it for admin review (see fraud_checks.has_disputed_unpaid_ride).
        setLiveMessage("Your driver reported this ride as unpaid. Pay it to keep booking.");
        setRide((prev) => (prev ? { ...prev, payment_status: "reported" } : prev));
      } else if (msg.type === "ride_update" && msg.event === "payment_disputed") {
        // An admin reviewed an open report and flagged the account — this
        // is the event that actually blocks new bookings.
        setLiveMessage("An admin flagged your account after reviewing your driver's report.");
        setRide((prev) => (prev ? { ...prev, payment_status: "disputed" } : prev));
      } else if (msg.type === "ride_update") {
        setLiveMessage(status ? `Status: ${status}` : null);
        setRide((prev) =>
          prev
            ? {
                ...prev,
                status: status ?? prev.status,
                total_fare: msg.data?.fare ?? prev.total_fare,
              }
            : prev,
        );
      }
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken, ride?.ride_id]);

  // Fallback safety net independent of the websocket above — polls the REST
  // snapshot periodically so a missed/late push (e.g. a dropped socket that
  // hasn't reconnected yet) can't leave the screen stuck on a stale status
  // indefinitely.
  useEffect(() => {
    if (!accessToken || !ride || !ACTIVE_STATUSES.includes(ride.status)) return;
    let cancelled = false;
    const id = setInterval(() => {
      getActiveRide(accessToken)
        .then((r) => {
          if (!cancelled) applyRide(r);
        })
        .catch((err) => {
          if (!cancelled && err instanceof ApiError && err.status === 404) {
            setRide(null);
          }
        });
    }, STATUS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken, ride?.ride_id, ride?.status]);

  // Share the rider's own position back to the driver pre-pickup — mirrors
  // the driver's existing location-ping loop in DriverHome.
  useEffect(() => {
    if (!accessToken || !ride) return;
    if (!RIDER_LOCATION_SHARING_STATUSES.includes(ride.status)) return;

    const ping = () => {
      getCurrentPosition(
        (coords) => {
          updateRiderLocation(coords.latitude, coords.longitude, accessToken).catch(() => {});
        },
        () => {},
      );
    };
    ping();
    const id = setInterval(ping, LOCATION_PING_MS);
    return () => clearInterval(id);
  }, [accessToken, ride?.status]);

  // When the rider returns to the app after paying in the browser, ask the
  // server to verify the payment with Paystack instead of waiting on the
  // websocket, which Android may have dropped while the app was away.
  const payLinkOpenedRef = useRef(false);
  useEffect(() => {
    if (!accessToken || !ride || ride.status !== "completed" || ride.payment_status === "paid") return;
    const rideId = ride.ride_id;
    const onVisible = () => {
      if (document.visibilityState !== "visible" || !payLinkOpenedRef.current) return;
      confirmPayment(rideId, accessToken)
        .then((res) => {
          if (res.payment_status === "paid") {
            payLinkOpenedRef.current = false;
            setLiveMessage("Payment received, thank you!");
            setRide((prev) => (prev ? { ...prev, payment_status: "paid" } : prev));
          }
        })
        .catch(() => {});
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [accessToken, ride?.ride_id, ride?.status, ride?.payment_status]);

  async function handlePay() {
    if (!ride || !accessToken) return;
    setPaying(true);
    setPayError(null);
    try {
      const result = await initiatePayment(ride.ride_id, accessToken);
      if (result.paid_via_wallet_credit) {
        // Wallet credit covered the fare in full — the ride is already
        // marked paid server-side, nothing to redirect to.
        setLiveMessage("Paid with your wallet credit, thank you!");
        setRide((prev) => (prev ? { ...prev, payment_status: "paid" } : prev));
      } else if (result.payment_url) {
        if (isTauri()) {
          // In the Android app the WebView can't come back from Paystack to
          // the app (the redirect lands on the website, without the rider's
          // login) — so pay in the phone's browser and re-check on return.
          const opened = await openExternal(result.payment_url);
          if (opened) {
            payLinkOpenedRef.current = true;
            setLiveMessage("Finish paying in your browser, then come back here");
          } else {
            setPayError("Couldn't open the payment page.");
          }
        } else {
          window.location.href = result.payment_url;
        }
      } else {
        setPayError(result.error ?? "Could not start payment.");
      }
    } catch (err) {
      setPayError(err instanceof ApiError ? err.message : "Could not start payment.");
    } finally {
      setPaying(false);
    }
  }

  async function handleCancel() {
    if (!ride || !accessToken) return;
    setCancelling(true);
    setCancelError(null);
    try {
      await cancelRide(ride.ride_id, accessToken);
      setRide(null);
      setLiveMessage(null);
      setCashCode(null);
      setDriverPosition(null);
    } catch (err) {
      setCancelError(err instanceof ApiError ? err.message : "Could not cancel.");
    } finally {
      setCancelling(false);
    }
  }

  async function handlePayCash() {
    if (!ride || !accessToken) return;
    setPaying(true);
    setPayError(null);
    try {
      const result = await payCash(ride.ride_id, accessToken);
      if (result.code) {
        setCashCode(result.code);
        setRide((prev) => (prev ? { ...prev, payment_method: "cash" } : prev));
      } else {
        setPayError(result.error ?? "Could not start cash payment.");
      }
    } catch (err) {
      setPayError(err instanceof ApiError ? err.message : "Could not start cash payment.");
    } finally {
      setPaying(false);
    }
  }

  async function handleRespondToDispute() {
    if (!ride || !accessToken || !disputeStatement.trim()) return;
    setSubmittingDispute(true);
    setDisputeError(null);
    try {
      await respondToDispute(ride.ride_id, disputeStatement.trim(), accessToken);
      setDisputeSubmitted(true);
    } catch (err) {
      setDisputeError(err instanceof ApiError ? err.message : "Could not submit your response.");
    } finally {
      setSubmittingDispute(false);
    }
  }

  async function handleReportDriver() {
    if (!ride || !accessToken || !reportDriverReason.trim()) return;
    setReportingDriver(true);
    setReportDriverError(null);
    try {
      await reportDriver(ride.ride_id, accessToken, reportDriverReason.trim());
      setReportDriverSubmitted(true);
    } catch (err) {
      setReportDriverError(err instanceof ApiError ? err.message : "Could not submit your report.");
    } finally {
      setReportingDriver(false);
    }
  }

  async function handleSendMessage(text: string) {
    if (!ride || !accessToken) return;
    setSendingMessage(true);
    try {
      const msg = await sendRideMessage(ride.ride_id, text, accessToken);
      appendMessage(msg);
    } catch {
      // Best-effort — the input keeps whatever the user typed on failure
      // is already cleared by ChatPanel, so just drop it silently; a retry
      // is as simple as typing it again.
    } finally {
      setSendingMessage(false);
    }
  }

  function handleOpenChat() {
    setChatOpen(true);
    setUnreadCount(0);
  }

  if (!loadingRide && !ride) {
    return (
      <BookingScreen
        accessToken={accessToken}
        onNeedsAuth={(pending) => {
          // Shouldn't happen behind RequireAuth, but fall back safely.
          savePendingBooking(pending);
          navigate("/login");
        }}
        onBooked={() => {
          setLoadingRide(true);
          setCashCode(null);
          getActiveRide(accessToken!)
            .then(applyRide)
            .finally(() => setLoadingRide(false));
        }}
        onLogout={logout}
      />
    );
  }

  if (loadingRide || !ride) {
    return (
      <div className="fixed inset-0 flex flex-col items-center justify-center gap-3 bg-[#20241f] text-slate-100 px-8 text-center">
        {navState?.bookedRideId && (
          <p className="text-[#1be451] text-sm">
            The request you started on the homepage has been sent, reference #{navState.bookedRideId}.
          </p>
        )}
        {navState?.bookingError && (
          <p className="text-red-400 text-sm">
            Couldn't finish the request you started on the homepage: {navState.bookingError}. Please try booking again.
          </p>
        )}
        <Loader fullScreen={false} message="Checking for an active trip" />
      </div>
    );
  }

  return (
    <ActiveRideScreen
      ride={ride}
      accessToken={accessToken}
      liveMessage={liveMessage}
      driverPosition={driverPosition}
        pickupEta={pickupEta}
      cancelling={cancelling}
      cancelError={cancelError}
      onCancel={handleCancel}
      paying={paying}
      payError={payError}
      cashCode={cashCode}
      onPay={handlePay}
      onPayCash={handlePayCash}
      disputeStatement={disputeStatement}
      onDisputeStatementChange={setDisputeStatement}
      submittingDispute={submittingDispute}
      disputeError={disputeError}
      disputeSubmitted={disputeSubmitted}
      onRespondToDispute={handleRespondToDispute}
      reportDriverReason={reportDriverReason}
      onReportDriverReasonChange={setReportDriverReason}
      reportingDriver={reportingDriver}
      reportDriverError={reportDriverError}
      reportDriverSubmitted={reportDriverSubmitted}
      onReportDriver={handleReportDriver}
      messages={messages}
      myUserId={myUserId ?? -1}
      unreadCount={unreadCount}
      chatOpen={chatOpen}
      onOpenChat={handleOpenChat}
      onCloseChat={() => setChatOpen(false)}
      sendingMessage={sendingMessage}
      onSendMessage={handleSendMessage}
      onBookAnother={() => {
        setRide(null);
        setCashCode(null);
        setLiveMessage(null);
        setDriverPosition(null);
        setReportDriverReason("");
        setReportDriverError(null);
        setReportDriverSubmitted(false);
        setMessages([]);
        setUnreadCount(0);
        setChatOpen(false);
      }}
      onLogout={logout}
    />
  );
}
