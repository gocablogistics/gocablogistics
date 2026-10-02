import { useRef, useState } from "react";

interface SlideToContinueProps {
  label: string;
  successLabel: string;
  onComplete: () => void;
}

export default function SlideToContinue({ label, successLabel, onComplete }: SlideToContinueProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const knobRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);
  const startXRef = useRef(0);
  const maxTranslateRef = useRef(0);

  const [translateX, setTranslateX] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [succeeded, setSucceeded] = useState(false);

  function handlePointerDown(e: React.PointerEvent) {
    if (succeeded) return;
    const track = trackRef.current;
    const knob = knobRef.current;
    if (!track || !knob) return;
    maxTranslateRef.current = track.offsetWidth - knob.offsetWidth - 12;
    draggingRef.current = true;
    startXRef.current = e.clientX;
    setDragging(true);
    (e.target as Element).setPointerCapture(e.pointerId);
  }

  function handlePointerMove(e: React.PointerEvent) {
    if (!draggingRef.current) return;
    const walk = e.clientX - startXRef.current;
    const clamped = Math.max(0, Math.min(walk, maxTranslateRef.current));
    setTranslateX(clamped);
  }

  function finishDrag() {
    if (!draggingRef.current) return;
    draggingRef.current = false;
    setDragging(false);

    if (translateX > maxTranslateRef.current * 0.65) {
      setTranslateX(maxTranslateRef.current);
      setSucceeded(true);
      window.setTimeout(onComplete, 500);
    } else {
      setTranslateX(0);
    }
  }

  const progress = maxTranslateRef.current > 0 ? translateX / maxTranslateRef.current : 0;

  return (
    <div
      ref={trackRef}
      className="relative w-full h-[62px] bg-white rounded-full p-1.5 flex items-center justify-between select-none shadow-xl"
    >
      <div
        ref={knobRef}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={finishDrag}
        onPointerCancel={finishDrag}
        className="h-full bg-black text-white px-7 rounded-full flex items-center justify-center font-semibold text-sm z-10 shadow-md cursor-grab active:cursor-grabbing touch-none"
        style={{
          transform: `translateX(${translateX}px)`,
          transition: dragging ? "none" : "transform 0.3s ease",
        }}
      >
        <span>{label}</span>
      </div>

      <div
        className="flex items-center space-x-2 pr-6 text-neutral-800 font-medium italic text-sm"
        style={{ opacity: 1 - progress, transition: dragging ? "none" : "opacity 0.3s ease" }}
      >
        <span>Slide</span>
        <i className="fa-solid fa-arrow-right text-xs" />
      </div>

      <div
        className="absolute inset-0 bg-[#1be451] rounded-full flex items-center justify-center font-bold text-neutral-900 text-base pointer-events-none transition-opacity duration-300"
        style={{ opacity: succeeded ? 1 : 0 }}
      >
        <span>{successLabel}</span>
      </div>
    </div>
  );
}
