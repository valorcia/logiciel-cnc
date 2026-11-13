import Link from "next/link";
import { Card, Empty, Flash, fmtDate, PageTitle, StatusBadge } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";

export const metadata = { title: "Journal" };

export default async function JournalAdminPage({ searchParams }: { searchParams: Promise<{ ok?: string; error?: string }> }) {
  await requireAdmin("journal.edit");
  const articles = await db.article.findMany({ orderBy: { updatedAt: "desc" }, take: 300 });
  return (
    <>
      <PageTitle title="Journal" text="Articles de fond pour le référencement. Chaque article est écrit dans une langue ; pour le traduire, créez un article avec la même adresse (slug) dans l'autre langue : les deux seront reliés automatiquement (hreflang)." actions={<Link href="/admin/journal/new" className="adm-btn">Nouvel article</Link>} />
      <Flash params={await searchParams} />
      <Card>
        {articles.length === 0 ? <Empty>Aucun article pour l&apos;instant.</Empty> : (
          <table className="adm-table">
            <thead><tr><th>Titre</th><th>Langue</th><th>Catégorie</th><th>Statut</th><th>Publication</th></tr></thead>
            <tbody>
              {articles.map((a) => (
                <tr key={a.id}>
                  <td><Link href={`/admin/journal/${a.id}`} className="text-white underline decoration-line underline-offset-4 hover:text-cyan">{a.title}</Link><br /><span className="font-mono text-xs text-smoke">/journal/{a.slug}</span></td>
                  <td className="uppercase">{a.locale}</td><td className="text-xs text-ash">{a.category}</td><td><StatusBadge status={a.status} /></td>
                  <td className="text-xs text-ash">{fmtDate(a.publishAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
