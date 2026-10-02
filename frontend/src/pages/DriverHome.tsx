import { useEffect, useRef, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { ApiError, API_BASE_URL } from "../api/http";
import { useAutoDismiss } from "../hooks/useAutoDismiss";
import { getCurrentPosition } from "../lib/geolocation";
import {
  startLocationTracking,
  stopLocationTracking,
  updateLocationToken,
} from "../lib/nativeLocation";
import Loader from "../components/Loader";
import DriverBrowseScreen from "../components/DriverBrowseScreen";
import DriverActiveRideScreen from "../components/DriverActiveRideScreen";
import {
  acceptRide,
  completeTrip,
  confirmCash,
  driverCancelRide,
  getAvailability,
  getDriverActiveRide,
  getDriverPayouts,
  getDriverSummary,
  getNearbyRides,
  getRideMessages,
  reportNonPayment,
  rideUpdatesSocketUrl,
  sendRideMessage,
  setAvailability,
  startTrip,
  updateDriverLocation,
  type AvailabilityOut,
  type DriverActiveRideOut,
  type DriverSummaryOut,
  type NearbyRideOut,
  type PayoutOut,
  type RideMessageOut,
} from "../api/rides";

const NEARBY_POLL_MS = 5000;
const LOCATION_PING_MS = 15000;
const RECONNECT_DELAY_MS = 2000;

export default function DriverHome() {
  const { user, myUserId, accessToken, logout } = useAuth();

  const [availability, setAvailabilityState] = useState<AvailabilityOut | null>(null);
  const [activeRide, setActiveRide] = useState<DriverActiveRideOut | null>(null);
  const [nearbyRides, setNearbyRides] = useState<NearbyRideOut[]>([]);
  const [summary, setSummary] = useState<DriverSummaryOut | null>(null);
  const [payouts, setPayouts] = useState<PayoutOut[]>([]);
  const [driverPosition, setDriverPosition] = useState<{ lat: number; lng: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState(false);
  const [toggleError, setToggleError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actingOn, setActingOn] = useState<number | null>(null);
  const [cashCodeInput, setCashCodeInput] = useState("");
  const [confirmingCash, setConfirmingCash] = useState(false);
  const [cashError, setCashError] = useState<string | null>(null);
  const [reporting, setReporting] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  const [reportReason, setReportReason] = useState("");
  const [messages, setMessages] = useState<RideMessageOut[]>([]);
  const [chatOpen, setChatOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [sendingMessage, setSendingMessage] = useState(false);
  const chatOpenRef = useRef(chatOpen);
  chatOpenRef.current = chatOpen;

  useAutoDismiss(toggleError, () => setToggleError(null));
  useAutoDismiss(actionError, () => setActionError(null));
  useAutoDismiss(cashError, () => setCashError(null));
  useAutoDismiss(reportError, () => setReportError(null));

  function appendMessage(msg: RideMessageOut) {
    setMessages((prev) => (prev.some((m) => m.id === msg.id) ? prev : [...prev, msg]));
  }

  async function refreshAll() {
    if (!accessToken) return;
    const [avail, summ, payoutList] = await Promise.all([
      getAvailability(accessToken),
      getDriverSummary(accessToken),
      getDriverPayouts(accessToken),
    ]);
    setAvailabilityState(avail);
    setSummary(summ);
    setPayouts(payoutList);
    try {
      const ride = await getDriverActiveRide(accessToken);
      setActiveRide(ride);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) throw err;
      setActiveRide(null);
    }
  }

  // Only the first load of a login session should block the screen behind
  // a full-page spinner — accessToken also changes every ~20 min when
  // AuthContext silently rotates it, and without this guard that would
  // unmount the entire active-ride screen (map, chat, complete/cancel
  // buttons) mid-trip every time. Reset on logout so a fresh login still
  // loads normally.
  const hasLoadedDashboardRef = useRef(false);
  useEffect(() => {
    if (!accessToken) {
      hasLoadedDashboardRef.current = false;
      return;
    }
    if (hasLoadedDashboardRef.current) return;
    hasLoadedDashboardRef.current = true;
    setLoading(true);
    refreshAll()
      .catch((err) => console.error("Failed to load driver dashboard", err))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken]);

  // Poll for nearby rides while online and not on a trip.
  useEffect(() => {
    if (!accessToken || !availability?.is_online || activeRide) {
      setNearbyRides([]);
      return;
    }
    let cancelled = false;
    const poll = () => {
      getNearbyRides(accessToken)
        .then((rides) => {
          if (!cancelled) setNearbyRides(rides);
        })
        .catch(() => {});
    };
    poll();
    const id = setInterval(poll, NEARBY_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [accessToken, availability?.is_online, activeRide]);

  // Poll for payment-status changes on a completed, unpaid ride — the
  // driver's screen has no other way to learn the rider just switched to
  // cash (generating a code) or paid online, since neither triggers a push
  // to the driver dashboard.
  useEffect(() => {
    if (!accessToken || !activeRide) return;
    if (activeRide.status !== "completed" || activeRide.payment_status === "paid") return;

    let cancelled = false;
    const poll = () => {
      getDriverActiveRide(accessToken)
        .then((ride) => {
          if (!cancelled) setActiveRide(ride);
        })
        .catch((err) => {
          if (!cancelled && err instanceof ApiError && err.status === 404) {
            setActiveRide(null);
          }
        });
    };
    const id = setInterval(poll, NEARBY_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [accessToken, activeRide?.ride_id, activeRide?.status, activeRide?.payment_status]);

  // Poll for the rider's position pre-pickup — the dashboard has no live
  // socket connection to push this, so it's picked up the same way the
  // payment-status poll above works: re-fetch the active ride periodically.
  useEffect(() => {
    if (!accessToken || !activeRide || activeRide.status !== "accepted") return;

    let cancelled = false;
    const poll = () => {
      getDriverActiveRide(accessToken)
        .then((ride) => {
          if (!cancelled) setActiveRide(ride);
        })
        .catch((err) => {
          // The rider can cancel while the driver is still "accepted" and
          // en route — a bare swallow here (as this used to be) left the
          // dashboard stuck showing a ride that's actually gone, since
          // getDriverActiveRide 404s once it no longer matches any active
          // criteria for this driver. Clear it the same way every other
          // poll in this file already does.
          if (!cancelled && err instanceof ApiError && err.status === 404) {
            setActiveRide(null);
          }
        });
    };
    const id = setInterval(poll, NEARBY_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [accessToken, activeRide?.ride_id, activeRide?.status]);

  // Fetch chat history whenever the active ride changes (including a fresh
  // one starting), and drop any stale unread/open state from a previous trip.
  useEffect(() => {
    if (!accessToken || !activeRide) return;
    let cancelled = false;
    getRideMessages(activeRide.ride_id, accessToken)
      .then((msgs) => {
        if (cancelled) return;
        setMessages(msgs);
        setUnreadCount(0);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken, activeRide?.ride_id]);

  // Live chat delivery — the driver dashboard otherwise has no websocket
  // connection at all (everything else here is REST polling), but chat
  // needs a real push rather than a 5s-latency poll. Subscribes to the same
  // ride_{id} group the rider's socket already uses (RideUpdatesConsumer is
  // now shared by both sides, authorized per-ride — see consumers.py).
  useEffect(() => {
    if (!accessToken || !activeRide) return;
    if (activeRide.status !== "accepted" && activeRide.status !== "started") return;

    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    const rideId = activeRide.ride_id;

    function connect() {
      if (cancelled) return;
      socket = new WebSocket(rideUpdatesSocketUrl(accessToken!));
      socket.onopen = () => {
        socket!.send(JSON.stringify({ action: "subscribe", ride_id: rideId }));
      };
      socket.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "chat_message") {
          appendMessage(msg as RideMessageOut);
          if (!chatOpenRef.current) setUnreadCount((n) => n + 1);
        }
      };
      socket.onclose = () => {
        if (cancelled) return;
        reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [accessToken, activeRide?.ride_id, activeRide?.status]);

  // Ping location periodically while online.
  useEffect(() => {
    if (!accessToken || !availability?.is_online) return;
    const ping = () => {
      getCurrentPosition(
        (coords) => {
          setDriverPosition({ lat: coords.latitude, lng: coords.longitude });
          updateDriverLocation(coords.latitude, coords.longitude, accessToken).catch(() => {});
        },
        () => {},
      );
    };
    ping();
    const id = setInterval(ping, LOCATION_PING_MS);
    return () => clearInterval(id);
  }, [accessToken, availability?.is_online]);

  // Native background tracking (Android only, no-op elsewhere) — the ping
  // effect above only runs while the WebView is alive, which Android
  // suspends once the app is backgrounded. This keeps location posting
  // through GocabLocationService independent of that. Some redundant posts
  // happen while the app is foregrounded (both this and the JS ping fire),
  // which is harmless — not worth the complexity of deduping across the
  // native/JS boundary right now.
  const wasOnlineRef = useRef(false);
  useEffect(() => {
    if (!accessToken) return;
    if (availability?.is_online) {
      if (!wasOnlineRef.current) {
        startLocationTracking(API_BASE_URL, accessToken).catch(() => {});
      } else {
        updateLocationToken(accessToken).catch(() => {});
      }
      wasOnlineRef.current = true;
    } else if (wasOnlineRef.current) {
      stopLocationTracking().catch(() => {});
      wasOnlineRef.current = false;
    }
  }, [accessToken, availability?.is_online]);

  useEffect(() => {
    return () => {
      stopLocationTracking().catch(() => {});
    };
  }, []);

  async function handleToggleOnline() {
    if (!accessToken || !availability) return;
    setToggling(true);
    setToggleError(null);
    try {
      const updated = await setAvailability(!availability.is_online, accessToken);
      setAvailabilityState(updated);
    } catch (err) {
      setToggleError(err instanceof ApiError ? err.message : "Failed to update availability");
    } finally {
      setToggling(false);
    }
  }

  async function handleAccept(rideId: number) {
    if (!accessToken) return;
    setActingOn(rideId);
    setActionError(null);
    try {
      await acceptRide(rideId, accessToken);
      await refreshAll();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not accept ride.");
    } finally {
      setActingOn(null);
    }
  }

  async function handleStart() {
    if (!accessToken || !activeRide) return;
    setActingOn(activeRide.ride_id);
    setActionError(null);
    try {
      await startTrip(activeRide.ride_id, accessToken);
      await refreshAll();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not start trip.");
    } finally {
      setActingOn(null);
    }
  }

  async function handleComplete() {
    if (!accessToken || !activeRide) return;
    setActingOn(activeRide.ride_id);
    setActionError(null);
    try {
      await completeTrip(activeRide.ride_id, accessToken);
      await refreshAll();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not complete trip.");
    } finally {
      setActingOn(null);
    }
  }

  async function handleConfirmCash() {
    if (!accessToken || !activeRide) return;
    setConfirmingCash(true);
    setCashError(null);
    try {
      await confirmCash(activeRide.ride_id, cashCodeInput.trim(), accessToken);
      setCashCodeInput("");
      // Don't refreshAll() here — the driver/rider "active ride" queries
      // only match unpaid completed rides, so an immediate re-fetch would
      // make this ride vanish before the driver ever sees "Paid". Update
      // in place instead; the "Done" button below moves on when they're
      // ready, via the same refreshAll() every other action already uses.
      setActiveRide((prev) => (prev ? { ...prev, payment_status: "paid" } : prev));
      getDriverSummary(accessToken).then(setSummary).catch(() => {});
    } catch (err) {
      setCashError(err instanceof ApiError ? err.message : "Could not confirm payment.");
    } finally {
      setConfirmingCash(false);
    }
  }

  async function handleReportNonPayment() {
    if (!accessToken || !activeRide) return;
    setReporting(true);
    setReportError(null);
    try {
      await reportNonPayment(activeRide.ride_id, accessToken, reportReason.trim());
      setReportReason("");
      // Same reasoning as handleConfirmCash — update in place rather than
      // refreshAll(), so the driver sees the "Reported" state instead of
      // the ride just vanishing.
      setActiveRide((prev) => (prev ? { ...prev, payment_status: "reported" } : prev));
    } catch (err) {
      setReportError(err instanceof ApiError ? err.message : "Could not report non-payment.");
    } finally {
      setReporting(false);
    }
  }

  async function handleSendMessage(text: string) {
    if (!accessToken || !activeRide) return;
    setSendingMessage(true);
    try {
      const msg = await sendRideMessage(activeRide.ride_id, text, accessToken);
      appendMessage(msg);
    } catch {
      // Best-effort — see RiderHome's identical handler for why this is a
      // silent no-op rather than surfacing an error for a single message.
    } finally {
      setSendingMessage(false);
    }
  }

  function handleOpenChat() {
    setChatOpen(true);
    setUnreadCount(0);
  }

  async function handleDriverCancel() {
    if (!accessToken || !activeRide) return;
    setActingOn(activeRide.ride_id);
    setActionError(null);
    try {
      await driverCancelRide(activeRide.ride_id, accessToken);
      await refreshAll();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not cancel trip.");
    } finally {
      setActingOn(null);
    }
  }

  if (user && user.is_approved === false) {
    return (
      <div className="fixed inset-0 flex flex-col items-center justify-center gap-4 bg-[#20241f] text-slate-100 px-8 text-center">
        <h1 className="text-white text-2xl font-extrabold">Pending approval</h1>
        <p className="text-slate-400">Your driver account is still awaiting admin approval.</p>
        <button
          onClick={logout}
          className="py-3 px-8 rounded-full bg-white/10 border border-white/20 text-white font-semibold"
        >
          Log out
        </button>
      </div>
    );
  }

  if (loading) {
    return <Loader message="Getting your dashboard ready" />;
  }

  if (activeRide) {
    return (
      <DriverActiveRideScreen
        ride={activeRide}
        accessToken={accessToken}
        driverPosition={driverPosition}
        actingOn={actingOn}
        actionError={actionError}
        onStart={handleStart}
        onComplete={handleComplete}
        onDriverCancel={handleDriverCancel}
        cashCodeInput={cashCodeInput}
        onCashCodeChange={setCashCodeInput}
        confirmingCash={confirmingCash}
        cashError={cashError}
        onConfirmCash={handleConfirmCash}
        reportReason={reportReason}
        onReportReasonChange={setReportReason}
        reporting={reporting}
        reportError={reportError}
        onReportNonPayment={handleReportNonPayment}
        messages={messages}
        myUserId={myUserId ?? -1}
        unreadCount={unreadCount}
        chatOpen={chatOpen}
        onOpenChat={handleOpenChat}
        onCloseChat={() => setChatOpen(false)}
        sendingMessage={sendingMessage}
        onSendMessage={handleSendMessage}
        onDone={() => {
          setMessages([]);
          setUnreadCount(0);
          setChatOpen(false);
          refreshAll();
        }}
        onLogout={logout}
      />
    );
  }

  return (
    <DriverBrowseScreen
      accessToken={accessToken}
      driverPosition={driverPosition}
      availability={availability}
      summary={summary}
      payouts={payouts}
      nearbyRides={nearbyRides}
      toggling={toggling}
      toggleError={toggleError}
      onToggleOnline={handleToggleOnline}
      actingOn={actingOn}
      actionError={actionError}
      onAccept={handleAccept}
      onLogout={logout}
    />
  );
}
