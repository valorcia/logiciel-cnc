import { getTranslations, setRequestLocale } from "next-intl/server";
import { ChallengeSection } from "@/components/site/challenge-section";
import { CluesSection } from "@/components/site/clues-section";
import { FaqSection } from "@/components/site/faq-section";
import { Hero } from "@/components/site/hero";
import { JoinSection } from "@/components/site/join-section";
import { MysterySection } from "@/components/site/mystery-section";
import { ProofSection } from "@/components/site/proof-section";
import { RevealHome } from "@/components/site/reveal-home";
import { jsonLd, baseUrl } from "@/lib/seo";
import { getSettings, socialLinks } from "@/lib/settings";

export const revalidate = 60;

export default async function HomePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const settings = await getSettings();
  const meta = await getTranslations({ locale, namespace: "meta" });
  const revealed = settings.mode === "REVEAL";

  const schema = {
    "@context": "https://schema.org",
    "@graph": [
      { "@type": "Organization", "@id": `${baseUrl()}/#org`, name: "MILLI", url: baseUrl(), sameAs: Object.values(socialLinks(settings)) },
      { "@type": "WebSite", "@id": `${baseUrl()}/#site`, name: "MILLI", url: baseUrl(), description: meta("description"), publisher: { "@id": `${baseUrl()}/#org` }, inLanguage: locale },
    ],
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(schema) }} />
      {revealed ? (
        <RevealHome locale={locale} settings={settings} />
      ) : (
        <>
          <Hero locale={locale} settings={settings} />
          <MysterySection locale={locale} settings={settings} />
        </>
      )}
      <ProofSection locale={locale} />
      {!revealed && <CluesSection locale={locale} />}
      <ChallengeSection locale={locale} />
      <JoinSection locale={locale} />
      <FaqSection locale={locale} mode={revealed ? "REVEAL" : "MYSTERY"} />
    </>
  );
}
