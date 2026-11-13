import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import type { ReactNode } from "react";
import type { Locale } from "@/lib/i18n/config";
import { pageMetadata } from "@/lib/seo";
import { getSettings } from "@/lib/settings";

export const LEGAL_UPDATED = "2026-11-13";

export type LegalIdentity = { name: string; address: string; email: string };

/** Who operates the site, as entered in the back office (Settings → Legal identity). */
export async function legalIdentity(): Promise<LegalIdentity> {
  const s = await getSettings();
  return {
    name: s.legalName?.trim() || "the publisher of the MILI website",
    address: s.postalAddress?.trim() || "",
    email: s.contactEmail?.trim() || "",
  };
}

export async function legalMetadata(locale: string, key: "privacyTitle" | "termsTitle" | "cookiesTitle", path: string): Promise<Metadata> {
  const t = await getTranslations({ locale, namespace: "legal" });
  return pageMetadata({ locale: locale as Locale, path, title: t(key), description: t(key) });
}

export async function LegalPage({ locale, titleKey, children }: { locale: string; titleKey: "privacyTitle" | "termsTitle" | "cookiesTitle"; children: ReactNode }) {
  setRequestLocale(locale);
  const t = await getTranslations({ locale, namespace: "legal" });
  return (
    <article className="shell pb-28 pt-[calc(var(--header-h)+5rem)]">
      <div className="mx-auto max-w-3xl">
        <h1 className="display display-lg">{t(titleKey)}</h1>
        <p className="mt-6 text-sm text-smoke">{t("updated", { date: LEGAL_UPDATED })}</p>
        {locale !== "en" && <p className="mt-2 text-sm text-smoke">{t("englishOnly")}</p>}
        <div className="prose-mili mt-12" lang="en">{children}</div>
      </div>
    </article>
  );
}

export function ContactLine({ id }: { id: LegalIdentity }) {
  return (
    <p>
      {id.name}
      {id.address && <><br />{id.address}</>}
      {id.email && <><br /><a href={`mailto:${id.email}`}>{id.email}</a></>}
      <br />You can also use the <a href="/contact">contact form</a>.
    </p>
  );
}
