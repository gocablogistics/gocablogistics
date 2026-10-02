import { useNavigate } from "react-router-dom";

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

export default function TermsAndConditions() {
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
          <h1 className="text-white text-xl font-extrabold">Terms &amp; Conditions</h1>
          <p className="text-slate-400 text-xs">Last updated {LAST_UPDATED}</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-6 flex flex-col gap-6 max-w-2xl mx-auto w-full">
        <p className="text-slate-300 text-sm leading-relaxed">
          By creating a GoCab account, as a rider (sender) or a driver (courier), you agree to
          these terms. GoCab connects people who need a small package moved with independent
          bike/bicycle couriers. GoCab isn't the courier itself, and doesn't own the vehicles
          used.
        </p>

        <Section title="What GoCab can carry">
          <ul className="list-disc pl-5 flex flex-col gap-1">
            <li>Fits in a backpack, up to 60×40×30cm</li>
            <li>Up to 15kg</li>
            <li>Worth up to ₦50,000</li>
            <li>Nothing illegal, hazardous, or that requires special handling</li>
          </ul>
          <p>You're responsible for accurately describing what you're sending. GoCab and the courier can refuse a package that doesn't match its description or these limits.</p>
        </Section>

        <Section title="Fares and payment">
          <p>The fare shown before you book is the fare you pay, unless it expires before you confirm. In that case you'll be asked to get a new estimate. Fares may vary by time of day.</p>
          <p>Card payments are processed by Paystack. Where cash is enabled, GoCab charges a 25% commission on the fare, which the driver owes GoCab directly. It isn't collected from you separately.</p>
          <p>A completed trip must be paid before you can book another. If a driver reports a trip as unpaid, your account is held the same way until it's paid or the report is reviewed.</p>
        </Section>

        <Section title="Cancellations">
          <p>You can cancel a trip before it starts, free of charge. Cancelling often in a short period may temporarily pause your ability to book or accept trips.</p>
        </Section>

        <Section title="Driver requirements">
          <p>Drivers must provide accurate identification and vehicle documents, and are approved before going online. GoCab may suspend a driver account for failed verification, repeated cancellations, low ratings, unresolved disputes, or unpaid cash commission.</p>
        </Section>

        <Section title="Account suspension">
          <p>GoCab may suspend or ban an account for fraud, repeated non-payment, abusive behaviour, or violating these terms. Reports against an account are reviewed before any lasting action is taken, except where a threshold (e.g. repeated non-payment) triggers an automatic hold pending review.</p>
        </Section>

        <Section title="Disputes">
          <p>If something goes wrong on a trip, report it in the app. GoCab reviews reports and may resolve a dispute by marking a trip paid, issuing a refund, or another outcome we consider fair to both sides. GoCab's decision on a dispute is final.</p>
        </Section>

        <Section title="Liability">
          <p>GoCab facilitates the connection between riders and drivers but isn't a party to the delivery itself. To the extent permitted by law, GoCab isn't liable for loss, damage, or delay of a package, except where required by Nigerian law.</p>
        </Section>

        <Section title="Changes to these terms">
          <p>We may update these terms as GoCab grows. We'll update the date above when we do. Continuing to use GoCab after a change means you accept it.</p>
        </Section>

        <Section title="Governing law">
          <p>These terms are governed by the laws of the Federal Republic of Nigeria.</p>
        </Section>

        <Section title="Contact us">
          <p>Questions about these terms, email{" "}
            <a href={`mailto:${SUPPORT_EMAIL}`} className="text-[#1be451] underline">{SUPPORT_EMAIL}</a>.
          </p>
        </Section>
      </div>
    </div>
  );
}
