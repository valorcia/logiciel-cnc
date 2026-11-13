import { db } from "@/lib/db";
import { seedDefaults } from "../prisma/seed-data";

/** Empties every table, then restores the default content (templates, steps, settings). */
export async function resetDatabase(): Promise<void> {
  const tables = await db.$queryRaw<{ tablename: string }[]>`
    SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> '_prisma_migrations'`;
  const list = tables.map((t) => `"${t.tablename}"`).join(", ");
  await db.$executeRawUnsafe(`TRUNCATE ${list} RESTART IDENTITY CASCADE`);
  await seedDefaults(db);
}

export const ctx = (ip = "1") => ({ ipHash: `iphash-${ip}`, userAgent: "vitest", utm: {} });

/** The confirmation token only exists in the e-mail; tests plant a known one. */
export async function plantConfirmToken(email: string, token: string): Promise<void> {
  const { hashToken } = await import("@/lib/crypto");
  await db.subscriber.update({ where: { email }, data: { confirmTokenHash: hashToken(token), confirmSentAt: new Date() } });
}
