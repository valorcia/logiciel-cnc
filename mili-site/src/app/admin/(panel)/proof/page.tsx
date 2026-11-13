import { Submit } from "@/components/admin/client";
import { MediaSelect, mediaOptions, STATUS_OPTIONS } from "@/components/admin/pickers";
import { Badge, Card, Check, Field, Flash, fmtDate, LocalizedField, PageTitle, Select, StatusBadge } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";
import { pickText } from "@/lib/i18n/config";
import { can } from "@/lib/permissions";
import { toInputDate } from "../../_lib/form";
import { deleteProofAction, saveProofAction } from "../../actions/content";

export const metadata = { title: "Vidéos de preuve" };
const CATEGORIES = [["PRECISION", "Precision"], ["COMPLEX_GEOMETRY", "Complex Geometry"], ["FIVE_AXIS", "5-Axis Machining"], ["SURFACE_FINISH", "Surface Finish"], ["MATERIALS", "Materials"]] as const;

export default async function ProofPage({ searchParams }: { searchParams: Promise<{ ok?: string; error?: string }> }) {
  const admin = await requireAdmin("proof.edit");
  const [videos, media] = await Promise.all([db.proofVideo.findMany({ orderBy: [{ sortOrder: "asc" }, { createdAt: "desc" }] }), mediaOptions()]);
  const mayValidate = can(admin.role, "proof.validate");
  return (
    <>
      <PageTitle
        title="Vidéos de preuve"
        text="Section « DON'T BELIEVE IT? ». Règle absolue : uniquement des pièces réellement usinées sur le prototype MILLI, cadrées sans montrer la machine tant que le mystère dure. Une vidéo n'apparaît sur le site que si elle est à la fois validée techniquement (Super Admin) et publiée. Sans aucune vidéo validée, le site affiche un message d'attente neutre."
      />
      <Flash params={await searchParams} />
      <div className="space-y-3">
        {[...videos, null].map((v) => (
          <Card key={v?.id ?? "new"}>
            <details open={!v && videos.length === 0}>
              <summary className="flex flex-wrap items-center gap-3">
                {v ? (
                  <>
                    <span className="font-medium text-white">{pickText(v.title, "en")}</span>
                    <StatusBadge status={v.status} />
                    {v.validated ? <Badge tone="ok">Validée techniquement</Badge> : <Badge tone="warn">Non validée</Badge>}
                    <span className="text-xs text-smoke">{v.validated && v.status === "PUBLISHED" ? "Visible sur le site" : "Non visible"}{v.validatedAt ? ` · validée le ${fmtDate(v.validatedAt)}` : ""}</span>
                  </>
                ) : <span className="font-medium text-white">+ Ajouter une vidéo</span>}
              </summary>
              <form action={saveProofAction} className="mt-5 grid gap-4 lg:grid-cols-2">
                <input type="hidden" name="id" value={v?.id ?? ""} />
                <LocalizedField label="Titre" name="title" value={v?.title} required />
                <LocalizedField label="Description" name="description" value={v?.description} rows={2} help="Décrivez ce que l'on voit. Aucune performance chiffrée qui n'ait été mesurée et validée." />
                <Field label="Lien de la vidéo" name="videoUrl" type="url" defaultValue={v?.videoUrl} required placeholder="https://" help="YouTube, Vimeo, Bunny Stream, Cloudflare Stream, Mux, ou fichier .mp4/.webm. La vidéo n'est chargée chez le visiteur qu'au clic." />
                <Select label="Catégorie" name="category" defaultValue={v?.category ?? "FIVE_AXIS"} options={CATEGORIES} />
                <MediaSelect label="Miniature" name="posterId" value={v?.posterId} media={media} publicOnly />
                <Field label="Durée (secondes)" name="durationSec" type="number" min={1} defaultValue={v?.durationSec} />
                <Field label="Date de tournage" name="recordedAt" type="date" defaultValue={toInputDate(v?.recordedAt)} />
                <Field label="Ordre d'affichage" name="sortOrder" type="number" defaultValue={v?.sortOrder ?? 0} />
                <Select label="Statut" name="status" defaultValue={v?.status === "SCHEDULED" ? "DRAFT" : (v?.status ?? "DRAFT")} options={STATUS_OPTIONS.filter(([k]) => k !== "SCHEDULED")} />
                {mayValidate ? (
                  <Check label="Validation technique" name="validated" defaultChecked={v?.validated} help="Je certifie que cette vidéo montre une pièce usinée sur le prototype MILLI, qu'elle ne dévoile pas la machine, et que ce qu'elle affirme est exact." />
                ) : (
                  <p className="text-sm text-smoke">La validation technique est réservée aux Super Admins. Enregistrez en brouillon, puis demandez la validation.</p>
                )}
                <div><button className="adm-btn">{v ? "Enregistrer" : "Ajouter la vidéo"}</button></div>
              </form>
              {v && (
                <form action={deleteProofAction} className="mt-3">
                  <input type="hidden" name="id" value={v.id} />
                  <Submit className="adm-btn adm-btn-danger adm-btn-sm" confirm="Supprimer cette vidéo ?">Supprimer</Submit>
                </form>
              )}
            </details>
          </Card>
        ))}
      </div>
    </>
  );
}
