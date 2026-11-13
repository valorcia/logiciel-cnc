import { Submit } from "@/components/admin/client";
import { Badge, Card, Check, Field, Flash, LocalizedField, PageTitle, Select } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";
import { pickText } from "@/lib/i18n/config";
import { deleteFaqAction, saveFaqAction } from "../../actions/content";

export const metadata = { title: "FAQ" };
const SCOPES = [["MYSTERY", "Pendant le mystère"], ["REVEAL", "Après la révélation"], ["BOTH", "Toujours"]] as const;

export default async function FaqPage({ searchParams }: { searchParams: Promise<{ ok?: string; error?: string }> }) {
  await requireAdmin("content.edit");
  const faqs = await db.faq.findMany({ orderBy: [{ scope: "asc" }, { sortOrder: "asc" }] });
  return (
    <>
      <PageTitle title="FAQ" text="Les questions « Après la révélation » ne sont jamais envoyées aux visiteurs tant que le site est en mode Mystery. N'y répondez par des chiffres (délais, dimensions, matériaux…) qu'une fois ceux-ci validés." />
      <Flash params={await searchParams} />
      <div className="space-y-3">
        {[...faqs, null].map((f) => (
          <Card key={f?.id ?? "new"}>
            <details>
              <summary className="flex flex-wrap items-center gap-3">
                {f ? (
                  <>
                    <span className="font-medium text-white">{pickText(f.question, "en")}</span>
                    <Badge tone={f.scope === "REVEAL" ? "warn" : "neutral"}>{SCOPES.find(([k]) => k === f.scope)?.[1]}</Badge>
                    {!f.published && <Badge>Masquée</Badge>}
                  </>
                ) : <span className="font-medium text-white">+ Ajouter une question</span>}
              </summary>
              <form action={saveFaqAction} className="mt-5 grid gap-4 lg:grid-cols-2">
                <input type="hidden" name="id" value={f?.id ?? ""} />
                <LocalizedField label="Question" name="question" value={f?.question} required />
                <LocalizedField label="Réponse" name="answer" value={f?.answer} rows={3} required />
                <Select label="Affichage" name="scope" defaultValue={f?.scope ?? "MYSTERY"} options={SCOPES} />
                <Field label="Ordre" name="sortOrder" type="number" defaultValue={f?.sortOrder ?? faqs.length} />
                <Check label="Publiée" name="published" defaultChecked={f?.published ?? true} />
                <div><button className="adm-btn">{f ? "Enregistrer" : "Ajouter"}</button></div>
              </form>
              {f && (
                <form action={deleteFaqAction} className="mt-3">
                  <input type="hidden" name="id" value={f.id} />
                  <Submit className="adm-btn adm-btn-danger adm-btn-sm" confirm="Supprimer cette question ?">Supprimer</Submit>
                </form>
              )}
            </details>
          </Card>
        ))}
      </div>
    </>
  );
}
