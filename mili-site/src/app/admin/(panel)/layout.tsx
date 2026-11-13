import type { ReactNode } from "react";
import { requireAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";
import { emailProviderConfigured } from "@/lib/email/provider";
import { can, roleLabels, type Permission } from "@/lib/permissions";
import { getSettings } from "@/lib/settings";
import { logoutAction } from "../login/actions";
import { Nav } from "./nav";

export const dynamic = "force-dynamic";

type Item = { href: string; label: string; perm: Permission; badge?: number };

export default async function PanelLayout({ children }: { children: ReactNode }) {
  const admin = await requireAdmin();
  const [settings, pendingChallenges, openInquiries] = await Promise.all([
    getSettings(),
    db.challenge.count({ where: { status: "PENDING" } }),
    db.inquiry.count({ where: { status: { in: ["OPEN", "IN_PROGRESS"] } } }),
  ]);
  const groups: { title: string; items: Item[] }[] = [
    { title: "Pilotage", items: [
      { href: "/admin", label: "Tableau de bord", perm: "dashboard.view" },
      { href: "/admin/prospects", label: "Prospects", perm: "prospects.view" },
      { href: "/admin/inquiries", label: "Messages & RGPD", perm: "inquiries.manage", badge: openInquiries },
    ] },
    { title: "Contenu", items: [
      { href: "/admin/content", label: "Textes du site", perm: "content.edit" },
      { href: "/admin/clues", label: "Indices", perm: "clues.edit" },
      { href: "/admin/proof", label: "Vidéos de preuve", perm: "proof.edit" },
      { href: "/admin/challenges", label: "Défis", perm: "challenges.moderate", badge: pendingChallenges },
      { href: "/admin/faq", label: "FAQ", perm: "content.edit" },
      { href: "/admin/journal", label: "Journal", perm: "journal.edit" },
      { href: "/admin/media", label: "Médias", perm: "media.manage" },
    ] },
    { title: "Campagne", items: [
      { href: "/admin/emails", label: "E-mails", perm: "emails.edit" },
      { href: "/admin/product", label: "Fiche produit", perm: "product.edit" },
      { href: "/admin/reveal", label: "Mode Reveal", perm: "product.edit" },
    ] },
    { title: "Réglages", items: [
      { href: "/admin/settings", label: "Paramètres", perm: "settings.edit" },
      { href: "/admin/users", label: "Utilisateurs", perm: "users.manage" },
      { href: "/admin/audit", label: "Journal d'activité", perm: "audit.view" },
    ] },
  ];
  const visible = groups
    .map((g) => ({ title: g.title, items: g.items.filter((i) => can(admin.role, i.perm)).map(({ href, label, badge }) => ({ href, label, badge })) }))
    .filter((g) => g.items.length > 0);

  return (
    <div className="lg:grid lg:min-h-svh lg:grid-cols-[15.5rem_1fr]">
      <aside className="border-b border-line bg-carbon/60 p-4 lg:sticky lg:top-0 lg:h-svh lg:overflow-y-auto lg:border-b-0 lg:border-r">
        <div className="mb-6 flex items-center justify-between px-3">
          <span className="font-semibold tracking-[0.28em]">MILLI</span>
          <span className={`adm-badge ${settings.mode === "REVEAL" ? "adm-badge-ok" : "adm-badge-warn"}`}>{settings.mode === "REVEAL" ? "Reveal" : "Mystery"}</span>
        </div>
        <Nav groups={visible} />
        <div className="mt-8 border-t border-line px-3 pt-5 text-xs text-smoke">
          <p className="truncate text-sm text-white">{admin.name}</p>
          <p className="truncate">{admin.email}</p>
          <p className="mt-1">{roleLabels[admin.role]}</p>
          <form action={logoutAction} className="mt-3"><button type="submit" className="adm-btn adm-btn-ghost adm-btn-sm">Se déconnecter</button></form>
          <a href="/" target="_blank" rel="noopener" className="mt-3 inline-block underline underline-offset-4 hover:text-white">Voir le site ↗</a>
        </div>
      </aside>
      <main className="min-w-0 px-4 py-8 sm:px-8 lg:px-10">
        {!emailProviderConfigured() && (
          <p role="alert" className="mb-6 rounded-lg border border-[#ffc46b]/40 bg-[#ffc46b]/10 px-4 py-3 text-sm text-[#ffc46b]">
            Aucun fournisseur d&apos;e-mail n&apos;est configuré (variable RESEND_API_KEY absente) : <strong>aucun e-mail ne part</strong>, y compris les confirmations d&apos;inscription.
          </p>
        )}
        {children}
      </main>
    </div>
  );
}
