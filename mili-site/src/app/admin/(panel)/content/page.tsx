import Link from "next/link";
import { Card, Flash, PageTitle } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";
import { isLocale, localeNames, locales } from "@/lib/i18n/config";
import { flatMessages } from "@/lib/i18n/messages";
import { saveOverridesAction } from "../../actions/content";

export const metadata = { title: "Textes du site" };
const NAMESPACES: [string, string][] = [
  ["hero", "Accueil — ouverture"], ["mystery", "Le mystère"], ["proof", "La preuve"], ["clues", "Indices"], ["challenge", "Le défi"], ["join", "Inscription"],
  ["countdown", "Compte à rebours"], ["nav", "Navigation"], ["footer", "Pied de page"], ["faq", "FAQ (titre)"], ["confirm", "Confirmation"], ["unsubscribe", "Désinscription"],
  ["insider", "Espace Insider"], ["journal", "Journal"], ["contact", "Contact"], ["reveal", "Mode Reveal"], ["meta", "Référencement (SEO)"], ["errors", "Messages d'erreur"], ["notFound", "Page 404"], ["legal", "Pages légales (titres)"],
];

export default async function ContentPage({ searchParams }: { searchParams: Promise<{ ns?: string; locale?: string; ok?: string; error?: string }> }) {
  await requireAdmin("content.edit");
  const params = await searchParams;
  const ns = NAMESPACES.find(([key]) => key === params.ns)?.[0] ?? "hero";
  const locale = isLocale(params.locale) ? params.locale : "en";
  const [defaults, english, overrides] = await Promise.all([
    flatMessages(locale), flatMessages("en"),
    db.contentOverride.findMany({ where: { locale, key: { startsWith: `${ns}.` } } }),
  ]);
  const saved = new Map(overrides.map((o) => [o.key, o.value]));
  const keys = Object.keys(english).filter((k) => k.startsWith(`${ns}.`));

  return (
    <>
      <PageTitle title="Textes du site" text="Chaque texte du site public peut être remplacé ici, langue par langue. Un champ laissé vide reprend le texte d'origine. Les éléments entre accolades — {price}, {date}… — sont des variables : conservez-les telles quelles." />
      <Flash params={params} />
      <div className="mb-4 flex flex-wrap gap-1.5">
        {NAMESPACES.map(([key, label]) => (
          <Link key={key} href={`/admin/content?ns=${key}&locale=${locale}`} className={`adm-btn adm-btn-sm ${key === ns ? "" : "adm-btn-ghost"}`}>{label}</Link>
        ))}
      </div>
      <div className="mb-6 flex flex-wrap gap-1.5">
        {locales.map((l) => (
          <Link key={l} href={`/admin/content?ns=${ns}&locale=${l}`} className={`adm-btn adm-btn-sm ${l === locale ? "" : "adm-btn-ghost"}`}>{localeNames[l]}</Link>
        ))}
      </div>
      <form action={saveOverridesAction}>
        <input type="hidden" name="namespace" value={ns} />
        <input type="hidden" name="locale" value={locale} />
        <Card>
          <div className="divide-y divide-line">
            {keys.map((key) => {
              const base = defaults[key] ?? english[key];
              return (
                <div key={key} className="grid gap-3 py-4 first:pt-0 last:pb-0 lg:grid-cols-[1fr_1.3fr]">
                  <div>
                    <p className="font-mono text-xs text-smoke">{key}{saved.has(key) && <span className="ml-2 text-cyan">modifié</span>}</p>
                    <p className="mt-1.5 whitespace-pre-wrap text-sm text-ash">{base}</p>
                  </div>
                  <textarea name={`v:${key}`} rows={base.length > 90 ? 3 : 1} defaultValue={saved.get(key) ?? ""} placeholder={base} aria-label={key} className="field" />
                </div>
              );
            })}
          </div>
        </Card>
        <div className="sticky bottom-0 mt-4 border-t border-line bg-void/90 py-3 backdrop-blur"><button className="adm-btn">Enregistrer cette section ({localeNames[locale]})</button></div>
      </form>
    </>
  );
}
