import { Link } from "@/i18n/navigation";
import { ContactLine, legalIdentity, legalMetadata, LegalPage } from "@/components/site/legal-page";

export const revalidate = 300;
type Props = { params: Promise<{ locale: string }> };
export async function generateMetadata({ params }: Props) {
  return legalMetadata((await params).locale, "termsTitle", "/terms");
}

export default async function TermsPage({ params }: Props) {
  const { locale } = await params;
  const id = await legalIdentity();
  return (
    <LegalPage locale={locale} titleKey="termsTitle">
      <h2>1. Publisher</h2>
      <ContactLine id={id} />

      <h2>2. What this website is</h2>
      <p>This website presents MILI, a 5-axis CNC milling machine kit that is under development, ahead of a planned crowdfunding campaign. It is an information and pre-launch website.</p>
      <p><strong>Nothing is sold here.</strong> This website takes no order, no deposit and no payment. Joining the Insider List is free, creates no obligation to buy, and reserves nothing. Pledges, if and when the campaign opens, are made on Kickstarter, under Kickstarter&apos;s own terms.</p>

      <h2>3. Product information and prices</h2>
      <p>MILI is not yet on sale. Any price shown before the campaign opens, including the planned introductory price, is an intention and may change before launch. Reward levels, quantities, shipping costs, taxes and delivery estimates will be those stated on the campaign page. Characteristics of the product are published only once they have been validated; anything not stated is not promised.</p>
      <p>Backing a crowdfunding campaign is supporting a project, not buying from a shop: delivery dates are estimates and projects carry risks, which will be described on the campaign page.</p>

      <h2>4. Referral programme</h2>
      <p>Insider List members receive a personal invitation link. A referral counts when the invited person joins through that link and confirms their own e-mail address. Ranks are a form of recognition; any benefit attached to them will be announced before launch and is not promised until then. Self-referrals, fake or disposable addresses and automated sign-ups do not count, and we may withhold ranks or remove accounts involved in abuse.</p>

      <h2>5. The MILI Challenge</h2>
      <p>By submitting an idea you confirm that it is yours to share and that it does not infringe anyone else&apos;s rights. You keep all rights to your idea and to any file you send. You authorise us to publish a short summary of it on this website and on MILI&apos;s social channels, credited with your first name. Files you upload stay private. We choose which submissions are published and may decline any of them. Votes are indicative and create no entitlement to a prize.</p>

      <h2>6. Acceptable use</h2>
      <p>Do not attempt to disrupt the website, access areas that are not public, submit unlawful or malicious content, or automate sign-ups or votes.</p>

      <h2>7. Intellectual property</h2>
      <p>The MILI name, the texts, visuals, videos and code of this website belong to the publisher or its licensors. You may share links to the website and quote short excerpts with attribution.</p>

      <h2>8. Liability</h2>
      <p>The website is provided as is. We do our best to keep it accurate and available but cannot guarantee that it will be free of errors or interruptions. Nothing in these terms limits rights that the law of your country of residence gives you as a consumer.</p>

      <h2>9. Changes and contact</h2>
      <p>We may update these terms; the date at the top of the page shows the current version. Questions can be sent through the <Link href="/contact">contact form</Link>.</p>
    </LegalPage>
  );
}
