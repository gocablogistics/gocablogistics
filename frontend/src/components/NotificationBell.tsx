import { useEffect, useRef, useState } from "react";
import {
  getNotificationCount,
  getNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  notificationsSocketUrl,
  type NotificationOut,
} from "../api/notifications";

const RECONNECT_DELAY_MS = 2000;
const POLL_FALLBACK_MS = 20000;

/** Short two-tone beep synthesized via the Web Audio API — no external
 * audio file/asset to ship or fail to load. Safe to call from anywhere;
 * silently no-ops if the browser blocks it (e.g. no user gesture yet). */
function playChime() {
  try {
    const Ctx = window.AudioContext || (window as any).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    [880, 1175].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      const start = ctx.currentTime + i * 0.09;
      gain.gain.setValueAtTime(0, start);
      gain.gain.linearRampToValueAtTime(0.15, start + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.001, start + 0.16);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(start);
      osc.stop(start + 0.18);
    });
    setTimeout(() => ctx.close(), 500);
  } catch {
    // Autoplay policy or unsupported browser — a missed chime isn't worth
    // surfacing an error over, the badge count still updates.
  }
}

export default function NotificationBell({ accessToken }: { accessToken: string }) {
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationOut[]>([]);
  const countRef = useRef(0);
  const firstCountRef = useRef(true);

  function applyCount(next: number) {
    if (!firstCountRef.current && next > countRef.current) {
      playChime();
    }
    firstCountRef.current = false;
    countRef.current = next;
    setCount(next);
  }

  useEffect(() => {
    getNotificationCount(accessToken).then((r) => applyCount(r.count)).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken]);

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      if (cancelled) return;
      socket = new WebSocket(notificationsSocketUrl(accessToken));
      socket.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "counter") applyCount(msg.count);
      };
      socket.onclose = () => {
        if (cancelled) return;
        reconnectTimer = setTimeout(() => {
          getNotificationCount(accessToken).then((r) => applyCount(r.count)).catch(() => {});
          connect();
        }, RECONNECT_DELAY_MS);
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken]);

  // Fallback safety net independent of the socket, same pattern as the
  // rider's ride-status poll — a dropped/never-reconnected socket still
  // can't leave the badge stuck stale for more than a few seconds.
  useEffect(() => {
    const id = setInterval(() => {
      getNotificationCount(accessToken).then((r) => applyCount(r.count)).catch(() => {});
    }, POLL_FALLBACK_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken]);

  function toggleOpen() {
    const next = !open;
    setOpen(next);
    if (next) {
      getNotifications(accessToken).then(setNotifications).catch(() => {});
    }
  }

  async function handleMarkRead(id: number) {
    const result = await markNotificationRead(id, accessToken);
    countRef.current = result.count;
    setCount(result.count);
    setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, is_active: false } : n)));
  }

  async function handleMarkAllRead() {
    const result = await markAllNotificationsRead(accessToken);
    countRef.current = result.count;
    setCount(result.count);
    setNotifications((prev) => prev.map((n) => ({ ...n, is_active: false })));
  }

  return (
    <div className="relative inline-block">
      <button onClick={toggleOpen} className="relative p-1 text-inherit" aria-label="Notifications">
        <i className="fa-solid fa-bell text-lg" />
        {count > 0 && (
          <span className="absolute -top-1 -right-1 bg-red-500 text-white rounded-full text-[10px] font-bold min-w-[15px] h-[15px] flex items-center justify-center px-1 leading-none">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-2 w-72 max-h-80 overflow-y-auto rounded-2xl bg-[#181c17] border border-white/10 shadow-xl p-2 z-20 text-slate-100">
            {notifications.length === 0 ? (
              <p className="text-slate-400 text-sm p-3">No notifications yet.</p>
            ) : (
              <>
                {count > 0 && (
                  <button
                    onClick={handleMarkAllRead}
                    className="w-full text-left text-[#1be451] text-xs font-semibold px-2 py-2"
                  >
                    Mark all as read
                  </button>
                )}
                {notifications.map((n) => (
                  <div
                    key={n.id}
                    onClick={() => n.is_active && handleMarkRead(n.id)}
                    className={`px-3 py-2.5 mb-1 rounded-xl text-sm ${
                      n.is_active ? "bg-white/10 cursor-pointer" : "bg-transparent"
                    }`}
                  >
                    <p className="m-0 text-slate-100">{n.message}</p>
                    <p className="m-0 text-slate-400 text-xs mt-0.5">
                      {new Date(n.created_at).toLocaleString()}
                    </p>
                  </div>
                ))}
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
