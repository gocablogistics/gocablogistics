import type { PointerEvent } from "react";

// Confirmation feedback for a handful of primary actions (book ride, accept
// ride, pay, cancel) — deliberately not wired globally onto every button, so
// it reads as deliberate confirmation (inDrive's actual pattern) rather than
// buzzing on every incidental tap. Uses the Vibration Web API directly
// rather than a native plugin round-trip: Android's WebView already exposes
// this once the VIBRATE permission is declared (see AndroidManifest.xml),
// so there's nothing a native command would add here.
export function tapHaptic(): void {
  try {
    if (typeof navigator !== "undefined" && typeof navigator.vibrate === "function") {
      navigator.vibrate(10);
    }
  } catch {
    /* best-effort — never let a missing/unsupported API break a tap */
  }
}

/** Pairs with the `.ripple-surface` CSS utility in index.css — sets the tap
 * origin as custom properties, triggers the one-shot ripple animation (runs
 * to completion on its own timeline regardless of how long the finger
 * actually stays down — a :active-driven version was nearly invisible on a
 * quick real tap, since release reverses it before the expand is visible),
 * then fires the haptic tick. Spread onto a button's `onPointerDown`:
 * `<button className="ripple-surface" onPointerDown={onPrimaryPress}>`. */
export function onPrimaryPress(e: PointerEvent<HTMLElement>): void {
  const el = e.currentTarget;
  const rect = el.getBoundingClientRect();
  el.style.setProperty("--ripple-x", `${e.clientX - rect.left}px`);
  el.style.setProperty("--ripple-y", `${e.clientY - rect.top}px`);

  // Force a reflow before re-adding the class so a rapid second tap
  // restarts the CSS animation instead of being a no-op (the browser
  // otherwise sees "class already present" and never replays it).
  el.classList.remove("rippling");
  void el.offsetWidth;
  el.classList.add("rippling");
  el.addEventListener("animationend", () => el.classList.remove("rippling"), { once: true });

  tapHaptic();
}
