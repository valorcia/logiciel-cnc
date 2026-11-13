import { Card, Check, Field, Flash, fmtDate, PageTitle, Select } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";
import { createUserAction, updateUserAction } from "../../actions/people";

export const metadata = { title: "Utilisateurs" };
const ROLE_OPTIONS = [
  ["SUPER_ADMIN", "Super Admin — tout, y compris la bascule Reveal et les validations techniques"],
  ["MARKETING_ADMIN", "Marketing Admin — prospects, e-mails, contenus, paramètres"],
  ["CONTENT_EDITOR", "Content Editor — textes, indices, journal, médias"],
  ["READ_ONLY", "Read Only — tableau de bord uniquement"],
] as const;

export default async function UsersPage({ searchParams }: { searchParams: Promise<{ ok?: string; error?: string }> }) {
  const admin = await requireAdmin("users.manage");
  const users = await db.user.findMany({ orderBy: { createdAt: "asc" } });
  return (
    <>
      <PageTitle title="Utilisateurs" text="Il n'existe pas d'inscription publique : les comptes sont créés ici. Mot de passe de 12 caractères minimum, à transmettre par un canal sûr." />
      <Flash params={await searchParams} />
      <div className="space-y-3">
        {users.map((u) => (
          <Card key={u.id}>
            <form action={updateUserAction} className="grid items-end gap-4 lg:grid-cols-[1.2fr_1.6fr_1fr_auto_auto]">
              <input type="hidden" name="id" value={u.id} />
              <div>
                <p className="font-medium text-white">{u.name}{u.id === admin.id && <span className="ml-2 text-xs text-cyan">(vous)</span>}</p>
                <p className="text-sm text-ash">{u.email}</p>
                <p className="mt-1 text-xs text-smoke">Créé le {fmtDate(u.createdAt)}</p>
              </div>
              <Select label="Rôle" name="role" defaultValue={u.role} options={ROLE_OPTIONS} />
              <Field label="Nouveau mot de passe" name="password" type="password" placeholder="Laisser vide pour ne pas changer" />
              <Check label="Actif" name="active" defaultChecked={u.active} />
              <button className="adm-btn">Enregistrer</button>
            </form>
          </Card>
        ))}
      </div>
      <Card title="Créer un compte" className="mt-8">
        <form action={createUserAction} className="grid gap-4 lg:grid-cols-2">
          <Field label="Nom" name="name" required />
          <Field label="Adresse e-mail" name="email" type="email" required />
          <Field label="Mot de passe" name="password" type="password" required help="12 caractères minimum." />
          <Select label="Rôle" name="role" defaultValue="CONTENT_EDITOR" options={ROLE_OPTIONS} />
          <div><button className="adm-btn">Créer le compte</button></div>
        </form>
      </Card>
    </>
  );
}
