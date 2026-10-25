import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { consumeTopBackHandler } from "../lib/backHandlerStack";
import { exitApp, onBackPressed } from "../lib/nativeBack";
import { useAutoDismiss } from "./useAutoDismiss";

// Deliberately NOT based on browser history depth — a logged-in rider's
// real history is "/ -> /login -> /rider", so a plain "is there history
// to go back to" check would silently kick them back to the login screen.
// These are the screens a back press should never leave via navigate(-1);
// it should ask for exit confirmation instead.
const ROOT_PATHS = new Set(["/", "/login", "/signup", "/rider", "/driver"]);

/** Wires the hardware back button to: close the topmost open overlay (chat/
 * drawer/receipt) if any, else navigate back on a nested route, else ask for
 * "press back again to exit" on a root screen. Call once, inside the Router. */
export function useAndroidBackHandler(): { showExitHint: boolean } {
  const location = useLocation();
  const navigate = useNavigate();
  const [showExitHint, setShowExitHint] = useState(false);

  const locationRef = useRef(location);
  const exitHintRef = useRef(showExitHint);
  useEffect(() => {
    locationRef.current = location;
    exitHintRef.current = showExitHint;
  }, [location, showExitHint]);

  useAutoDismiss(showExitHint ? "show" : null, () => setShowExitHint(false), 2);

  useEffect(() => {
    let unlisten: (() => void) | null = null;
    onBackPressed(() => {
      if (consumeTopBackHandler()) return;

      const isRoot = ROOT_PATHS.has(locationRef.current.pathname);
      if (!isRoot) {
        navigate(-1);
        return;
      }
      if (exitHintRef.current) {
        exitApp();
      } else {
        setShowExitHint(true);
      }
    }).then((fn) => {
      unlisten = fn;
    });
    return () => unlisten?.();
  }, [navigate]);

  return { showExitHint };
}
