import { Submit } from "@/components/admin/client";
import { MediaSelect, mediaOptions, STATUS_OPTIONS } from "@/components/admin/pickers";
import { Card, Field, Flash, fmtDate, LocalizedField, PageTitle, Select, StatusBadge } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";
import { pickText } from "@/lib/i18n/config";
import { nowMs } from "@/lib/time";
import { toInputDateTime } from "../../_lib/form";
import { deleteClueAction, saveClueAction } from "../../actions/content";

export const metadata = { title: "Indices" };

export default async function CluesPage({ searchParams }: { searchParams: Promise<{ ok?: string; error?: string }> }) {
  await requireAdmin("clues.edit");
  const [clues, media] = await Promise.all([db.clue.findMany({ orderBy: { number: "asc" } }), mediaOptions()]);
  const next = (clues.at(-1)?.number ?? 0) + 1;
  const now = nowMs();
  return (
    <>
      <PageTitle title="Indices" text="Un indice « Programmé » s'ouvre tout seul à sa date. Avant cette date, ni son titre ni son contenu ne sont envoyés au navigateur des visiteurs. Un indice doit intriguer sans rien dévoiler : aucune caractéristique technique, aucune image de la machine." />
      <Flash params={await searchParams} />
      <div className="space-y-3">
        {[...clues, null].map((c) => {
          const live = c && (c.status === "PUBLISHED" || (c.status === "SCHEDULED" && c.publishAt && c.publishAt.getTime() <= now)) && (!c.publishAt || c.publishAt.getTime() <= now);
          return (
            <Card key={c?.id ?? "new"}>
              <details open={!c && clues.length === 0}>
                <summary className="flex flex-wrap items-center gap-3">
                  {c ? (
                    <>
                      <span className="font-mono text-cyan">#{String(c.number).padStart(2, "0")}</span>
                      <span className="font-medium text-white">{pickText(c.title, "en")}</span>
                      <StatusBadge status={c.status} />
                      <span className="text-xs text-smoke">{live ? "Visible sur le site" : c.publishAt ? `Ouverture : ${fmtDate(c.publishAt)}` : "Non visible"}</span>
                    </>
                  ) : <span className="font-medium text-white">+ Ajouter un indice</span>}
                </summary>
                <form action={saveClueAction} className="mt-5 grid gap-4 lg:grid-cols-2">
                  <input type="hidden" name="id" value={c?.id ?? ""} />
                  <LocalizedField label="Titre" name="title" value={c?.title} required />
                  <LocalizedField label="Contenu" name="content" value={c?.content} rows={2} />
                  <Field label="Numéro" name="number" type="number" min={1} defaultValue={c?.number ?? next} required />
                  <Select label="Statut" name="status" defaultValue={c?.status ?? "DRAFT"} options={STATUS_OPTIONS} />
                  <Field label="Date d'ouverture (UTC)" name="publishAt" type="datetime-local" defaultValue={toInputDateTime(c?.publishAt)} help="Requise pour « Programmé ». Laissée vide avec « Publié » : visible immédiatement." />
                  <Field label="Lien vidéo (facultatif)" name="videoUrl" type="url" defaultValue={c?.videoUrl} placeholder="https://" />
                  <MediaSelect label="Image (facultative)" name="imageId" value={c?.imageId} media={media} publicOnly />
                  <div className="flex items-end"><button className="adm-btn">{c ? "Enregistrer" : "Créer l'indice"}</button></div>
                </form>
                {c && (
                  <form action={deleteClueAction} className="mt-3">
                    <input type="hidden" name="id" value={c.id} />
                    <Submit className="adm-btn adm-btn-danger adm-btn-sm" confirm={`Supprimer l'indice #${c.number} ?`}>Supprimer</Submit>
                  </form>
                )}
              </details>
            </Card>
          );
        })}
      </div>
    </>
  );
}
