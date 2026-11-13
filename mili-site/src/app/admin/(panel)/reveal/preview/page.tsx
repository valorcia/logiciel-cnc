import Link from "next/link";
import { ProductView } from "@/components/site/product-view";
import { RevealObserver } from "@/components/site/reveal-observer";
import { requireAdmin } from "@/lib/admin-session";
import { revealContent } from "@/lib/content";
import { isLocale, localeNames, locales } from "@/lib/i18n/config";
import { getSettings } from "@/lib/settings";

export const metadata = { title: "Prévisualisation" };

/** The product page exactly as visitors will get it — including sections not yet published, flagged as such. */
export default async function RevealPreviewPage({ searchParams }: { searchParams: Promise<{ locale?: string }> }) {
  await requireAdmin("product.edit");
  const params = await searchParams;
  const locale = isLocale(params.locale) ? params.locale : "en";
  const [content, settings] = await Promise.all([revealContent(locale, { preview: true }), getSettings()]);
  return (
    <div className="-mx-4 -my-8 sm:-mx-8 lg:-mx-10" style={{ "--header-h": "0rem" } as React.CSSProperties}>
      <div className="sticky top-0 z-40 flex flex-wrap items-center gap-2 border-b border-[#ffc46b]/40 bg-[#1a1408] px-4 py-2.5 text-sm text-[#ffc46b]">
        <strong>Prévisualisation confidentielle</strong>
        <span className="text-xs">Inclut les sections non publiées. Les caractéristiques non validées et les récompenses inactives n&apos;y figurent pas, comme sur le site.</span>
        <span className="ml-auto flex gap-1.5">
          {locales.map((l) => <Link key={l} href={`/admin/reveal/preview?locale=${l}`} className={`adm-btn adm-btn-sm ${l === locale ? "" : "adm-btn-ghost"}`} title={localeNames[l]}>{l.toUpperCase()}</Link>)}
          <Link href="/admin/reveal" className="adm-btn adm-btn-ghost adm-btn-sm">Fermer</Link>
        </span>
      </div>
      <div className="text-base">
        {content && <ProductView locale={locale} content={content} kickstarterUrl={settings.kickstarterUrl} />}
      </div>
      <RevealObserver />
    </div>
  );
}
