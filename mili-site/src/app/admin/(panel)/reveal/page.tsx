import Link from "next/link";
import { Submit } from "@/components/admin/client";
import { Badge, Card, Check, Field, Flash, fmtDate, PageTitle } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";
import { emailProviderConfigured } from "@/lib/email/provider";
import { can } from "@/lib/permissions";
import { getSettings } from "@/lib/settings";
import { switchModeAction } from "../../actions/product";

export const metadata = { title: "Mode Reveal" };

export default async function RevealPage({ searchParams }: { searchParams: Promise<{ ok?: string; error?: string }> }) {
  const admin = await requireAdmin("product.edit");
  const settings = await getSettings();
  const [sections, emptySections, specs, pendingSpecs, tiers, hero, gallery, confidentialUsed, revealFaq, by] = await Promise.all([
    db.productSection.count({ where: { published: true } }),
    db.productSection.count({ where: { published: false } }),
    db.productSpec.count({ where: { validated: true } }),
    db.productSpec.count({ where: { validated: false } }),
    db.pledgeTier.count({ where: { active: true } }),
    db.mediaAsset.count({ where: { placement: "HERO_IMAGE" } }),
    db.mediaAsset.count({ where: { placement: "GALLERY" } }),
    db.mediaAsset.count({ where: { visibility: "REVEAL_ONLY" } }),
    db.faq.count({ where: { published: true, scope: { in: ["REVEAL", "BOTH"] } } }),
    settings.revealedById ? db.user.findUnique({ where: { id: settings.revealedById }, select: { name: true } }) : null,
  ]);
  const revealed = settings.mode === "REVEAL";
  const maySwitch = can(admin.role, "reveal.switch");
  const checks: [boolean, string, string, boolean][] = [
    [sections > 0, "Fiche produit", `${sections} section(s) publiée(s), ${emptySections} masquée(s)`, true],
    [specs > 0, "Caractéristiques validées", `${specs} validée(s)${pendingSpecs ? `, ${pendingSpecs} en attente de validation (non affichées)` : ""}`, false],
    [Boolean(settings.kickstarterUrl), "Lien Kickstarter", settings.kickstarterUrl ?? "Absent : les boutons « Back MILI on Kickstarter » resteront inactifs et les e-mails de lancement ne partiront pas", false],
    [tiers > 0, "Récompenses confirmées", `${tiers} active(s)`, false],
    [hero > 0 || Boolean(settings.filmUrl), "Film ou image principale", `${settings.filmUrl ? "Film renseigné" : "Pas de film"} · ${hero} image principale · ${gallery} image(s) de galerie`, false],
    [revealFaq > 0, "FAQ après révélation", `${revealFaq} question(s)`, false],
    [Boolean(settings.launchAt), "Date de lancement", settings.launchAt ? fmtDate(settings.launchAt) : "Non définie", false],
    [Boolean(settings.legalName && settings.postalAddress), "Identité légale et adresse postale", settings.legalName ? "Renseignées" : "Incomplètes (Paramètres)", false],
    [emailProviderConfigured(), "Fournisseur d'e-mail", emailProviderConfigured() ? "Configuré" : "Non configuré : aucun e-mail de lancement ne partira", false],
  ];
  const blocked = checks.some(([ok, , , required]) => required && !ok);

  return (
    <>
      <PageTitle title="Mode Reveal" text="Le site a deux états. En mode Mystery, rien de confidentiel ne quitte le serveur : la page produit répond 404, les images confidentielles aussi, et les réponses envoyées au navigateur ne contiennent ni caractéristiques ni médias de la machine. Le compte à rebours, lui, ne déclenche rien : seule cette page fait basculer le site." />
      <Flash params={await searchParams} />

      <Card className="mb-4">
        <div className="flex flex-wrap items-center gap-4">
          <span className="text-sm text-smoke">État actuel</span>
          <span className={`adm-badge text-base ${revealed ? "adm-badge-ok" : "adm-badge-warn"}`}>{revealed ? "REVEAL — la machine est publique" : "MYSTERY — la machine est secrète"}</span>
          {revealed && <span className="text-sm text-ash">Révélé le {fmtDate(settings.revealedAt)}{by ? ` par ${by.name}` : ""}</span>}
          <Link href="/admin/reveal/preview" className="adm-btn adm-btn-ghost adm-btn-sm ml-auto">Prévisualiser la page produit</Link>
        </div>
      </Card>

      <Card title="Contrôles avant révélation" className="mb-4">
        <ul className="divide-y divide-line">
          {checks.map(([ok, label, detail, required]) => (
            <li key={label} className="flex flex-wrap items-center gap-3 py-3 first:pt-0 last:pb-0">
              <Badge tone={ok ? "ok" : required ? "bad" : "warn"}>{ok ? "OK" : required ? "Bloquant" : "À vérifier"}</Badge>
              <span className="w-64 text-sm text-white">{label}</span>
              <span className="min-w-0 flex-1 break-words text-sm text-ash">{detail}</span>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-xs text-smoke">{confidentialUsed} image(s) confidentielle(s) deviendront accessibles à la révélation.</p>
      </Card>

      {!maySwitch ? (
        <Card><p className="text-sm text-ash">La bascule est réservée aux Super Admins.</p></Card>
      ) : revealed ? (
        <Card title="Revenir au mode Mystery">
          <p className="mb-4 max-w-2xl text-sm leading-relaxed text-ash">Retour arrière d&apos;urgence. La page produit et les médias confidentiels redeviennent inaccessibles en moins d&apos;une minute. <strong className="text-white">Ce qui a déjà été vu, copié, indexé par un moteur de recherche ou envoyé par e-mail ne peut pas être repris.</strong></p>
          <form action={switchModeAction} className="grid max-w-xl gap-4">
            <input type="hidden" name="target" value="MYSTERY" />
            <Field label="Saisissez MYSTERY pour confirmer" name="confirmation" required mono />
            <Check label="Je comprends que ce retour ne rend pas le secret à ce qui a déjà été diffusé." name="understood" />
            <div><Submit className="adm-btn adm-btn-danger" confirm="Repasser le site en mode Mystery ?">Repasser en mode Mystery</Submit></div>
          </form>
        </Card>
      ) : (
        <Card title="Révéler la machine">
          <p className="mb-4 max-w-2xl text-sm leading-relaxed text-ash">
            En validant, d&apos;un seul coup et pour tous les visiteurs : la page d&apos;accueil change, la page produit et ses médias deviennent publics, la page entre dans le plan du site, et les e-mails de lancement dont la date est atteinte pourront partir. L&apos;opération est enregistrée dans le journal d&apos;activité avec votre nom.
            <strong className="text-white"> Une révélation ne se reprend pas vraiment.</strong>
          </p>
          {blocked && <p role="alert" className="mb-4 text-sm text-[#ff8a9a]">Un contrôle bloquant n&apos;est pas satisfait.</p>}
          <form action={switchModeAction} className="grid max-w-xl gap-4">
            <input type="hidden" name="target" value="REVEAL" />
            <Field label="Saisissez REVEAL pour confirmer" name="confirmation" required mono />
            <Check label="J'ai prévisualisé la page produit et je confirme que tout ce qu'elle affiche est exact et peut être rendu public." name="understood" />
            <div><Submit className="adm-btn" confirm="Révéler MILI au public maintenant ?">Révéler MILI maintenant</Submit></div>
          </form>
        </Card>
      )}
    </>
  );
}
