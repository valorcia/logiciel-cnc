import { Submit } from "@/components/admin/client";
import { Badge, Card, Empty, Field, Flash, LocalizedField, PageTitle, Select } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";
import { maxUploadBytes } from "@/lib/storage";
import { deleteMediaAction, updateMediaAction, uploadMediaAction } from "../../actions/content";

export const metadata = { title: "Médias" };
const PLACEMENTS = [["OTHER", "Autre"], ["CLUE", "Indice"], ["POSTER", "Miniature vidéo"], ["ARTICLE", "Article du journal"], ["GALLERY", "Galerie de la fiche produit"], ["HERO_IMAGE", "Image principale de la fiche produit"]] as const;
const VISIBILITY = [["REVEAL_ONLY", "Confidentielle — invisible jusqu'à la révélation"], ["PUBLIC", "Publique — visible dès maintenant"]] as const;

export default async function MediaPage({ searchParams }: { searchParams: Promise<{ ok?: string; error?: string }> }) {
  await requireAdmin("media.manage");
  const assets = await db.mediaAsset.findMany({ orderBy: { createdAt: "desc" }, take: 300 });
  const maxMb = Math.floor(maxUploadBytes() / 1024 / 1024);
  return (
    <>
      <PageTitle
        title="Médias"
        text="Les images sont rangées dans un espace privé, jamais dans un dossier public. Une image « confidentielle » répond « introuvable » à tout visiteur tant que le site est en mode Mystery — même à qui connaîtrait son adresse. Toute photo ou rendu de la machine doit rester confidentiel. Les vidéos ne se déposent pas ici : elles sont hébergées chez un service de streaming et référencées par leur lien."
      />
      <Flash params={await searchParams} />
      <Card title="Ajouter une image">
        <form action={uploadMediaAction} className="grid gap-4 lg:grid-cols-2">
          <div>
            <label htmlFor="media-file" className="field-label">Fichier <span className="text-cyan">*</span></label>
            <input id="media-file" name="file" type="file" required accept=".jpg,.jpeg,.png,.webp" className="block w-full text-sm text-ash file:mr-4 file:rounded-md file:border file:border-solid file:border-line file:bg-transparent file:px-3 file:py-2 file:text-white" />
            <p className="mt-1.5 text-xs text-smoke">JPG, PNG ou WebP — {maxMb} Mo maximum. Exportez en 2 400 px de large au plus.</p>
          </div>
          <Select label="Visibilité" name="visibility" defaultValue="REVEAL_ONLY" options={VISIBILITY} />
          <Select label="Emplacement" name="placement" defaultValue="OTHER" options={PLACEMENTS} />
          <Field label="Ordre" name="sortOrder" type="number" defaultValue={0} />
          <LocalizedField label="Texte alternatif (accessibilité et SEO)" name="alt" />
          <div className="flex items-end"><button className="adm-btn">Envoyer</button></div>
        </form>
      </Card>

      <h2 className="mb-3 mt-10">Bibliothèque</h2>
      {assets.length === 0 ? <Empty>Aucune image.</Empty> : (
        <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
          {assets.map((m) => (
            <Card key={m.id}>
              <div className="flex gap-4">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={`/media/${m.id}`} alt="" loading="lazy" className="h-24 w-32 flex-none rounded-md border border-line object-cover" />
                <div className="min-w-0 text-xs">
                  <p className="truncate text-sm text-white">{m.fileName}</p>
                  <p className="mt-1 text-smoke">{Math.round(m.size / 1024)} Ko · {m.mime}</p>
                  <p className="mt-2"><Badge tone={m.visibility === "PUBLIC" ? "ok" : "warn"}>{m.visibility === "PUBLIC" ? "Publique" : "Confidentielle"}</Badge></p>
                  <p className="mt-2 select-all font-mono text-smoke">/media/{m.id}</p>
                </div>
              </div>
              <details className="mt-4">
                <summary className="text-xs text-ash">Modifier</summary>
                <form action={updateMediaAction} className="mt-3 space-y-3">
                  <input type="hidden" name="id" value={m.id} />
                  <Select label="Visibilité" name="visibility" defaultValue={m.visibility} options={VISIBILITY} />
                  <Select label="Emplacement" name="placement" defaultValue={m.placement} options={PLACEMENTS} />
                  <Field label="Ordre" name="sortOrder" type="number" defaultValue={m.sortOrder} />
                  <LocalizedField label="Texte alternatif" name="alt" value={m.alt} />
                  <button className="adm-btn adm-btn-sm">Enregistrer</button>
                </form>
                <form action={deleteMediaAction} className="mt-3">
                  <input type="hidden" name="id" value={m.id} />
                  <Submit className="adm-btn adm-btn-danger adm-btn-sm" confirm="Supprimer cette image ? Elle disparaîtra de tous les contenus qui l'utilisent.">Supprimer</Submit>
                </form>
              </details>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
