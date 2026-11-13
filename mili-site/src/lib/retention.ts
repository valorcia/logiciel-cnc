import "server-only";
import { db } from "./db";
import { storage } from "./storage";

const DAY = 24 * 60 * 60 * 1000;

/**
 * Enforces the retention periods announced in the Privacy Policy. Runs with the
 * scheduled job; every figure here must match src/app/[locale]/privacy/page.tsx.
 */
export async function applyRetention(now = new Date()) {
  const ago = (days: number) => new Date(now.getTime() - days * DAY);

  const pending = await db.subscriber.deleteMany({ where: { status: "PENDING", createdAt: { lt: ago(30) } } });
  const unsubscribed = await db.subscriber.deleteMany({ where: { status: "UNSUBSCRIBED", unsubscribedAt: { lt: ago(5 * 365) } } });
  const inquiries = await db.inquiry.deleteMany({ where: { createdAt: { lt: ago(365) } } });
  const visits = await db.visit.deleteMany({ where: { day: { lt: ago(25 * 31) } } });
  const rateLimits = await db.rateLimit.deleteMany({ where: { expiresAt: { lt: now } } });

  const oldChallenges = await db.challenge.findMany({ where: { createdAt: { lt: ago(730) } }, select: { id: true, fileKey: true } });
  for (const challenge of oldChallenges) {
    if (challenge.fileKey) await storage().delete(challenge.fileKey).catch(() => {});
  }
  const challenges = await db.challenge.deleteMany({ where: { id: { in: oldChallenges.map((c) => c.id) } } });

  return {
    pendingSubscribers: pending.count, unsubscribed: unsubscribed.count, inquiries: inquiries.count,
    visits: visits.count, rateLimits: rateLimits.count, challenges: challenges.count,
  };
}
