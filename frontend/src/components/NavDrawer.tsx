import { useNavigate } from "react-router-dom";
import { useBackHandler } from "../hooks/useBackHandler";
import { useMountTransition } from "../hooks/useMountTransition";
import { withViewTransition } from "../lib/viewTransition";

const TRANSITION_MS = 220;

interface NavDrawerProps {
  open: boolean;
  onClose: () => void;
  role: "rider" | "driver";
  onLogout: () => void;
}

const RIDER_LINKS = [
  { to: "/rider/history", label: "Ride history", icon: "fa-clock-rotate-left" },
  { to: "/rider/referrals", label: "Refer a friend", icon: "fa-gift" },
  { to: "/rider/profile", label: "Profile", icon: "fa-user" },
  { to: "/rider/support", label: "Support", icon: "fa-circle-question" },
];

const DRIVER_LINKS = [
  { to: "/driver/history", label: "Ride history", icon: "fa-clock-rotate-left" },
  { to: "/driver/profile", label: "Profile", icon: "fa-user" },
  { to: "/driver/balance", label: "Balance", icon: "fa-wallet" },
  { to: "/driver/support", label: "Support", icon: "fa-circle-question" },
];

export default function NavDrawer({ open, onClose, role, onLogout }: NavDrawerProps) {
  const navigate = useNavigate();
  useBackHandler(open, onClose);
  const { shouldRender, isOpen } = useMountTransition(open, TRANSITION_MS);
  if (!shouldRender) return null;
  const links = role === "rider" ? RIDER_LINKS : DRIVER_LINKS;

  function goTo(path: string) {
    onClose();
    withViewTransition(() => navigate(path));
  }

  return (
    <div className="fixed inset-0 z-20 flex">
      <div
        className={`safe-area-shell w-64 h-full bg-[#181c17] p-6 flex flex-col gap-3 text-slate-100 transition-transform ease-out ${
          isOpen ? "translate-x-0" : "-translate-x-full"
        }`}
        style={{ transitionDuration: `${TRANSITION_MS}ms` }}
      >
        <button onClick={onClose} className="self-end text-slate-400 mb-2" aria-label="Close menu">
          <i className="fa-solid fa-xmark text-lg" />
        </button>
        {links.map((link) => (
          <button
            key={link.to}
            onClick={() => goTo(link.to)}
            className="w-full py-3 rounded-full bg-white/10 border border-white/20 text-white font-semibold flex items-center justify-center gap-2"
          >
            <i className={`fa-solid ${link.icon}`} />
            {link.label}
          </button>
        ))}
        <button
          onClick={onLogout}
          className="w-full py-3 rounded-full bg-white/10 border border-white/20 text-white font-semibold flex items-center justify-center gap-2 mt-auto"
        >
          <i className="fa-solid fa-right-from-bracket" />
          Log out
        </button>
      </div>
      <div
        className={`flex-1 bg-black/40 transition-opacity ease-out ${isOpen ? "opacity-100" : "opacity-0"}`}
        style={{ transitionDuration: `${TRANSITION_MS}ms` }}
        onClick={onClose}
      />
    </div>
  );
}
