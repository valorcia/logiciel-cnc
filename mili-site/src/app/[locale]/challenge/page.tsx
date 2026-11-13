import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { ChallengeSection } from "@/components/site/challenge-section";
import type { Locale } from "@/lib/i18n/config";
import { pageMetadata } from "@/lib/seo";

export const revalidate = 60;
type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "challenge" });
  return pageMetadata({ locale: locale as Locale, path: "/challenge", title: t("pageTitle"), description: t("intro") });
}

export default async function ChallengePage({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <div className="pt-[var(--header-h)]"><ChallengeSection locale={locale} full /></div>;
}
