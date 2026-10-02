import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

// TODO: swap in the real support inbox before launch.
const SUPPORT_EMAIL = "support@gocab.app";

// GoCab is a courier/delivery app, not a passenger ride-hailing app — the
// "rider" here is the person sending or receiving a package, not someone
// getting into a vehicle, so their safety concerns are different from the
// courier's (who's the one actually out on the road on a bike/bicycle).
const SENDER_SAFETY_TIPS = [
  "Confirm the courier's name, photo, and plate/bike match what's shown in the app before handing over your package.",
  "Never hand over a package before the trip shows as \"started\" in the app.",
  "Accurately describe what you're sending. Never send anything illegal, hazardous, or fragile without saying so.",
  "Double-check the recipient's phone number and address so the courier can actually reach them.",
  "Keep your cash payment code to yourself until the package has actually been delivered.",
  "Track the delivery in the app rather than arranging to meet the courier somewhere off-app.",
  "Report anything that feels off right away, such as a courier asking for extra cash, or going off-route.",
];

const COURIER_SAFETY_TIPS = [
  "Confirm the pickup address and sender's name match the app before collecting a package.",
  "Don't accept a package that looks illegal, hazardous, or doesn't match its description. You're responsible for what you're carrying.",
  "Wear a helmet and follow traffic laws. Your safety on the road comes first.",
  "Confirm the recipient's identity (or their cash code) before handing over the package or marking it delivered.",
  "Avoid off-app cash arrangements. Your payout and protection both depend on the trip going through the app.",
  "Keep your phone charged and reachable in case a sender or recipient needs to reach you mid-delivery.",
  "If a pickup or drop-off location feels unsafe, don't go through with it. Cancel and report it instead.",
];

export default function Support() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const isDriver = user?.role === "driver";
  const tips = isDriver ? COURIER_SAFETY_TIPS : SENDER_SAFETY_TIPS;

  return (
    <div className="fixed inset-0 flex flex-col bg-[#20241f] text-slate-100">
      <div className="flex items-center gap-3 px-4 pt-6 pb-4">
        <button
          onClick={() => navigate(user?.role === "driver" ? "/driver" : "/rider")}
          className="w-9 h-9 rounded-full bg-white/10 flex items-center justify-center"
          aria-label="Back"
        >
          <i className="fa-solid fa-arrow-left" />
        </button>
        <h1 className="text-white text-xl font-extrabold">Support</h1>
      </div>

      <div className="flex-1 overflow-y-auto px-4 pb-8 flex flex-col gap-6">
        <div>
          <h2 className="text-white font-semibold mb-3">
            {isDriver ? "Safety tips for couriers" : "Safety tips for sending a package"}
          </h2>
          <div className="flex flex-col gap-2">
            {tips.map((tip) => (
              <div key={tip} className="rounded-2xl bg-white/5 border border-white/10 p-3 flex gap-3 items-start">
                <i className="fa-solid fa-shield-halved text-[#1be451] mt-0.5" />
                <p className="text-slate-200 text-sm">{tip}</p>
              </div>
            ))}
          </div>
        </div>

        <div>
          <h2 className="text-white font-semibold mb-3">Contact support</h2>
          <p className="text-slate-400 text-sm mb-3">
            Something not covered here? Email us and we'll get back to you.
          </p>
          <a
            href={`mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(
              `GoCab support, ${isDriver ? "courier" : "sender"} account`,
            )}`}
            className="w-full py-4 rounded-full bg-[#1be451] text-neutral-900 font-bold text-lg flex items-center justify-center gap-2"
          >
            <i className="fa-solid fa-envelope" />
            Email {SUPPORT_EMAIL}
          </a>
        </div>
      </div>
    </div>
  );
}
