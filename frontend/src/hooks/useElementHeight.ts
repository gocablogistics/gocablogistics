import { useCallback, useEffect, useRef, useState } from "react";

/** Live height of an element, rounded to 8px steps so the map isn't
 * re-framed for every pixel of a sheet animating open. Used to tell a
 * full-screen map how much of its bottom is covered by a sheet. */
export function useElementHeight<T extends HTMLElement>(): [(node: T | null) => void, number] {
  const [height, setHeight] = useState(0);
  const observerRef = useRef<ResizeObserver | null>(null);

  const ref = useCallback((node: T | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (!node) return;
    const update = () => setHeight(Math.round(node.getBoundingClientRect().height / 8) * 8);
    update();
    if (typeof ResizeObserver !== "undefined") {
      observerRef.current = new ResizeObserver(update);
      observerRef.current.observe(node);
    }
  }, []);

  useEffect(() => () => observerRef.current?.disconnect(), []);

  return [ref, height];
}
