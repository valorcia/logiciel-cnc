import Link from "next/link";
import { Submit } from "@/components/admin/client";
import { Badge, Card, Empty, Flash, fmtDate, fmtNum, PageTitle, StatusBadge } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { countryName } from "@/lib/countries";
import { db } from "@/lib/db";
import { can } from "@/lib/permissions";
import type { Prisma, SubscriberStatus } from "@/generated/prisma/client";
import { clearReferralFlagAction, deleteSubscriberAction } from "../../actions/people";

export const metadata = { title: "Prospects" };
const PAGE = 50;
const STATUSES = ["PENDING", "CONFIRMED", "UNSUBSCRIBED", "BOUNCED", "COMPLAINED"] as const;

type Props = { searchParams: Promise<{ q?: string; status?: string; country?: string; source?: string; flagged?: string; page?: string; ok?: string; error?: string }> };

export default async function ProspectsPage({ searchParams }: Props) {
  const admin = await requireAdmin("prospects.view");
  const params = await searchParams;
  const q = params.q?.trim().slice(0, 120) ?? "";
  const status = STATUSES.find((s) => s === params.status);
  const page = Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1);
  const where: Prisma.SubscriberWhereInput = {
    ...(q ? { OR: [{ email: { contains: q, mode: "insensitive" } }, { firstName: { contains: q, mode: "insensitive" } }, { publicId: { contains: q.toUpperCase() } }, { referralCode: q.toUpperCase() }] } : {}),
    ...(status ? { status: status as SubscriberStatus } : {}),
    ...(params.country ? { country: params.country.toUpperCase().slice(0, 2) } : {}),
    ...(params.source ? { utmSource: params.source.slice(0, 120) } : {}),
    ...(params.flagged ? { referralFlagged: true } : {}),
  };
  const [rows, total, flagged] = await Promise.all([
    db.subscriber.findMany({
      where, orderBy: { createdAt: "desc" }, skip: (page - 1) * PAGE, take: PAGE,
      include: { referredBy: { select: { publicId: true } }, _count: { select: { referrals: { where: { confirmedAt: { not: null }, referralFlagged: false } } } } },
    }),
    db.subscriber.count({ where }),
    db.subscriber.count({ where: { referralFlagged: true } }),
  ]);
  const query = new URLSearchParams(Object.entries({ q, status: status ?? "", country: params.country ?? "", source: params.source ?? "", flagged: params.flagged ?? "" }).filter(([, v]) => v));
  const canDelete = can(admin.role, "prospects.delete");
  const pages = Math.ceil(total / PAGE);

  return (
    <>
      <PageTitle
        title="Prospects" text={`${fmtNum(total)} résultat${total > 1 ? "s" : ""}. Les adresses IP ne sont jamais conservées en clair.`}
        actions={can(admin.role, "prospects.export") ? <a href={`/admin/prospects/export?${query}`} className="adm-btn adm-btn-ghost">Exporter en CSV</a> : null}
      />
      <Flash params={params} />

      <form className="adm-card mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr_1fr_auto]" method="get">
        <input name="q" defaultValue={q} placeholder="E-mail, prénom, identifiant, code de parrainage" aria-label="Recherche" className="field" />
        <select name="status" defaultValue={status ?? ""} aria-label="Statut" className="field">
          <option value="">Tous les statuts</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input name="country" defaultValue={params.country ?? ""} placeholder="Pays (FR, US…)" maxLength={2} aria-label="Pays" className="field" />
        <input name="source" defaultValue={params.source ?? ""} placeholder="Source UTM" aria-label="Source UTM" className="field" />
        <button type="submit" className="adm-btn">Filtrer</button>
      </form>
      {flagged > 0 && !params.flagged && (
        <p className="mb-4 text-sm"><Link href="/admin/prospects?flagged=1" className="text-[#ffc46b] underline underline-offset-4">{flagged} parrainage{flagged > 1 ? "s" : ""} à vérifier</Link></p>
      )}

      <Card>
        {rows.length === 0 ? <Empty>Aucun prospect ne correspond.</Empty> : (
          <div className="overflow-x-auto">
            <table className="adm-table">
              <thead><tr><th>Contact</th><th>Statut</th><th>Pays</th><th>Origine</th><th>Parrainage</th><th>Inscription</th><th /></tr></thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <span className="text-white">{s.email}</span>
                      <br /><span className="font-mono text-xs text-smoke">{s.publicId}{s.firstName ? ` · ${s.firstName}` : ""} · {s.locale}</span>
                    </td>
                    <td><StatusBadge status={s.status} /></td>
                    <td>{s.country ? countryName(s.country, "fr") : "—"}</td>
                    <td className="text-xs text-ash">
                      {s.utmSource ?? s.referrerHost ?? "direct"}{s.utmCampaign ? <><br /><span className="text-smoke">{s.utmCampaign}</span></> : null}
                    </td>
                    <td className="text-xs">
                      <span className="tabular-nums">{s._count.referrals}</span> filleul{s._count.referrals > 1 ? "s" : ""}
                      {s.referredBy && <><br /><span className="text-smoke">via {s.referredBy.publicId}</span></>}
                      {s.referralFlagged && (
                        <div className="mt-1.5">
                          <Badge tone="warn">À vérifier</Badge>
                          <p className="mt-1 max-w-48 text-smoke">{s.referralFlagNote}</p>
                          {canDelete && (
                            <form action={clearReferralFlagAction} className="mt-1.5 flex gap-1.5">
                              <input type="hidden" name="id" value={s.id} />
                              <button name="decision" value="accept" className="adm-btn adm-btn-ghost adm-btn-sm">Valider</button>
                              <button name="decision" value="reject" className="adm-btn adm-btn-danger adm-btn-sm">Refuser</button>
                            </form>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="whitespace-nowrap text-xs text-ash">{fmtDate(s.createdAt)}{s.confirmedAt ? <><br /><span className="text-smoke">confirmé {fmtDate(s.confirmedAt)}</span></> : null}</td>
                    <td>
                      {canDelete && (
                        <form action={deleteSubscriberAction}>
                          <input type="hidden" name="id" value={s.id} />
                          <Submit className="adm-btn adm-btn-danger adm-btn-sm" confirm={`Supprimer définitivement ${s.email} et tout son historique ? Cette action est irréversible.`}>Supprimer</Submit>
                        </form>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {pages > 1 && (
        <nav className="mt-4 flex items-center gap-3 text-sm" aria-label="Pagination">
          {page > 1 && <Link className="adm-btn adm-btn-ghost adm-btn-sm" href={`/admin/prospects?${query}&page=${page - 1}`}>← Précédent</Link>}
          <span className="text-smoke">Page {page} / {pages}</span>
          {page < pages && <Link className="adm-btn adm-btn-ghost adm-btn-sm" href={`/admin/prospects?${query}&page=${page + 1}`}>Suivant →</Link>}
        </nav>
      )}
    </>
  );
}
