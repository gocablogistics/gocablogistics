import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import SlideToContinue from "../components/SlideToContinue";

export default function Home() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const destination = user ? (user.role === "driver" ? "/driver" : "/rider") : "/login";

  return (
    <div className="relative w-full max-w-[480px] mx-auto min-h-dvh bg-[#20241f] overflow-hidden flex flex-col text-slate-100">
      <div className="relative bg-[#8c978f] pt-10 pb-16 px-6 flex flex-col items-center flex-[1.3] justify-between">
        {/* Logo */}
        <div className="flex flex-col items-center z-10 pt-2">
          <div className="flex items-center space-x-2">
            <img
              src="/gocab-logo.png"
              alt="GoCab"
              className="w-10 h-10 object-contain drop-shadow-md"
            />
            <div className="flex flex-col justify-center">
              <span className="text-white text-2xl font-bold tracking-tight leading-none">GoCab</span>
              <div className="flex items-center space-x-1 mt-0.5">
                <span className="w-4 h-[1.5px] bg-white/70" />
                <span className="text-white/90 text-[10px] tracking-widest font-medium uppercase">Logistics</span>
              </div>
            </div>
          </div>
        </div>

        {/* Rider illustration */}
        <div className="relative my-auto w-full flex items-center justify-center animate-float z-10">
          <img
            src="/bike-rider.png"
            alt="GoCab Rider Illustration"
            className="w-full h-auto object-contain drop-shadow-2xl"
          />
        </div>

        <div className="wave-divider">
          <svg viewBox="0 0 1200 120" preserveAspectRatio="none">
            <path
              d="M0,0 C150,90 350,-40 500,65 C650,140 900,10 1200,45 L1200,120 L0,120 Z"
              fill="#20241f"
            />
          </svg>
        </div>
      </div>

      <div className="relative bg-[#20241f] px-8 pt-2 pb-10 flex flex-col justify-between items-center text-center flex-1 z-20">
        <div className="flex items-center justify-center space-x-2 my-2">
          <span className="w-2.5 h-2.5 rounded-full bg-white opacity-80" />
          <span className="w-2.5 h-2.5 rounded-full bg-white opacity-80" />
          <span className="w-9 h-3 rounded-full bg-[#1be451]" />
        </div>

        <div className="my-auto space-y-3 max-w-[320px]">
          <h1 className="text-white text-2xl sm:text-[26px] font-extrabold tracking-tight leading-snug">
            Bike Dispatch, <br />
            <span className="italic font-black text-white tracking-wide">On Demand</span>
          </h1>
          <p className="text-slate-300/80 text-sm font-normal leading-relaxed px-2">
            Parcels, packages, and people, moved fast by GoCab riders near you.
          </p>
        </div>

        <SlideToContinue
          label="Continue"
          successLabel={user ? "Welcome back! " : "Let's go "}
          onComplete={() => navigate(destination)}
        />

        
      </div>
    </div>
  );
}
