import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  logout as apiLogout,
  me,
  refreshTokenPair,
  type TokenPairOut,
  type UserOut,
} from "../api/auth";
import { ApiError } from "../api/http";
import { registerDevice } from "../api/notifications";
import { getFcmToken, onTokenRefresh, requestNotificationPermission } from "../lib/nativePush";
import { decodeAccessTokenUserId } from "../lib/jwt";

const REFRESH_STORAGE_KEY = "gocab_refresh_token";
// Access tokens live 30 minutes server-side (NINJA_JWT.ACCESS_TOKEN_LIFETIME)
// — refresh comfortably before that so a long-lived session (e.g. a driver
// staying online for hours, polling every few seconds) never silently starts
// getting 401s.
const REFRESH_INTERVAL_MS = 20 * 60 * 1000;

interface AuthContextValue {
  user: UserOut | null;
  /** Who the *current* accessToken actually authenticates as — decoded
   * from the token itself rather than taken from the separately-fetched
   * `user` object. Two reasons this has to be token-first, not just a
   * fallback for when user is null: (1) the one-off /auth/me fetch can
   * fail on a flaky connection and nothing ever retries it in time, and
   * (2) on a device that's logged in/out of more than one account in a
   * session, a slow in-flight /auth/me from the PREVIOUS login can resolve
   * after setSession() already set a fresh user for the new one, silently
   * overwriting it with the wrong id — user would be non-null but wrong,
   * so a null check alone wouldn't catch it. The token can't go stale like
   * that: it's the same value used for every request's Authorization
   * header, so decoding it is always consistent with who the server
   * thinks made the request. Chat's "is this message mine" check uses
   * this, not user?.id. */
  myUserId: number | null;
  accessToken: string | null;
  loading: boolean;
  setSession: (tokens: TokenPairOut) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const myUserId = decodeAccessTokenUserId(accessToken) ?? user?.id ?? null;

  useEffect(() => {
    const storedRefresh = localStorage.getItem(REFRESH_STORAGE_KEY);
    if (!storedRefresh) {
      setLoading(false);
      return;
    }

    refreshTokenPair(storedRefresh)
      .then(async (tokens) => {
        localStorage.setItem(REFRESH_STORAGE_KEY, tokens.refresh);
        setAccessToken(tokens.access);
        const profile = await me(tokens.access);
        setUser(profile);
      })
      .catch((err) => {
        // Only a genuine "this refresh token is invalid/expired" response
        // should sign the user out — a network error here (offline at cold
        // boot, dead zone, etc.) shouldn't discard an otherwise-valid
        // stored session. Note this also covers a failed `me()` call inside
        // the .then above (a network blip on that specific request) — user
        // profile fields (name/phone/email/role) would be left unset by
        // that, which the self-heal effect below retries.
        if (err instanceof ApiError) {
          localStorage.removeItem(REFRESH_STORAGE_KEY);
        }
      })
      .finally(() => setLoading(false));
  }, []);

  // Self-heals a `user` stuck null after the boot fetch above (or the login
  // response) if the one-off /auth/me call ever failed on a flaky network —
  // otherwise nothing ever retries it and every user?.-keyed bit of UI
  // (profile page, chat's "is this mine" check before myUserId existed,
  // driver/rider role routing) stays silently broken for the rest of the
  // session. Retries roughly every 20s while accessToken is set but user
  // isn't yet, and stops on its own once it succeeds.
  useEffect(() => {
    if (!accessToken || user) return;
    let cancelled = false;
    const attempt = () => {
      me(accessToken)
        .then((profile) => {
          if (!cancelled) setUser(profile);
        })
        .catch(() => {
          /* will retry on the next tick below */
        });
    };
    attempt();
    const id = setInterval(attempt, 20_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [accessToken, user]);

  useEffect(() => {
    if (!accessToken) return;

    const id = setInterval(() => {
      const storedRefresh = localStorage.getItem(REFRESH_STORAGE_KEY);
      if (!storedRefresh) return;
      refreshTokenPair(storedRefresh)
        .then((tokens) => {
          localStorage.setItem(REFRESH_STORAGE_KEY, tokens.refresh);
          setAccessToken(tokens.access);
        })
        .catch((err) => {
          // Only clear the session on a genuine "invalid/expired" response
          // from the server — a network blip (elevator, dead zone, spotty
          // mobile data) mid-shift shouldn't log a driver out of an active
          // ride over a dropped connection. The next scheduled refresh will
          // just retry.
          if (err instanceof ApiError) {
            localStorage.removeItem(REFRESH_STORAGE_KEY);
            setAccessToken(null);
            setUser(null);
          }
        });
    }, REFRESH_INTERVAL_MS);

    return () => clearInterval(id);
  }, [accessToken]);

  // Register/refresh this device's FCM token with the backend — a no-op on
  // desktop/web (getFcmToken resolves null there, see lib/nativePush).
  useEffect(() => {
    if (!accessToken) return;

    let cancelled = false;
    let unlisten: (() => void) | null = null;

    requestNotificationPermission()
      .then(() => getFcmToken())
      .then((token) => {
        if (token) registerDevice(token, accessToken).catch(() => {});
      });

    onTokenRefresh((token) => {
      registerDevice(token, accessToken).catch(() => {});
    }).then((fn) => {
      if (cancelled) fn?.();
      else unlisten = fn;
    });

    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [accessToken]);

  function setSession(tokens: TokenPairOut) {
    localStorage.setItem(REFRESH_STORAGE_KEY, tokens.refresh);
    setAccessToken(tokens.access);
    setUser(tokens.user);
  }

  async function logout() {
    // Navigate first, before any state clears or awaited calls — if the
    // clear-state-then-navigate order is used instead, there's a window
    // where user/token are already null but the route hasn't changed yet,
    // and RequireAuth (still mounted on the old protected route) can
    // re-render against that null user and redirect to /login itself,
    // racing the intended navigate("/") here. Changing the route first
    // unmounts RequireAuth immediately, so it never gets that chance.
    navigate("/", { replace: true });
    const storedRefresh = localStorage.getItem(REFRESH_STORAGE_KEY);
    if (storedRefresh) {
      try {
        await apiLogout(storedRefresh);
      } catch {
        // Logout is best-effort — clear local state regardless.
      }
    }
    localStorage.removeItem(REFRESH_STORAGE_KEY);
    setAccessToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider
      value={{ user, myUserId, accessToken, loading, setSession, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
