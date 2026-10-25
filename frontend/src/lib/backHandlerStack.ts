/**
 * App-wide singleton for "what should a hardware back press close right
 * now" — chat panel, nav drawer, receipt modal, etc. are all plain
 * conditionally-rendered overlays with zero history/route representation,
 * nested arbitrarily inside whichever screen opened them. A back press
 * should close whichever one is actually on top, regardless of what
 * combination is open — a plain stack does that correctly with no need to
 * know about the overlays' identities or nesting.
 *
 * A module-level singleton, not a React Context — this has no provider/
 * re-render semantics to offer that a plain array doesn't already give for
 * free, and every consumer (useBackHandler) is already a hook.
 */
type BackHandler = () => void;

const stack: BackHandler[] = [];

export function pushBackHandler(handler: BackHandler): void {
  stack.push(handler);
}

export function removeBackHandler(handler: BackHandler): void {
  const index = stack.lastIndexOf(handler);
  if (index !== -1) stack.splice(index, 1);
}

/** Pops and calls the topmost handler. Returns false if the stack was empty,
 * so the caller knows to fall through to route-level back handling. */
export function consumeTopBackHandler(): boolean {
  const top = stack.pop();
  if (!top) return false;
  top();
  return true;
}
