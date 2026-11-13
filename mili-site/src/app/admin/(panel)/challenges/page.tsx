import Link from "next/link";
import { Submit } from "@/components/admin/client";
import { Card, Empty, Field, Flash, fmtDate, PageTitle, Select, StatusBadge } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";
import type { ChallengeStatus } from "@/generated/prisma/client";
import { moderateChallengeAction } from "../../actions/content";

export const metadata = { title: "Défis" };
const CATEGORIES = [["ART_DESIGN", "Art & Design"], ["ENGINEERING", "Engineering"], ["ROBOTICS", "Robotics"], ["AUTOMOTIVE", "Automotive"], ["AEROSPACE", "Aerospace"], ["JEWELRY", "Jewelry"], ["EDUCATION", "Education"], ["OTHER", "Other"]] as const;
const TABS = [["PENDING", "À modérer"], ["APPROVED", "Publiés"], ["REJECTED", "Refusés"]] as const;

export default async function ChallengesPage({ searchParams }: { searchParams: Promise<{ status?: string; ok?: string; error?: string }> }) {
  await requireAdmin("challenges.moderate");
  const params = await searchParams;
  const status = (TABS.find(([k]) => k === params.status)?.[0] ?? "PENDING") as ChallengeStatus;
  const rows = await db.challenge.findMany({ where: { status }, orderBy: status === "APPROVED" ? { voteCount: "desc" } : { createdAt: "desc" }, take: 200 });
  const back = `?status=${status}`;
  return (
    <>
      <PageTitle title="Défis" text="Le texte envoyé par le visiteur n'est jamais publié tel quel : vous rédigez le titre et le résumé publics. Le fichier joint reste privé. Ne publiez que le prénom, jamais le nom complet ni l'e-mail." />
      <Flash params={params} />
      <div className="mb-4 flex gap-1.5">
        {TABS.map(([key, label]) => <Link key={key} href={`/admin/challenges?status=${key}`} className={`adm-btn adm-btn-sm ${key === status ? "" : "adm-btn-ghost"}`}>{label}</Link>)}
      </div>
      {rows.length === 0 ? <Empty>Rien ici pour le moment.</Empty> : (
        <div className="space-y-3">
          {rows.map((c) => (
            <Card key={c.id}>
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <StatusBadge status={c.status} />
                <strong>{c.name}</strong>
                <a href={`mailto:${c.email}`} className="text-ash underline underline-offset-4">{c.email}</a>
                {status === "APPROVED" && <span className="text-cyan">{c.voteCount} vote{c.voteCount > 1 ? "s" : ""}</span>}
                <span className="ml-auto text-xs text-smoke">{fmtDate(c.createdAt)} · {c.locale}</span>
              </div>
              <p className="mt-4 whitespace-pre-wrap rounded-lg bg-void/60 p-4 text-sm leading-relaxed text-ash">{c.description}</p>
              {c.fileKey && (
                <p className="mt-3 text-sm">
                  <a href={`/admin/challenges/${c.id}/file`} className="underline underline-offset-4 hover:text-cyan">Télécharger le fichier joint</a>
                  <span className="ml-2 text-xs text-smoke">{c.fileName} · {c.fileMime} · {Math.round((c.fileSize ?? 0) / 1024)} Ko — fichier envoyé par un inconnu : ouvrez-le avec prudence.</span>
                </p>
              )}
              <form action={moderateChallengeAction} className="mt-5 grid gap-4 border-t border-line pt-5 lg:grid-cols-2">
                <input type="hidden" name="id" value={c.id} />
                <input type="hidden" name="back" value={back} />
                <Field label="Titre public" name="publicTitle" defaultValue={c.publicTitle} maxLength={120} />
                <Field label="Prénom affiché" name="displayName" defaultValue={c.displayName ?? c.name.split(/\s+/)[0]} maxLength={40} />
                <Field label="Résumé public" name="publicDescription" defaultValue={c.publicDescription} rows={2} maxLength={400} />
                <Select label="Catégorie" name="category" defaultValue={c.category} options={CATEGORIES} />
                <div className="flex flex-wrap gap-2 lg:col-span-2">
                  <button name="decision" value="approve" className="adm-btn">{status === "APPROVED" ? "Mettre à jour" : "Approuver et publier"}</button>
                  {status !== "REJECTED" && <button name="decision" value="reject" className="adm-btn adm-btn-ghost">Refuser</button>}
                  <Submit name="decision" value="delete" className="adm-btn adm-btn-danger" confirm="Supprimer définitivement ce défi, son fichier et ses votes ?">Supprimer</Submit>
                </div>
              </form>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
