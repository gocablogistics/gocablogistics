interface LoaderProps {
  /** Short line under the logo, e.g. "Checking for an active trip". */
  message?: string;
  /** Covers the whole screen (default). Turn off to sit inside a page. */
  fullScreen?: boolean;
  /** Smaller mark, for inline spots such as a list that's still loading. */
  compact?: boolean;
  /** Skip the short fade-in delay — used for the launch screen, which must
   * follow the static startup loader with no blank gap in between. */
  immediate?: boolean;
}

/**
 * GoCab's loading state: the pin logo with a soft location-style ripple, an
 * animated status line and a slim progress bar. Styles live in index.css
 * (`gc-*`); they fade in after a short delay so a load that finishes in a
 * blink never flashes the loader at all, and they switch off animation when
 * the device asks for reduced motion.
 */
export default function Loader({
  message,
  fullScreen = true,
  compact = false,
  immediate = false,
}: LoaderProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={
        `${immediate ? "gc-loader-now " : ""}${fullScreen
          ? "gc-loader-screen fixed inset-0 z-50 flex flex-col items-center justify-center gap-7 bg-[#20241f] px-8"
          : "gc-loader-screen flex flex-col items-center justify-center gap-5 py-10"}`
      }
    >
      <div className={`gc-loader-mark${compact ? " gc-loader-mark-sm" : ""}`} aria-hidden="true">
        <span className="gc-loader-ring" />
        <span className="gc-loader-ring gc-loader-ring-late" />
        <img src="/gocab-logo.png" alt="" className="gc-loader-logo" draggable={false} />
      </div>

      <div className="flex flex-col items-center gap-3">
        <span className="sr-only">{message ?? "Loading"}</span>
        {message && (
          <p className="text-slate-300 text-sm tracking-wide" aria-hidden="true">
            {message}
            <span className="gc-dots">
              <i />
              <i />
              <i />
            </span>
          </p>
        )}
        {!compact && (
          <div className="gc-bar" aria-hidden="true">
            <span />
          </div>
        )}
      </div>
    </div>
  );
}
