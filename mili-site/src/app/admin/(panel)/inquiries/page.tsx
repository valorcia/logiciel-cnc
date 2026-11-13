import { Card, Empty, Flash, fmtDate, PageTitle, StatusBadge } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";
import { updateInquiryAction } from "../../actions/people";

export const metadata = { title: "Messages & RGPD" };
const KINDS: Record<string, string> = {
  GENERAL: "Question", PRESS: "Presse", PARTNERSHIP: "Partenariat", GDPR_ACCESS: "RGPD — accès", GDPR_DELETION: "RGPD — suppression",
  GDPR_RECTIFICATION: "RGPD — rectification", GDPR_OBJECTION: "RGPD — opposition",
};

export default async function InquiriesPage({ searchParams }: { searchParams: Promise<{ all?: string; ok?: string; error?: string }> }) {
  await requireAdmin("inquiries.manage");
  const params = await searchParams;
  const rows = await db.inquiry.findMany({ where: params.all ? {} : { status: { in: ["OPEN", "IN_PROGRESS"] } }, orderBy: { createdAt: "desc" }, take: 200 });
  return (
    <>
      <PageTitle
        title="Messages & demandes RGPD"
        text="Une demande RGPD doit recevoir une réponse sous un mois. Vérifiez que l'adresse appartient bien au demandeur avant toute suppression ; la suppression elle-même se fait depuis Prospects."
        actions={<a className="adm-btn adm-btn-ghost" href={params.all ? "/admin/inquiries" : "/admin/inquiries?all=1"}>{params.all ? "Seulement les ouverts" : "Tout afficher"}</a>}
      />
      <Flash params={params} />
      {rows.length === 0 ? <Empty>Aucun message en attente.</Empty> : (
        <div className="space-y-3">
          {rows.map((m) => (
            <Card key={m.id}>
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <StatusBadge status={m.status} />
                <strong className={m.kind.startsWith("GDPR") ? "text-[#ffc46b]" : ""}>{KINDS[m.kind] ?? m.kind}</strong>
                <a href={`mailto:${m.email}`} className="underline underline-offset-4">{m.email}</a>
                {m.name && <span className="text-ash">{m.name}</span>}
                <span className="ml-auto text-xs text-smoke">{fmtDate(m.createdAt)} · {m.locale}</span>
              </div>
              <p className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-ash">{m.message}</p>
              <form action={updateInquiryAction} className="mt-5 grid gap-3 border-t border-line pt-4 sm:grid-cols-[12rem_1fr_auto]">
                <input type="hidden" name="id" value={m.id} />
                <select name="status" defaultValue={m.status} aria-label="Statut" className="field">
                  <option value="OPEN">Ouvert</option><option value="IN_PROGRESS">En cours</option><option value="DONE">Traité</option><option value="REJECTED">Refusé</option>
                </select>
                <input name="note" defaultValue={m.note ?? ""} placeholder="Note interne (ce qui a été fait)" aria-label="Note interne" className="field" />
                <button className="adm-btn">Enregistrer</button>
              </form>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
