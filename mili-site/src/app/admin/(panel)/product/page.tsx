import Link from "next/link";
import { Submit } from "@/components/admin/client";
import { Badge, Card, Check, Field, Flash, LocalizedField, PageTitle } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";
import { pickText } from "@/lib/i18n/config";
import { can } from "@/lib/permissions";
import { formatUsd, getSettings } from "@/lib/settings";
import { deleteProductRowAction, saveFilmAction, saveKitItemAction, saveSectionAction, saveSpecAction, saveTierAction } from "../../actions/product";

export const metadata = { title: "Fiche produit" };

function Delete({ id, kind, label }: { id: string; kind: string; label: string }) {
  return (
    <form action={deleteProductRowAction} className="mt-3">
      <input type="hidden" name="id" value={id} /><input type="hidden" name="kind" value={kind} />
      <Submit className="adm-btn adm-btn-danger adm-btn-sm" confirm={`Supprimer ${label} ?`}>Supprimer</Submit>
    </form>
  );
}

export default async function ProductAdminPage({ searchParams }: { searchParams: Promise<{ ok?: string; error?: string }> }) {
  const admin = await requireAdmin("product.edit");
  const [sections, specs, kit, tiers, settings] = await Promise.all([
    db.productSection.findMany({ orderBy: { sortOrder: "asc" } }),
    db.productSpec.findMany({ orderBy: { sortOrder: "asc" } }),
    db.kitItem.findMany({ orderBy: { sortOrder: "asc" } }),
    db.pledgeTier.findMany({ orderBy: { sortOrder: "asc" } }),
    getSettings(),
  ]);
  const mayValidate = can(admin.role, "product.validate");

  return (
    <>
      <PageTitle
        title="Fiche produit"
        text={`Tout ce qui est saisi ici est confidentiel : la page /milli n'existe pas pour les visiteurs (erreur 404) et rien de ce contenu ne leur est transmis tant que le site est en mode Mystery. Mode actuel : ${settings.mode === "REVEAL" ? "Reveal — les changements sont publics immédiatement" : "Mystery"}.`}
        actions={<Link href="/admin/reveal/preview" className="adm-btn adm-btn-ghost">Prévisualiser la page</Link>}
      />
      <Flash params={await searchParams} />
      <p className="mb-8 rounded-lg border border-line bg-carbon px-4 py-3 text-sm leading-relaxed text-ash">
        <strong className="text-white">Aucune valeur n&apos;est pré-remplie.</strong> Précision, puissance, vitesse, matériaux, capacités, dimensions, poids, délais : n&apos;écrivez que des valeurs mesurées. Une caractéristique n&apos;apparaît dans le tableau public qu&apos;une fois <em>validée</em> par un Super Admin ; une section sans texte n&apos;est pas affichée ; une récompense n&apos;est visible qu&apos;une fois activée.
      </p>

      <h2 id="film" className="mb-3 scroll-mt-8">Film officiel</h2>
      <Card>
        <form action={saveFilmAction} className="flex flex-wrap items-end gap-3">
          <div className="min-w-72 flex-1"><Field label="Lien du film" name="filmUrl" type="url" defaultValue={settings.filmUrl} placeholder="https://" help="Mettez la vidéo en « non répertoriée » chez l'hébergeur jusqu'au jour J : son lien n'est transmis par le site qu'après la révélation, mais l'hébergeur, lui, ne connaît pas ce secret." /></div>
          <button className="adm-btn">Enregistrer</button>
        </form>
      </Card>
      <p className="mt-3 text-xs text-smoke">L&apos;image principale et la galerie se gèrent dans <Link href="/admin/media" className="underline underline-offset-4">Médias</Link> (emplacements « Image principale » et « Galerie », visibilité « Confidentielle »).</p>

      <h2 id="sections" className="mb-3 mt-12 scroll-mt-8">Sections</h2>
      <div className="space-y-3">
        {sections.map((s) => (
          <Card key={s.id}>
            <details>
              <summary className="flex flex-wrap items-center gap-3">
                <span className="font-medium text-white">{pickText(s.title, "en")}</span>
                <span className="font-mono text-xs text-smoke">#{s.key}</span>
                {s.published ? <Badge tone="ok">Publiée</Badge> : <Badge>Masquée</Badge>}
                {!pickText(s.body, "en") && <Badge tone="warn">Vide</Badge>}
              </summary>
              <form action={saveSectionAction} className="mt-5 grid gap-4">
                <input type="hidden" name="id" value={s.id} />
                <LocalizedField label="Titre" name="title" value={s.title} required />
                <LocalizedField label="Texte (Markdown)" name="body" value={s.body} rows={6} help="## Titre · **gras** · - liste · [lien](https://…) · ![image](/media/IDENTIFIANT)" />
                <div className="flex flex-wrap items-center gap-6">
                  <Check label="Publiée (visible après la révélation)" name="published" defaultChecked={s.published} />
                  <div className="w-28"><Field label="Ordre" name="sortOrder" type="number" defaultValue={s.sortOrder} /></div>
                  <button className="adm-btn">Enregistrer</button>
                </div>
              </form>
            </details>
          </Card>
        ))}
      </div>

      <h2 id="specs" className="mb-3 mt-12 scroll-mt-8">Caractéristiques techniques</h2>
      <div className="space-y-3">
        {[...specs, null].map((s) => (
          <Card key={s?.id ?? "new"}>
            <details open={!s && specs.length === 0}>
              <summary className="flex flex-wrap items-center gap-3">
                {s ? (
                  <>
                    <span className="text-ash">{pickText(s.label, "en")}</span><span className="font-medium text-white">{pickText(s.value, "en")}</span>
                    {s.validated ? <Badge tone="ok">Validée</Badge> : <Badge tone="warn">Non validée — non affichée</Badge>}
                  </>
                ) : <span className="font-medium text-white">+ Ajouter une caractéristique</span>}
              </summary>
              <form action={saveSpecAction} className="mt-5 grid gap-4 lg:grid-cols-3">
                <input type="hidden" name="id" value={s?.id ?? ""} />
                <LocalizedField label="Groupe (ex. Dimensions)" name="groupName" value={s?.groupName} />
                <LocalizedField label="Intitulé" name="label" value={s?.label} required />
                <LocalizedField label="Valeur" name="value" value={s?.value} required help="Avec son unité et, si utile, ses conditions de mesure." />
                <div className="flex flex-wrap items-center gap-6 lg:col-span-3">
                  {mayValidate
                    ? <Check label="Valeur validée" name="validated" defaultChecked={s?.validated} help="Je certifie que cette valeur a été mesurée ou arrêtée par les fondateurs." />
                    : <p className="text-sm text-smoke">Validation réservée aux Super Admins. Modifier une valeur validée lui retire sa validation.</p>}
                  <div className="w-28"><Field label="Ordre" name="sortOrder" type="number" defaultValue={s?.sortOrder ?? specs.length} /></div>
                  <button className="adm-btn">{s ? "Enregistrer" : "Ajouter"}</button>
                </div>
              </form>
              {s && <Delete id={s.id} kind="specs" label="cette caractéristique" />}
            </details>
          </Card>
        ))}
      </div>

      <h2 id="kit" className="mb-3 mt-12 scroll-mt-8">Contenu du kit</h2>
      <div className="space-y-3">
        {[...kit, null].map((k) => (
          <Card key={k?.id ?? "new"}>
            <details open={!k && kit.length === 0}>
              <summary>{k ? <><span className="font-medium text-white">{pickText(k.name, "en")}</span>{k.quantity && <span className="ml-3 text-cyan">{k.quantity}</span>}</> : <span className="font-medium text-white">+ Ajouter un élément</span>}</summary>
              <form action={saveKitItemAction} className="mt-5 grid gap-4 lg:grid-cols-2">
                <input type="hidden" name="id" value={k?.id ?? ""} />
                <LocalizedField label="Nom" name="name" value={k?.name} required />
                <LocalizedField label="Description" name="description" value={k?.description} />
                <Field label="Quantité (ex. ×4)" name="quantity" defaultValue={k?.quantity} />
                <Field label="Ordre" name="sortOrder" type="number" defaultValue={k?.sortOrder ?? kit.length} />
                <div><button className="adm-btn">{k ? "Enregistrer" : "Ajouter"}</button></div>
              </form>
              {k && <Delete id={k.id} kind="kit" label="cet élément" />}
            </details>
          </Card>
        ))}
      </div>

      <h2 id="tiers" className="mb-2 mt-12 scroll-mt-8">Récompenses Kickstarter</h2>
      <p className="mb-4 max-w-2xl text-sm text-ash">Paliers proposés par le cahier des charges, tous <strong className="text-white">inactifs</strong> tant qu&apos;un Super Admin ne les a pas confirmés. Ils sont affichés pour information : les contributions se font exclusivement sur Kickstarter, ce site n&apos;encaisse rien. Les prix restent en dollars ; aucune conversion automatique n&apos;est faite.</p>
      <div className="space-y-3">
        {[...tiers, null].map((t) => (
          <Card key={t?.id ?? "new"}>
            <details>
              <summary className="flex flex-wrap items-center gap-3">
                {t ? <><span className="font-medium text-white">{t.name}</span><span className="tabular-nums text-ash">{formatUsd(t.priceCents)}</span>{t.active ? <Badge tone="ok">Active</Badge> : <Badge tone="warn">Inactive — non affichée</Badge>}</> : <span className="font-medium text-white">+ Ajouter une récompense</span>}
              </summary>
              <form action={saveTierAction} className="mt-5 grid gap-4 lg:grid-cols-2">
                <input type="hidden" name="id" value={t?.id ?? ""} />
                <Field label="Nom" name="name" defaultValue={t?.name} required />
                <Field label="Prix (USD)" name="price" type="number" min={1} defaultValue={t ? Math.round(t.priceCents / 100) : undefined} required />
                <LocalizedField label="Description" name="description" value={t?.description} rows={2} />
                <LocalizedField label="Conditions (livraison, taxes, délais)" name="conditions" value={t?.conditions} rows={2} help="Précisez ce qui est inclus ou non : frais de port, taxes, date de livraison estimée." />
                <Field label="Quantité limitée (facultatif)" name="quantityLimit" type="number" min={1} defaultValue={t?.quantityLimit} />
                <Field label="Ordre" name="sortOrder" type="number" defaultValue={t?.sortOrder ?? tiers.length} />
                <div className="flex flex-wrap items-center gap-6 lg:col-span-2">
                  {mayValidate ? <Check label="Récompense confirmée et affichée" name="active" defaultChecked={t?.active} /> : <p className="text-sm text-smoke">Activation réservée aux Super Admins. Changer le prix d&apos;une récompense active la désactive.</p>}
                  <button className="adm-btn">{t ? "Enregistrer" : "Ajouter"}</button>
                </div>
              </form>
              {t && <Delete id={t.id} kind="tiers" label="cette récompense" />}
            </details>
          </Card>
        ))}
      </div>
    </>
  );
}
