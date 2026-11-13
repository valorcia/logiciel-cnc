import { legalMetadata, LegalPage } from "@/components/site/legal-page";

export const revalidate = 300;
type Props = { params: Promise<{ locale: string }> };
export async function generateMetadata({ params }: Props) {
  return legalMetadata((await params).locale, "cookiesTitle", "/cookies");
}

export default async function CookiesPage({ params }: Props) {
  const { locale } = await params;
  return (
    <LegalPage locale={locale} titleKey="cookiesTitle">
      <p>This website uses no advertising cookies and no third-party tracking cookies. Audience measurement is done without cookies. That is why you do not see a cookie banner: everything listed below is strictly necessary for a feature you asked for.</p>

      <h2>Cookies we set</h2>
      <table>
        <thead><tr><th>Name</th><th>Purpose</th><th>Lifetime</th></tr></thead>
        <tbody>
          <tr><td><code>NEXT_LOCALE</code></td><td>Remembers the language you chose.</td><td>Session to 1 year</td></tr>
          <tr><td><code>milli_ref</code></td><td>Set only if you arrive through an invitation link: remembers who invited you so they are credited if you join.</td><td>30 days</td></tr>
          <tr><td><code>milli_voter</code></td><td>Set only if you vote for a challenge: a random identifier that limits each browser to one vote per challenge.</td><td>1 year</td></tr>
        </tbody>
      </table>
      <p>Administrators of the website also receive a session cookie when they sign in to the back office.</p>

      <h2>Storage in your browser</h2>
      <table>
        <thead><tr><th>Name</th><th>Purpose</th><th>Lifetime</th></tr></thead>
        <tbody>
          <tr><td><code>milli_intro</code></td><td>Avoids replaying the opening animation on every page.</td><td>Until you close the tab</td></tr>
          <tr><td><code>milli_attr</code></td><td>Keeps the campaign parameters of the link you followed until you register, so we know which channel brought you.</td><td>Until you close the tab</td></tr>
          <tr><td><code>milli_clues_seen</code></td><td>Remembers which clues you have already seen, to highlight new ones.</td><td>Until you clear it</td></tr>
        </tbody>
      </table>

      <h2>Embedded videos</h2>
      <p>Videos are hosted by third-party platforms. Nothing is requested from them, and they set nothing on your device, until you press play. From then on the platform may set its own cookies under its own policy.</p>

      <h2>Managing cookies</h2>
      <p>You can delete or block cookies in your browser settings. The website keeps working; only the features described above are affected.</p>
    </LegalPage>
  );
}
