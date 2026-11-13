import "server-only";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { auth } from "./auth";
import { db } from "./db";
import { can, type Permission } from "./permissions";
import type { Role } from "@/generated/prisma/client";

export type Admin = { id: string; email: string; name: string; role: Role };

/** The signed-in administrator, re-read from the database on every request so that
 *  a role change or a deactivation takes effect immediately. */
export async function currentAdmin(): Promise<Admin | null> {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session?.user) return null;
  const user = await db.user.findUnique({ where: { id: session.user.id } });
  if (!user || !user.active) return null;
  return { id: user.id, email: user.email, name: user.name, role: user.role };
}

/** For pages: redirects to the login screen, or to the dashboard when the role is insufficient. */
export async function requireAdmin(permission: Permission = "dashboard.view"): Promise<Admin> {
  const admin = await currentAdmin();
  if (!admin) redirect("/admin/login");
  if (!can(admin.role, permission)) redirect("/admin?denied=1");
  return admin;
}

export class ForbiddenError extends Error {
  constructor(message = "Forbidden") {
    super(message);
    this.name = "ForbiddenError";
  }
}

/** For Server Actions and route handlers: throws instead of redirecting. */
export async function assertAdmin(permission: Permission): Promise<Admin> {
  const admin = await currentAdmin();
  if (!admin) throw new ForbiddenError("Not authenticated");
  if (!can(admin.role, permission)) throw new ForbiddenError(`Missing permission: ${permission}`);
  return admin;
}
