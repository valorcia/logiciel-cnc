import { Submit } from "@/components/admin/client";
import { Card, Check, Field, Flash, LocalizedField, PageTitle } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";
import { getSettings, socialLinks } from "@/lib/settings";
import { toInputDateTime } from "../../_lib/form";
import { deleteRewardAction, saveRewardAction, saveSettingsAction } from "../../actions/people";

export const metadata = { title: "Paramètres" };

export default async function SettingsPage({ searchParams }: { searchParams: Promise<{ ok?: string; error?: string }> }) {
  await requireAdmin("settings.edit");
  const [s, rewards] = await Promise.all([getSettings(), db.referralReward.findMany({ orderBy: { threshold: "asc" } })]);
  const social = socialLinks(s);
  return (
    <>
      <PageTitle title="Paramètres" text="Les changements sont visibles sur le site dans la minute." />
      <Flash params={await searchParams} />
      <form action={saveSettingsAction} className="space-y-4">
        <Card title="Lancement">
          <div className="grid gap-4 lg:grid-cols-2">
            <Field label="Date et heure du lancement (UTC)" name="launchAt" type="datetime-local" defaultValue={toInputDateTime(s.launchAt)}
              help="Saisie en temps universel (UTC) ; chaque visiteur la voit dans son fuseau. Elle pilote le compte à rebours et le calendrier des e-mails de pré-lancement. Arrivé à zéro, le compte à rebours ne révèle rien : la bascule en mode Reveal reste une action manuelle." />
            <Field label="Lien de la campagne Kickstarter" name="kickstarterUrl" type="url" defaultValue={s.kickstarterUrl} placeholder="https://www.kickstarter.com/projects/…"
              help="Tant qu'il est vide, les boutons « Back MILLI on Kickstarter » restent inactifs et les e-mails de lancement ne partent pas." />
            <Check label="Afficher le compte à rebours" name="countdownEnabled" defaultChecked={s.countdownEnabled} help="Sans date de lancement, il reste masqué." />
          </div>
        </Card>
        <Card title="Prix de lancement envisagé">
          <div className="grid gap-4 lg:grid-cols-2">
            <Field label="Prix affiché (USD, sans centimes)" name="plannedPrice" type="number" min={1} defaultValue={Math.round(s.plannedPriceCents / 100)}
              help="Décision commerciale : ce montant apparaît en très grand sur la page d'accueil, toujours accompagné de la mention « prix envisagé, sous réserve de confirmation »." />
            <Check label="Afficher le prix sur le site" name="showPlannedPrice" defaultChecked={s.showPlannedPrice} help="Décoché : le prix disparaît partout (accueil, image de partage, pied de page)." />
          </div>
        </Card>
        <Card title="Identité légale et contact">
          <div className="grid gap-4 lg:grid-cols-2">
            <Field label="Raison sociale" name="legalName" defaultValue={s.legalName} help="Figure dans le pied des e-mails et les pages légales." />
            <Field label="Adresse e-mail de contact" name="contactEmail" type="email" defaultValue={s.contactEmail} />
            <div className="lg:col-span-2">
              <Field label="Adresse postale" name="postalAddress" defaultValue={s.postalAddress} help="Obligatoire dans tout e-mail marketing envoyé vers les États-Unis (loi CAN-SPAM). Sans elle, les e-mails de campagne ne devraient pas être activés." />
            </div>
          </div>
        </Card>
        <Card title="Réseaux sociaux">
          <div className="grid gap-4 lg:grid-cols-2">
            {(["x", "youtube", "instagram", "facebook", "reddit", "tiktok", "discord"] as const).map((key) => (
              <Field key={key} label={key === "x" ? "X (Twitter)" : key[0].toUpperCase() + key.slice(1)} name={`social.${key}`} type="url" defaultValue={social[key]} placeholder="https://" />
            ))}
          </div>
        </Card>
        <Card title="Parrainage">
          <Check label="Afficher le classement des meilleurs parrains dans l'espace Insider" name="leaderboardEnabled" defaultChecked={s.leaderboardEnabled} help="Les parrains y apparaissent sous un identifiant masqué, jamais sous leur nom ou leur e-mail." />
        </Card>
        <button className="adm-btn">Enregistrer les paramètres</button>
      </form>

      <h2 id="rewards" className="mb-2 mt-12 scroll-mt-8">Rangs de parrainage</h2>
      <p className="mb-4 max-w-2xl text-sm text-ash">Un rang est une reconnaissance. N&apos;écrivez un avantage concret (remise, produit, accès) dans sa description qu&apos;une fois celui-ci validé : ce texte est une promesse publique.</p>
      <div className="space-y-3">
        {[...rewards, null].map((r) => (
          <Card key={r?.id ?? "new"} title={r ? undefined : "Ajouter un rang"}>
            <form action={saveRewardAction} className="grid gap-4 lg:grid-cols-[8rem_1fr_2fr]">
              <input type="hidden" name="id" value={r?.id ?? ""} />
              <Field label="Filleuls requis" name="threshold" type="number" min={1} defaultValue={r?.threshold} required />
              <Field label="Nom du rang" name="name" defaultValue={r?.name} required />
              <LocalizedField label="Description" name="description" value={r?.description} />
              <div className="flex items-center gap-4 lg:col-span-3">
                <Check label="Actif" name="active" defaultChecked={r?.active ?? true} />
                <button className="adm-btn adm-btn-sm">{r ? "Enregistrer" : "Ajouter"}</button>
              </div>
            </form>
            {r && (
              <form action={deleteRewardAction} className="mt-3">
                <input type="hidden" name="id" value={r.id} />
                <Submit className="adm-btn adm-btn-danger adm-btn-sm" confirm={`Supprimer le rang « ${r.name} » ?`}>Supprimer</Submit>
              </form>
            )}
          </Card>
        ))}
      </div>
    </>
  );
}
