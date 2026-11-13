import { Link } from "@/i18n/navigation";
import { ContactLine, legalIdentity, legalMetadata, LegalPage } from "@/components/site/legal-page";

export const revalidate = 300;
type Props = { params: Promise<{ locale: string }> };
export async function generateMetadata({ params }: Props) {
  return legalMetadata((await params).locale, "privacyTitle", "/privacy");
}

export default async function PrivacyPage({ params }: Props) {
  const { locale } = await params;
  const id = await legalIdentity();
  return (
    <LegalPage locale={locale} titleKey="privacyTitle">
      <p>This policy explains what personal data the MILI website collects, why, for how long, and what you can do about it. It applies to this website only.</p>

      <h2>1. Who is responsible</h2>
      <p>The data controller is:</p>
      <ContactLine id={id} />

      <h2>2. What we collect, and why</h2>
      <h3>When you join the Insider List</h3>
      <ul>
        <li>Your e-mail address (required), your first name and country (optional), and the language of the page you used.</li>
        <li>How you reached us: campaign parameters in the link you followed (UTM), the website that referred you (host name only), the first page you saw, and the code of the person who invited you, if any.</li>
        <li>Technical context of the registration: date and time, browser type, and a one-way cryptographic fingerprint of your IP address. We do not store the IP address itself.</li>
        <li>A record of your consent: the exact wording you accepted, when, and when you confirmed or withdrew it.</li>
      </ul>
      <p>We use this to send you the e-mails you asked for about MILI and its launch, to run the referral programme, to prevent abuse, and to measure which channels bring visitors. The legal basis is your consent for e-mails (GDPR art. 6(1)(a)) and our legitimate interest in securing the service and understanding our audience (art. 6(1)(f)).</p>
      <p>Registration uses double opt-in: you receive nothing but a single confirmation e-mail until you click the link in it.</p>

      <h3>When you submit a challenge</h3>
      <p>Your name, e-mail address, description, chosen category and the optional file you attach. Files are stored privately and are never published as they are. If your idea is selected, we publish a summary written by our team, credited with your first name only. The legal basis is your consent.</p>

      <h3>When you vote</h3>
      <p>A random identifier stored in a cookie on your device and the fingerprint of your IP address, used only to limit each browser to one vote per challenge.</p>

      <h3>When you contact us</h3>
      <p>Your e-mail address, your name if you give it, and your message, used to answer you.</p>

      <h3>When you browse</h3>
      <p>We count visits without cookies and without identifying you: each page view is reduced to an anonymous identifier that changes every day and cannot be traced back to you or linked from one day to the next. We record the page, the referring website, campaign parameters, country when the hosting platform provides it, and device type.</p>

      <h3>E-mail delivery events</h3>
      <p>Our e-mail provider tells us whether a message was delivered, bounced or marked as spam, and, where your mail application allows it, whether it was opened or a link was clicked. We use this to keep our list clean and to stop writing to addresses that do not work.</p>

      <h2>3. Who receives your data</h2>
      <p>We do not sell your data and we do not share it for advertising. It is processed on our behalf by the providers that run the site: Vercel (hosting), our managed PostgreSQL database provider, our file storage provider, and Resend (e-mail delivery). Some of them are located in the United States; transfers rely on the European Commission&apos;s Standard Contractual Clauses or the EU–US Data Privacy Framework where applicable.</p>
      <p>Videos are hosted by third-party platforms. Nothing is loaded from them until you press play; from that moment the platform&apos;s own privacy policy applies.</p>

      <h2>4. How long we keep it</h2>
      <ul>
        <li>Unconfirmed registrations: deleted after 30 days.</li>
        <li>Insider List data: until you unsubscribe or ask for deletion.</li>
        <li>After you unsubscribe: your address and the proof of your consent and of its withdrawal are kept for up to five years, so that we never write to you again by mistake and can demonstrate compliance. You can ask for full deletion at any time.</li>
        <li>Challenge submissions and their files: until you ask for deletion, and at the latest 24 months after submission.</li>
        <li>Contact messages: up to twelve months after they were received.</li>
        <li>Anonymous visit statistics: up to 25 months.</li>
      </ul>

      <h2>5. Your rights</h2>
      <p>You can access, correct, export or delete your data, withdraw your consent, and object to processing at any time. Every e-mail contains an unsubscribe link, and your Insider space lets you download or delete your data immediately, without asking us. For anything else, use the <Link href="/contact">contact form</Link>.</p>
      <p>If you live in the European Economic Area, the United Kingdom or Switzerland, you may lodge a complaint with your data protection authority. California residents have the right to know, delete and correct their personal information and are not discriminated against for exercising these rights; we do not sell or share personal information as defined by the CCPA/CPRA.</p>

      <h2>6. Security</h2>
      <p>Connections are encrypted. Access to the administration area is restricted, role-based and logged. Confirmation tokens are stored in hashed form and IP addresses are never stored in clear text.</p>

      <h2>7. Children</h2>
      <p>This website is not directed at children under 16 and we do not knowingly collect their data.</p>

      <h2>8. Changes</h2>
      <p>If this policy changes in a way that affects you, we will tell Insider List members by e-mail before the change takes effect.</p>
    </LegalPage>
  );
}
