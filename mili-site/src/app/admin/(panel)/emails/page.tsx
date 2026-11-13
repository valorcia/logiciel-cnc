import Link from "next/link";
import { Submit } from "@/components/admin/client";
import { Badge, Card, Empty, Flash, fmtDate, fmtNum, fmtPct, PageTitle, StatusBadge } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";
import { can } from "@/lib/permissions";
import { getSettings } from "@/lib/settings";
import { runAutomationAction, saveStepAction } from "../../actions/emails";

export const metadata = { title: "E-mails" };
const SERIES: Record<string, [string, string]> = {
  TRANSACTIONAL: ["Transactionnels", "Envoyés immédiatement en réponse à une action (confirmation d'inscription)."],
  WELCOME: ["Séquence de bienvenue", "Délai compté à partir de la confirmation de l'adresse."],
  PRELAUNCH: ["Pré-lancement", "Calée sur la date de lancement définie dans Paramètres. Sans date, rien ne part."],
  LAUNCH: ["Lancement", "Calée sur la date de lancement. Bloquée tant que le site n'est pas en mode Reveal avec un lien Kickstarter."],
};

function describeOffset(series: string, minutes: number): string {
  const abs = Math.abs(minutes);
  const amount = abs % 1440 === 0 ? `${abs / 1440} j` : `${Math.round(abs / 60)} h`;
  if (series === "WELCOME") return minutes === 0 ? "À la confirmation" : `${amount} après la confirmation`;
  return minutes === 0 ? "Jour J" : minutes < 0 ? `J-${abs / 1440 >= 1 ? Math.round(abs / 1440) : amount}` : `J+${Math.round(abs / 1440)}`;
}

export default async function EmailsPage({ searchParams }: { searchParams: Promise<{ ok?: string; error?: string; ran?: string; failed?: string }> }) {
  const admin = await requireAdmin("emails.edit");
  const params = await searchParams;
  const [templates, steps, settings, sends, eventRows, sendCounts, recipients] = await Promise.all([
    db.emailTemplate.findMany({ orderBy: [{ key: "asc" }, { locale: "asc" }] }),
    db.emailStep.findMany({ orderBy: [{ series: "asc" }, { offsetMinutes: "asc" }] }),
    getSettings(),
    db.emailSend.findMany({ orderBy: { createdAt: "desc" }, take: 60, include: { subscriber: { select: { email: true } } } }),
    db.$queryRaw<{ templateKey: string; type: string; n: bigint }[]>`
      SELECT s."templateKey", e.type, count(DISTINCT e."providerId")::bigint n FROM "EmailEvent" e JOIN "EmailSend" s ON s.id = e."sendId" WHERE s.kind <> 'TEST' GROUP BY 1, 2`,
    db.emailSend.groupBy({ by: ["templateKey", "status"], where: { kind: { not: "TEST" } }, _count: { _all: true } }),
    db.subscriber.count({ where: { status: "CONFIRMED", marketingConsent: true } }),
  ]);
  const byKey = new Map<string, typeof templates>();
  for (const t of templates) byKey.set(t.key, [...(byKey.get(t.key) ?? []), t]);
  const ev = (key: string, type: string) => Number(eventRows.find((e) => e.templateKey === key && e.type === type)?.n ?? 0);
  const count = (key: string, status: string) => sendCounts.find((c) => c.templateKey === key && c.status === status)?._count._all ?? 0;
  const canSend = can(admin.role, "emails.send");
  const stepKeys = new Set(steps.map((s) => s.templateKey));

  return (
    <>
      <PageTitle
        title="E-mails"
        text={`${fmtNum(recipients)} destinataire${recipients > 1 ? "s" : ""} possible${recipients > 1 ? "s" : ""} : adresses confirmées, avec consentement en cours. Les séquences ne sont jamais envoyées à quelqu'un d'autre. Elles partent automatiquement via la tâche planifiée du serveur.`}
        actions={canSend ? <form action={runAutomationAction}><Submit className="adm-btn adm-btn-ghost" confirm="Envoyer maintenant tous les e-mails arrivés à échéance ?">Lancer les envois dus maintenant</Submit></form> : null}
      />
      <Flash params={params} />
      {params.ran != null && <p role="status" className="mb-6 text-sm text-ash">Dernier passage : {params.ran} envoyé(s), {params.failed ?? 0} en échec.</p>}
      {!settings.postalAddress && <p className="mb-6 rounded-lg border border-[#ffc46b]/40 bg-[#ffc46b]/10 px-4 py-3 text-sm text-[#ffc46b]">Adresse postale absente (Paramètres → Identité légale) : elle est obligatoire dans le pied des e-mails marketing envoyés vers les États-Unis.</p>}

      <div className="space-y-4">
        {Object.entries(SERIES).map(([series, [title, hint]]) => {
          const keys = [...byKey.keys()].filter((k) => byKey.get(k)![0].series === series);
          if (keys.length === 0) return null;
          const ordered = keys.sort((a, b) => (steps.find((s) => s.templateKey === a)?.offsetMinutes ?? 0) - (steps.find((s) => s.templateKey === b)?.offsetMinutes ?? 0));
          return (
            <Card key={series} title={title}>
              <p className="-mt-2 mb-4 text-xs text-smoke">{hint}</p>
              <div className="overflow-x-auto">
                <table className="adm-table">
                  <thead><tr><th>Modèle</th><th>Langues</th><th>Déclenchement</th><th className="num">Envoyés</th><th className="num">Délivrés</th><th className="num">Ouverts</th><th className="num">Clics</th><th className="num">Rejets</th><th className="num">Échecs</th></tr></thead>
                  <tbody>
                    {ordered.map((key) => {
                      const list = byKey.get(key)!;
                      const step = steps.find((s) => s.templateKey === key);
                      const at = step && series !== "WELCOME" && settings.launchAt ? new Date(settings.launchAt.getTime() + step.offsetMinutes * 60000) : null;
                      const sent = count(key, "SENT");
                      return (
                        <tr key={key}>
                          <td><Link href={`/admin/emails/${key}`} className="text-white underline decoration-line underline-offset-4 hover:text-cyan">{list[0].name}</Link><br /><span className="text-xs text-smoke">{list.find((t) => t.locale === "en")?.subject}</span></td>
                          <td className="text-xs uppercase text-ash">{list.map((t) => t.locale).join(" ")}</td>
                          <td className="text-xs">
                            {step ? (
                              <form action={saveStepAction} className="flex flex-wrap items-center gap-1.5">
                                <input type="hidden" name="id" value={step.id} />
                                <span className="w-24 text-ash">{describeOffset(series, step.offsetMinutes)}</span>
                                <input name="amount" type="number" min={0} defaultValue={Math.abs(step.offsetMinutes) % 1440 === 0 ? Math.abs(step.offsetMinutes) / 1440 : Math.round(Math.abs(step.offsetMinutes) / 60)} aria-label="Délai" className="field !min-h-8 w-16 !px-2 !py-1" />
                                <select name="unit" defaultValue={Math.abs(step.offsetMinutes) % 1440 === 0 ? "days" : "hours"} aria-label="Unité" className="field !min-h-8 w-20 !px-2 !py-1"><option value="days">jours</option><option value="hours">heures</option></select>
                                {series === "WELCOME" ? <input type="hidden" name="direction" value="after" /> : (
                                  <select name="direction" defaultValue={step.offsetMinutes < 0 ? "before" : "after"} aria-label="Sens" className="field !min-h-8 w-24 !px-2 !py-1"><option value="before">avant</option><option value="after">après</option></select>
                                )}
                                <label className="flex items-center gap-1.5"><input type="checkbox" name="active" defaultChecked={step.active} className="checkbox !h-4 !w-4" />actif</label>
                                <button className="adm-btn adm-btn-ghost adm-btn-sm">OK</button>
                                {at && <span className="basis-full text-smoke">{fmtDate(at)}</span>}
                              </form>
                            ) : <span className="text-smoke">Immédiat</span>}
                          </td>
                          <td className="num">{fmtNum(sent)}</td>
                          <td className="num">{fmtNum(ev(key, "delivered"))}</td>
                          <td className="num">{fmtNum(ev(key, "opened"))}<br /><span className="text-xs text-smoke">{fmtPct(ev(key, "opened"), ev(key, "delivered"))}</span></td>
                          <td className="num">{fmtNum(ev(key, "clicked"))}<br /><span className="text-xs text-smoke">{fmtPct(ev(key, "clicked"), ev(key, "delivered"))}</span></td>
                          <td className="num">{fmtNum(ev(key, "bounced"))}</td>
                          <td className="num">{fmtNum(count(key, "FAILED"))}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          );
        })}
      </div>
      <p className="mt-3 text-xs text-smoke">Délivrés, ouverts, clics et rejets sont comptés à partir des événements transmis par le fournisseur d&apos;e-mail — jamais estimés. {stepKeys.size} étapes programmées.</p>

      <Card title="Derniers envois" className="mt-6">
        {sends.length === 0 ? <Empty>Aucun envoi pour l&apos;instant.</Empty> : (
          <div className="overflow-x-auto">
            <table className="adm-table">
              <thead><tr><th>Date</th><th>Destinataire</th><th>Modèle</th><th>Type</th><th>Statut</th><th>Erreur</th></tr></thead>
              <tbody>
                {sends.map((s) => (
                  <tr key={s.id}>
                    <td className="whitespace-nowrap text-xs text-ash">{fmtDate(s.createdAt)}</td>
                    <td className="text-xs">{s.subscriber?.email ?? (s.kind === "TEST" ? "adresse de test" : "prospect supprimé")}</td>
                    <td className="text-xs">{s.templateKey} <span className="uppercase text-smoke">{s.locale}</span></td>
                    <td>{s.kind === "TEST" ? <Badge>Test</Badge> : <span className="text-xs text-smoke">{s.kind === "TRANSACTIONAL" ? "Transactionnel" : "Séquence"}</span>}</td>
                    <td><StatusBadge status={s.status} /></td>
                    <td className="max-w-64 text-xs text-[#ff8a9a]">{s.error}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
