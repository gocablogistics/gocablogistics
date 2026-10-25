interface BackExitHintProps {
  show: boolean;
}

// Rendered once at the App root — the "press back again to exit" nudge
// shown for a couple of seconds after the first back press on a root
// screen (see hooks/useAndroidBackHandler.ts).
export default function BackExitHint({ show }: BackExitHintProps) {
  if (!show) return null;
  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[100] px-4 py-2.5 rounded-full bg-black/80 text-white text-sm font-medium shadow-lg pointer-events-none">
      Press back again to exit
    </div>
  );
}
