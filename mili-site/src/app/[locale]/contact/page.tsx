import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { ContactForm } from "@/components/site/contact-form";
import type { Locale } from "@/lib/i18n/config";
import { pageMetadata } from "@/lib/seo";
import { getSettings } from "@/lib/settings";

export const revalidate = 300;
type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "contact" });
  return pageMetadata({ locale: locale as Locale, path: "/contact", title: t("title"), description: t("text") });
}

export default async function ContactPage({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations({ locale, namespace: "contact" });
  const settings = await getSettings();
  return (
    <div className="shell grid gap-12 pb-28 pt-[calc(var(--header-h)+5rem)] lg:grid-cols-2 lg:gap-20">
      <div>
        <h1 className="display display-xl">{t("title")}</h1>
        <p className="lede mt-7 max-w-md">{t("text")}</p>
        {settings.contactEmail && <p className="mt-6"><a href={`mailto:${settings.contactEmail}`} className="text-white underline underline-offset-4 hover:text-cyan">{settings.contactEmail}</a></p>}
      </div>
      <ContactForm />
    </div>
  );
}
