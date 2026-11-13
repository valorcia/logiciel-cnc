import Link from "next/link";
import { BarChart } from "@/components/admin/bar-chart";
import { Card, Empty, Flash, fmtNum, fmtPct, PageTitle } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { dashboardStats, rangeOf } from "@/lib/admin-stats";
import { countryName } from "@/lib/countries";
import { getSettings } from "@/lib/settings";

export const metadata = { title: "Tableau de bord" };
const RANGES = [7, 30, 90, 365] as const;

type Props = { searchParams: Promise<{ days?: string; source?: string; ok?: string; error?: string; denied?: string }> };

export default async function DashboardPage({ searchParams }: Props) {
  await requireAdmin("dashboard.view");
  const params = await searchParams;
  const days = RANGES.find((d) => String(d) === params.days) ?? 30;
  const source = params.source?.slice(0, 120) || undefined;
  const [stats, settings] = await Promise.all([dashboardStats(rangeOf(days), source), getSettings()]);
  const href = (d: number, s?: string) => `/admin?days=${d}${s ? `&source=${encodeURIComponent(s)}` : ""}`;

  const tiles: [string, string, string?][] = [
    ["Visiteurs", fmtNum(stats.visitors), "Visiteurs uniques par jour, sans cookie"],
    ["Inscriptions", fmtNum(stats.signups), `${fmtNum(stats.confirmed)} confirmées sur la période`],
    ["Taux de conversion", fmtPct(stats.signups, stats.visitors), "Inscriptions ÷ visiteurs"],
    ["Taux de confirmation", fmtPct(stats.confirmed, stats.signups), "Double opt-in validé"],
    ["Parrainages", fmtNum(stats.referrals), "Filleuls confirmés, hors signalements"],
    ["Désinscriptions", fmtNum(stats.unsubscribed)],
    ["E-mails envoyés", fmtNum(stats.emails.sent), `${fmtNum(stats.emails.delivered)} délivrés`],
    ["Taux d'ouverture", fmtPct(stats.emails.opened, stats.emails.delivered), "Ouvertures ÷ délivrés"],
    ["Taux de clic", fmtPct(stats.emails.clicked, stats.emails.delivered), "Clics ÷ délivrés"],
  ];

  return (
    <>
      <PageTitle
        title="Tableau de bord"
        text={`${fmtNum(stats.totalConfirmed)} Insiders confirmés au total. ${settings.launchAt ? "" : "Aucune date de lancement n'est encore définie — le compte à rebours reste masqué."}`}
      />
      <Flash params={params} />

      <div className="mb-6 flex flex-wrap items-center gap-2" role="group" aria-label="Période">
        {RANGES.map((d) => (
          <Link key={d} href={href(d, source)} aria-current={d === days ? "true" : undefined} className={`adm-btn adm-btn-sm ${d === days ? "" : "adm-btn-ghost"}`}>
            {d === 365 ? "12 mois" : `${d} jours`}
          </Link>
        ))}
        {source && (
          <Link href={href(days)} className="adm-badge adm-badge-ok ml-2">Source : {source} ✕</Link>
        )}
      </div>

      <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {tiles.map(([label, value, hint]) => (
          <div key={label} className="adm-card">
            <dt className="text-xs uppercase tracking-[0.12em] text-smoke">{label}</dt>
            <dd className="mt-2 text-4xl font-semibold tracking-tight tabular-nums">{value}</dd>
            {hint && <p className="mt-1.5 text-xs text-smoke">{hint}</p>}
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-smoke">
        Les statistiques d&apos;e-mail proviennent uniquement des événements transmis par le fournisseur (webhooks). Un tiret signifie qu&apos;aucune donnée n&apos;a été reçue. Les ouvertures sont sous-estimées ou surestimées par certaines messageries.
      </p>

      <div className="mt-6 grid gap-3 xl:grid-cols-2">
        <Card><BarChart title="Visiteurs" points={stats.daily.map((d) => ({ day: d.day, value: d.visitors }))} /></Card>
        <Card><BarChart title="Inscriptions" points={stats.daily.map((d) => ({ day: d.day, value: d.signups }))} color="#7856FF" /></Card>
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-[1.4fr_1fr]">
        <Card title="Sources de trafic">
          {stats.sources.length === 0 ? <Empty>Aucune visite sur la période.</Empty> : (
            <div className="overflow-x-auto">
              <table className="adm-table">
                <thead><tr><th>Source</th><th className="num">Visiteurs</th><th className="num">Inscriptions</th><th className="num">Confirmées</th><th className="num">Conversion</th></tr></thead>
                <tbody>
                  {stats.sources.map((s) => (
                    <tr key={s.source}>
                      <td><Link href={href(days, s.source)} className="underline decoration-line underline-offset-4 hover:text-cyan">{s.source}</Link></td>
                      <td className="num">{fmtNum(s.visitors)}</td><td className="num">{fmtNum(s.signups)}</td><td className="num">{fmtNum(s.confirmed)}</td>
                      <td className="num">{fmtPct(s.signups, s.visitors)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card title="Pays des inscrits">
          {stats.countries.length === 0 ? <Empty>Aucun pays renseigné sur la période (champ facultatif).</Empty> : (
            <table className="adm-table">
              <thead><tr><th>Pays</th><th className="num">Inscriptions</th></tr></thead>
              <tbody>{stats.countries.map((c) => <tr key={c.country}><td>{countryName(c.country, "fr")}</td><td className="num">{fmtNum(c.signups)}</td></tr>)}</tbody>
            </table>
          )}
        </Card>
      </div>

      <Card title="Campagnes UTM" className="mt-3">
        {stats.utm.length === 0 ? <Empty>Aucun lien de campagne (paramètres utm_…) n&apos;a encore amené de visite.</Empty> : (
          <div className="overflow-x-auto">
            <table className="adm-table">
              <thead><tr><th>Campagne</th><th>Source</th><th>Support</th><th className="num">Visiteurs</th><th className="num">Inscriptions</th><th className="num">Confirmées</th><th className="num">Conversion</th></tr></thead>
              <tbody>
                {stats.utm.map((u) => (
                  <tr key={`${u.campaign}|${u.source}|${u.medium}`}>
                    <td>{u.campaign || "—"}</td><td>{u.source || "—"}</td><td>{u.medium || "—"}</td>
                    <td className="num">{fmtNum(u.visitors)}</td><td className="num">{fmtNum(u.signups)}</td><td className="num">{fmtNum(u.confirmed)}</td>
                    <td className="num">{fmtPct(u.signups, u.visitors)}</td>
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
