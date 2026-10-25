import { flushSync } from "react-dom";

/**
 * react-router-dom v7's own `viewTransition` option on navigate()/<Link>
 * only works in Framework/Data router modes (createBrowserRouter) —
 * confirmed by reading its type definitions directly. This app uses plain
 * declarative <BrowserRouter><Routes>, so that flag is unavailable here;
 * migrating router modes just to unlock it would be a bigger, riskier
 * change than this feature justifies. The underlying browser API doesn't
 * care about react-router at all though — it only needs the DOM mutation
 * to happen synchronously inside its callback, which `flushSync` gives a
 * plain `navigate()`/`setState()` call just as well.
 *
 * Feature-detected, not version-sniffed — degrades to an instant cut on
 * WebViews too old to support it, and the browser itself already skips
 * the transition under prefers-reduced-motion, so nothing extra is needed
 * here for that.
 */
export function withViewTransition(fn: () => void): void {
  if (typeof document.startViewTransition !== "function") {
    fn();
    return;
  }
  document.startViewTransition(() => flushSync(fn));
}
