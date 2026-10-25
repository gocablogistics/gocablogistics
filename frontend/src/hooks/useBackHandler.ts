import { useEffect, useRef } from "react";
import { pushBackHandler, removeBackHandler } from "../lib/backHandlerStack";

/** Registers `onBack` as the thing a hardware back press should do while
 * `active` is true (e.g. a modal/panel's own `open` prop, or just `true`
 * for something whose mount itself is the "active" signal). Call
 * unconditionally at the top of the component — it no-ops internally
 * while inactive, same reasoning as every other hook here needing to run
 * every render regardless of early-return branches below it. */
export function useBackHandler(active: boolean, onBack: () => void): void {
  const onBackRef = useRef(onBack);
  useEffect(() => {
    onBackRef.current = onBack;
  }, [onBack]);

  useEffect(() => {
    if (!active) return;
    const handler = () => onBackRef.current();
    pushBackHandler(handler);
    return () => removeBackHandler(handler);
  }, [active]);
}
