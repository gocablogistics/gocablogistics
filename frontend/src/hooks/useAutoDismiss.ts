import { useEffect, useRef } from "react";

/** Clears a transient error message a few seconds after it appears, instead
 * of leaving it on screen until the next action. Called once, right next to
 * the useState that owns the error — works regardless of whether that error
 * is rendered locally or passed down as a prop to a child component.
 *
 * Keyed only on `value` (not `clear`, which is a fresh function every render
 * in most callers) so an unrelated re-render of the owning component —
 * common here given how much of this app polls on an interval — doesn't
 * keep resetting the clock and leave the message stuck forever. */
export function useAutoDismiss(value: string | null, clear: () => void, seconds = 6) {
  const clearRef = useRef(clear);
  clearRef.current = clear;

  useEffect(() => {
    if (!value) return;
    const id = setTimeout(() => clearRef.current(), seconds * 1000);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, seconds]);
}
