import { useEffect, useRef, useState } from "react";

/**
 * Solves the two classic timing problems of a CSS-only enter/exit
 * transition on a conditionally-rendered overlay (chat panel, nav drawer,
 * receipt modal), with no animation library installed:
 *
 *  - Exit: the element must stay mounted for `durationMs` after `mounted`
 *    flips false, long enough for its CSS transition to actually play,
 *    instead of disappearing instantly.
 *  - Enter: the very first paint after mounting must happen in the
 *    "closed" position, with a second paint one frame later flipping to
 *    "open" — otherwise the browser has only one style to show and there's
 *    nothing to interpolate from, so the enter transition never plays.
 *
 * Usage: a wrapper div's class is driven by the returned `isOpen` (not the
 * `mounted` prop directly), e.g. `isOpen ? "translate-x-0" : "translate-x-full"`,
 * and the component's own early-return/conditional render is gated on
 * `shouldRender`.
 */
export function useMountTransition(
  mounted: boolean,
  durationMs: number,
): { shouldRender: boolean; isOpen: boolean } {
  const [shouldRender, setShouldRender] = useState(mounted);
  const [isOpen, setIsOpen] = useState(false);
  const frameRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (mounted) {
      setShouldRender(true);
      // Start closed, then flip open one frame later so there's an actual
      // state change for the CSS transition to animate between.
      setIsOpen(false);
      frameRef.current = requestAnimationFrame(() => setIsOpen(true));
      return () => {
        if (frameRef.current) cancelAnimationFrame(frameRef.current);
      };
    }

    setIsOpen(false);
    const timeout = setTimeout(() => setShouldRender(false), durationMs);
    return () => clearTimeout(timeout);
  }, [mounted, durationMs]);

  return { shouldRender, isOpen };
}
