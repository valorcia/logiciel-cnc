import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import { FaqSection } from "@/components/site/faq-section";
import { ProductView } from "@/components/site/product-view";
import { revealContent } from "@/lib/content";
import type { Locale } from "@/lib/i18n/config";
import { pageMetadata } from "@/lib/seo";
import { getSettings } from "@/lib/settings";

export const revalidate = 60;
type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  const settings = await getSettings();
  // In Mystery mode this URL is a plain 404 and says nothing, not even in its metadata.
  if (settings.mode !== "REVEAL") return { robots: { index: false, follow: false } };
  const t = await getTranslations({ locale, namespace: "reveal" });
  return pageMetadata({ locale: locale as Locale, path: "/mili", title: t("heroTitle"), description: t("homeText") });
}

export default async function ProductPage({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  const content = await revealContent(locale);
  if (!content) notFound();
  const settings = await getSettings();
  return (
    <>
      <ProductView locale={locale} content={content} kickstarterUrl={settings.kickstarterUrl} />
      <FaqSection locale={locale} mode="REVEAL" />
    </>
  );
}
