import { useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import RequireAuth from "./auth/RequireAuth";
import Home from "./pages/Home";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import RiderHome from "./pages/RiderHome";
import DriverHome from "./pages/DriverHome";
import PaymentCallback from "./pages/PaymentCallback";
import Track from "./pages/Track";
import RideHistory from "./pages/RideHistory";
import Referrals from "./pages/Referrals";
import Profile from "./pages/Profile";
import Support from "./pages/Support";
import Balance from "./pages/Balance";
import PrivacyPolicy from "./pages/PrivacyPolicy";
import TermsAndConditions from "./pages/TermsAndConditions";
import Loader from "./components/Loader";

// First-open launch screen: the very first time the app is opened — before
// anyone has signed up — it starts on the branded loader for a moment instead of
// dropping straight onto the home page. Never again after that: the flag below
// is set once it has played, and anyone who is already signed in skips it too.
const LAUNCH_SEEN_KEY = "gocab_launch_seen";
const LAUNCH_SCREEN_MIN_MS = 1800;

function shouldShowLaunchScreen(): boolean {
  try {
    // Dev only: /?splash replays it, since the flag hides it after one view.
    if (import.meta.env.DEV && new URLSearchParams(window.location.search).has("splash")) {
      return true;
    }
    if (localStorage.getItem(LAUNCH_SEEN_KEY) === "1") return false;
    if (localStorage.getItem("gocab_refresh_token")) return false;
    return true;
  } catch {
    // Storage unavailable — skip it rather than replaying on every open.
    return false;
  }
}

function LaunchScreen({ children }: { children: ReactNode }) {
  const { loading } = useAuth();
  const [show] = useState(shouldShowLaunchScreen);
  const [minTimeDone, setMinTimeDone] = useState(!show);

  useEffect(() => {
    if (!show) return;
    const t = setTimeout(() => {
      try {
        localStorage.setItem(LAUNCH_SEEN_KEY, "1");
      } catch {
        /* best-effort */
      }
      setMinTimeDone(true);
    }, LAUNCH_SCREEN_MIN_MS);
    return () => clearTimeout(t);
  }, [show]);

  if (show && (loading || !minTimeDone)) return <Loader immediate />;
  return <>{children}</>;
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <LaunchScreen>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<Login />} />
          {/* Dev only (import.meta.env.DEV is false in production builds): a
              permanent way to look at the loader without waiting for a real load. */}
          {import.meta.env.DEV && (
            <Route path="/loader-preview" element={<Loader message="Checking for an active trip" />} />
          )}
          <Route path="/signup" element={<Signup />} />
          <Route path="/privacy" element={<PrivacyPolicy />} />
          <Route path="/terms" element={<TermsAndConditions />} />
          <Route
            path="/rider"
            element={
              <RequireAuth role="rider">
                <RiderHome />
              </RequireAuth>
            }
          />
          <Route
            path="/driver"
            element={
              <RequireAuth role="driver">
                <DriverHome />
              </RequireAuth>
            }
          />
          <Route
            path="/payment-callback"
            element={<PaymentCallback />}
          />
          <Route path="/track/:token" element={<Track />} />
          <Route
            path="/rider/history"
            element={
              <RequireAuth role="rider">
                <RideHistory />
              </RequireAuth>
            }
          />
          <Route
            path="/rider/referrals"
            element={
              <RequireAuth role="rider">
                <Referrals />
              </RequireAuth>
            }
          />
          <Route
            path="/rider/profile"
            element={
              <RequireAuth role="rider">
                <Profile />
              </RequireAuth>
            }
          />
          <Route
            path="/rider/support"
            element={
              <RequireAuth role="rider">
                <Support />
              </RequireAuth>
            }
          />
          <Route
            path="/driver/history"
            element={
              <RequireAuth role="driver">
                <RideHistory />
              </RequireAuth>
            }
          />
          <Route
            path="/driver/profile"
            element={
              <RequireAuth role="driver">
                <Profile />
              </RequireAuth>
            }
          />
          <Route
            path="/driver/balance"
            element={
              <RequireAuth role="driver">
                <Balance />
              </RequireAuth>
            }
          />
          <Route
            path="/driver/support"
            element={
              <RequireAuth role="driver">
                <Support />
              </RequireAuth>
            }
          />
          {/* No matching route (e.g. a stale bundle navigating to a path
              added after it loaded) would otherwise render nothing at all —
              send it somewhere real instead of a blank screen. */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        </LaunchScreen>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
