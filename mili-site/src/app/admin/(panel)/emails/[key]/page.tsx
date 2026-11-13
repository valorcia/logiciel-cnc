import Link from "next/link";
import { notFound } from "next/navigation";
import { Submit } from "@/components/admin/client";
import { Card, Field, Flash, PageTitle } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";
import { buildEmail, sampleVars } from "@/lib/email/send";
import { siteUrl } from "@/lib/env";
import { isLocale, localeNames, locales } from "@/lib/i18n/config";
import { can } from "@/lib/permissions";
import { getSettings } from "@/lib/settings";
import { deleteTemplateTranslationAction, saveTemplateAction, sendTestAction } from "../../../actions/emails";

export const metadata = { title: "Modèle d'e-mail" };

export default async function TemplatePage({ params, searchParams }: { params: Promise<{ key: string }>; searchParams: Promise<{ locale?: string; ok?: string; error?: string }> }) {
  const admin = await requireAdmin("emails.edit");
  const { key } = await params;
  const query = await searchParams;
  const locale = isLocale(query.locale) ? query.locale : "en";
  const [versions, settings] = await Promise.all([db.emailTemplate.findMany({ where: { key } }), getSettings()]);
  if (versions.length === 0) notFound();
  const english = versions.find((v) => v.locale === "en") ?? versions[0];
  const current = versions.find((v) => v.locale === locale);
  const shown = current ?? { ...english, locale };
  const built = buildEmail(
    shown, { ...sampleVars(locale, settings), confirmUrl: `${siteUrl()}/confirm?token=SAMPLE` }, settings,
    key === "confirm" ? undefined : { url: `${siteUrl()}/unsubscribe?t=SAMPLE`, oneClickUrl: `${siteUrl()}/api/unsubscribe?t=SAMPLE` },
  );

  return (
    <>
      <PageTitle title={english.name} text={`Modèle « ${key} ». ${current ? "" : `Pas encore de version ${localeNames[locale]} : les abonnés dans cette langue reçoivent la version anglaise. Le texte ci-dessous est l'anglais, à traduire.`}`} actions={<Link href="/admin/emails" className="adm-btn adm-btn-ghost">← Tous les e-mails</Link>} />
      <Flash params={query} />
      <div className="mb-6 flex flex-wrap gap-1.5">
        {locales.map((l) => (
          <Link key={l} href={`/admin/emails/${key}?locale=${l}`} className={`adm-btn adm-btn-sm ${l === locale ? "" : "adm-btn-ghost"}`}>
            {localeNames[l]}{versions.some((v) => v.locale === l) ? "" : " ＋"}
          </Link>
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="space-y-4">
          <Card>
            <form action={saveTemplateAction} className="space-y-4">
              <input type="hidden" name="key" value={key} />
              <input type="hidden" name="locale" value={locale} />
              <Field label="Objet" name="subject" defaultValue={shown.subject} required maxLength={150} />
              <Field label="Texte d'aperçu" name="preheader" defaultValue={shown.preheader} maxLength={150} help="La ligne grise affichée après l'objet dans la boîte de réception." />
              <Field label="Contenu" name="body" defaultValue={shown.body} rows={20} mono required
                help="Mise en forme : # Titre · ## Sous-titre · **gras** · *italique* · - liste · [lien](https://…) · bouton, seul sur sa ligne : [[Libellé|https://…]]. Variables : {{firstName}} {{greeting}} {{referralLink}} {{insiderLink}} {{launchDate}} {{kickstarterUrl}} {{siteUrl}}. Le lien de désinscription et l'adresse postale sont ajoutés automatiquement en pied." />
              <button className="adm-btn">{current ? "Enregistrer" : `Créer la version ${localeNames[locale]}`}</button>
            </form>
            {current && locale !== "en" && (
              <form action={deleteTemplateTranslationAction} className="mt-3">
                <input type="hidden" name="key" value={key} /><input type="hidden" name="locale" value={locale} />
                <Submit className="adm-btn adm-btn-danger adm-btn-sm" confirm="Supprimer cette traduction ? Les abonnés concernés recevront la version anglaise.">Supprimer cette traduction</Submit>
              </form>
            )}
          </Card>
          {can(admin.role, "emails.send") && (
            <Card title="Envoyer un test">
              <form action={sendTestAction} className="flex flex-wrap items-end gap-3">
                <input type="hidden" name="key" value={key} /><input type="hidden" name="locale" value={locale} />
                <div className="min-w-64 flex-1"><Field label="Adresse" name="to" type="email" defaultValue={admin.email} /></div>
                <button className="adm-btn adm-btn-ghost" disabled={!current}>Envoyer le test</button>
              </form>
              <p className="mt-2 text-xs text-smoke">Le test utilise la dernière version enregistrée et des données d&apos;exemple (prénom « Alex »). Son objet est préfixé [TEST].</p>
            </Card>
          )}
        </div>
        <Card title="Aperçu" aside={<span className="text-xs text-smoke">Données d&apos;exemple · dernière version enregistrée</span>}>
          <p className="mb-3 text-sm"><span className="text-smoke">Objet : </span>{built.subject}</p>
          {/* Sandboxed: the preview cannot run scripts or reach the back office. */}
          <iframe title="Aperçu de l'e-mail" sandbox="" srcDoc={built.message.html} className="h-[46rem] w-full rounded-lg border border-line bg-[#050505]" />
          <details className="mt-3 text-xs text-smoke">
            <summary>Version texte brut</summary>
            <pre className="mt-2 whitespace-pre-wrap rounded-lg bg-void p-4 font-mono text-ash">{built.message.text}</pre>
          </details>
        </Card>
      </div>
    </>
  );
}
