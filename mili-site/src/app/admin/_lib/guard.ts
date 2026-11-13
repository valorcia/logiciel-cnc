import "server-only";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { assertAdmin, ForbiddenError, type Admin } from "@/lib/admin-session";
import { audit } from "@/lib/audit";
import type { Permission } from "@/lib/permissions";

type AuditMeta = Record<string, string | number | boolean | null>;
export type ActionContext = { admin: Admin; log: (action: string, entity: string, entityId?: string | null, meta?: AuditMeta) => Promise<void> };

export class FormError extends Error {}

/**
 * Wraps every back-office mutation: checks the session and the permission,
 * runs the change, refreshes the public site's cache and redirects back with a
 * message. A FormError becomes a readable message; anything else is rethrown.
 */
export async function adminAction(
  permission: Permission,
  back: string,
  run: (ctx: ActionContext) => Promise<string | void>,
  ok = "saved",
): Promise<never> {
  let target = back;
  try {
    const admin = await assertAdmin(permission);
    const result = await run({ admin, log: (action, entity, entityId, meta) => audit(admin, action, entity, entityId, meta) });
    if (typeof result === "string") target = result;
    revalidatePath("/", "layout");
    target += `${target.includes("?") ? "&" : "?"}ok=${ok}`;
  } catch (err) {
    if (err instanceof ForbiddenError) redirect("/admin/login");
    if (!(err instanceof FormError)) throw err;
    target = `${back}${back.includes("?") ? "&" : "?"}error=${encodeURIComponent(err.message)}`;
  }
  redirect(target);
}
