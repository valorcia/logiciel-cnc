import "server-only";
import { db } from "./db";

type Actor = { id: string; email: string } | null;

/** Appends an entry to the administrator audit trail. Never store personal data of prospects in `meta`. */
export async function audit(
  actor: Actor,
  action: string,
  entity: string,
  entityId?: string | null,
  meta: Record<string, string | number | boolean | null> = {},
): Promise<void> {
  await db.auditLog.create({
    data: { actorId: actor?.id, actorEmail: actor?.email, action, entity, entityId: entityId ?? null, meta },
  });
}
