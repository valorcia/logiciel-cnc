import "server-only";
import { db } from "./db";

export type RateLimitResult = { allowed: boolean; remaining: number; retryAfterSec: number };

/**
 * Fixed-window rate limiter backed by PostgreSQL, so it holds across serverless
 * instances without an extra service. One atomic statement per check.
 */
export async function rateLimit(key: string, limit: number, windowSec: number): Promise<RateLimitResult> {
  const rows = await db.$queryRaw<{ count: number; expiresAt: Date }[]>`
    INSERT INTO "RateLimit" ("key", "count", "windowStart", "expiresAt")
    VALUES (${key}, 1, now(), now() + make_interval(secs => ${windowSec}))
    ON CONFLICT ("key") DO UPDATE SET
      "count" = CASE WHEN "RateLimit"."expiresAt" <= now() THEN 1 ELSE "RateLimit"."count" + 1 END,
      "windowStart" = CASE WHEN "RateLimit"."expiresAt" <= now() THEN now() ELSE "RateLimit"."windowStart" END,
      "expiresAt" = CASE WHEN "RateLimit"."expiresAt" <= now()
        THEN now() + make_interval(secs => ${windowSec}) ELSE "RateLimit"."expiresAt" END
    RETURNING "count", "expiresAt"`;
  const row = rows[0];
  const count = Number(row.count);
  const retryAfterSec = Math.max(1, Math.ceil((row.expiresAt.getTime() - Date.now()) / 1000));
  return { allowed: count <= limit, remaining: Math.max(0, limit - count), retryAfterSec };
}

/** Housekeeping, called by the cron route. */
export async function purgeExpiredRateLimits(): Promise<number> {
  const result = await db.rateLimit.deleteMany({ where: { expiresAt: { lt: new Date() } } });
  return result.count;
}
