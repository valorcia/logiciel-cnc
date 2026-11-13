import Link from "next/link";
import { Card, Empty, fmtDate, PageTitle } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";

export const metadata = { title: "Journal d'activité" };
const PAGE = 100;

export default async function AuditPage({ searchParams }: { searchParams: Promise<{ page?: string; q?: string }> }) {
  await requireAdmin("audit.view");
  const params = await searchParams;
  const page = Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1);
  const q = params.q?.trim().slice(0, 80);
  const where = q ? { OR: [{ action: { contains: q, mode: "insensitive" as const } }, { actorEmail: { contains: q, mode: "insensitive" as const } }, { entity: { contains: q, mode: "insensitive" as const } }] } : {};
  const [rows, total] = await Promise.all([
    db.auditLog.findMany({ where, orderBy: { createdAt: "desc" }, skip: (page - 1) * PAGE, take: PAGE }),
    db.auditLog.count({ where }),
  ]);
  return (
    <>
      <PageTitle title="Journal d'activité" text="Chaque modification faite dans le back-office : qui, quoi, quand. Les entrées ne peuvent être ni modifiées ni supprimées depuis l'interface." />
      <form method="get" className="mb-4 flex gap-2"><input name="q" defaultValue={q ?? ""} placeholder="Filtrer : action, e-mail, type d'objet" aria-label="Filtrer" className="field max-w-md" /><button className="adm-btn">Filtrer</button></form>
      <Card>
        {rows.length === 0 ? <Empty>Aucune entrée.</Empty> : (
          <div className="overflow-x-auto">
            <table className="adm-table">
              <thead><tr><th>Date</th><th>Auteur</th><th>Action</th><th>Objet</th><th>Détails</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className="whitespace-nowrap text-xs text-ash">{fmtDate(r.createdAt)}</td>
                    <td className="text-xs">{r.actorEmail ?? "—"}</td>
                    <td className="font-mono text-xs text-cyan">{r.action}</td>
                    <td className="text-xs text-ash">{r.entity}{r.entityId ? <span className="text-smoke"> · {r.entityId.slice(0, 12)}</span> : null}</td>
                    <td className="font-mono text-xs text-smoke">{Object.keys(r.meta as object).length ? JSON.stringify(r.meta) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <nav className="mt-4 flex items-center gap-3 text-sm">
        {page > 1 && <Link className="adm-btn adm-btn-ghost adm-btn-sm" href={`/admin/audit?page=${page - 1}${q ? `&q=${encodeURIComponent(q)}` : ""}`}>← Plus récent</Link>}
        <span className="text-smoke">{total} entrées</span>
        {page * PAGE < total && <Link className="adm-btn adm-btn-ghost adm-btn-sm" href={`/admin/audit?page=${page + 1}${q ? `&q=${encodeURIComponent(q)}` : ""}`}>Plus ancien →</Link>}
      </nav>
    </>
  );
}
