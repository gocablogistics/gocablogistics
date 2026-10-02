import { useNavigate } from "react-router-dom";

// TODO: keep in sync with Support.tsx's SUPPORT_EMAIL placeholder — swap
// both to the real inbox before launch.
const SUPPORT_EMAIL = "support@gocab.app";
const LAST_UPDATED = "22 September 2026";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <h2 className="text-white font-semibold">{title}</h2>
      <div className="text-slate-300 text-sm leading-relaxed flex flex-col gap-2">{children}</div>
    </div>
  );
}

export default function PrivacyPolicy() {
  const navigate = useNavigate();

  return (
    <div className="fixed inset-0 flex flex-col bg-[#20241f] text-slate-100">
      <div className="flex items-center gap-3 px-4 pt-6 pb-4 border-b border-white/5">
        <button
          onClick={() => navigate(-1)}
          className="w-9 h-9 rounded-full bg-white/10 flex items-center justify-center shrink-0"
          aria-label="Back"
        >
          <i className="fa-solid fa-arrow-left" />
        </button>
        <div>
          <h1 className="text-white text-xl font-extrabold">Privacy Policy</h1>
          <p className="text-slate-400 text-xs">Last updated {LAST_UPDATED}</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-6 flex flex-col gap-6 max-w-2xl mx-auto w-full">
        <p className="text-slate-300 text-sm leading-relaxed">
          GoCab ("we", "us") runs a bike courier and delivery service connecting senders with
          couriers. This page explains what information we collect, why, and what choices you
          have, for both riders (people sending or receiving a package) and drivers (couriers).
        </p>

        <Section title="Information we collect">
          <p><strong className="text-white">Account details.</strong> Your phone number and email are how we identify your account and send you a one-time login code. GoCab doesn't use passwords.</p>
          <p><strong className="text-white">Driver verification documents.</strong> Drivers provide a National Identification Number, a driver's license, a selfie, vehicle details and a photo, and bank account details for payouts. This is required so we can verify who's operating on the platform and pay drivers correctly.</p>
          <p><strong className="text-white">Location.</strong> A rider's pickup and drop-off addresses, and a driver's live location while online or on a trip, so we can match rides and show accurate progress. Background location on a driver's device only runs while they're online, shown by a persistent notification.</p>
          <p><strong className="text-white">Trip and payment information.</strong> Ride history, fares, and payment status. Card payments are processed by Paystack directly. GoCab never receives or stores your full card number.</p>
          <p><strong className="text-white">Messages and ratings.</strong> In-ride chat messages between a rider and driver for that trip, and the star ratings and comments you leave after a ride.</p>
          <p><strong className="text-white">Device and push notification data.</strong> A device token so we can send you ride updates and alerts through Firebase Cloud Messaging.</p>
        </Section>

        <Section title="How we use it">
          <ul className="list-disc pl-5 flex flex-col gap-1">
            <li>Matching riders with nearby drivers and calculating fares and pickup times</li>
            <li>Processing payments and driver payouts</li>
            <li>Sending ride status updates, chat messages, and account alerts</li>
            <li>Verifying driver identity and preventing fraud or abuse (e.g. repeated non-payment or cancellations)</li>
            <li>Responding to support requests and resolving disputes between riders and drivers</li>
          </ul>
        </Section>

        <Section title="Who we share it with">
          <p>We don't sell your information. It's shared only with the services that make GoCab work:</p>
          <ul className="list-disc pl-5 flex flex-col gap-1">
            <li><strong className="text-white">Paystack</strong>, to process card payments and driver bank transfers</li>
            <li><strong className="text-white">Google</strong>, for maps, address search, and route/fare calculation</li>
            <li><strong className="text-white">Firebase (Google)</strong>, to deliver push notifications</li>
            <li>The other party on a trip: a driver sees the rider's name, phone number, and pickup/drop-off; a rider sees the driver's name, phone, photo, vehicle, and rating</li>
          </ul>
        </Section>

        <Section title="How long we keep it">
          <p>Ride, payment, and dispute records are kept for as long as needed for accounting, tax, and fraud-prevention purposes, even after an account is deleted. Live location is not retained once a trip ends.</p>
        </Section>

        <Section title="Your choices">
          <p>You can delete your account at any time from within the app (Profile → Delete account), which deactivates it and removes your phone number and email from our active records. To request deletion without access to the app, email us at{" "}
            <a href={`mailto:${SUPPORT_EMAIL}`} className="text-[#1be451] underline">{SUPPORT_EMAIL}</a>.
          </p>
          <p>Some records (completed trips, payments, and any open dispute) are kept even after deletion, as described above.</p>
        </Section>

        <Section title="Children">
          <p>GoCab is not directed at children, and both riders and drivers must be old enough to hold a valid means of payment or a driver's license respectively.</p>
        </Section>

        <Section title="Changes to this policy">
          <p>We'll update the date at the top of this page if this policy changes. Continuing to use GoCab after a change means you accept the update.</p>
        </Section>

        <Section title="Contact us">
          <p>Questions about this policy or your data, email{" "}
            <a href={`mailto:${SUPPORT_EMAIL}`} className="text-[#1be451] underline">{SUPPORT_EMAIL}</a>.
          </p>
        </Section>
      </div>
    </div>
  );
}
