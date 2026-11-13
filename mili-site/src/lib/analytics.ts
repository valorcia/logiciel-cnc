import "server-only";
import { visitorHash } from "./crypto";
import { db } from "./db";
import type { Utm } from "./validation";

export type VisitInput = {
  ip: string;
  userAgent: string;
  path: string;
  locale?: string | null;
  referrer?: string | null;
  country?: string | null;
  utm: Utm;
  selfHost: string;
};

const BOT = /bot|crawl|spider|slurp|preview|monitor|headless|lighthouse|pingdom|curl|wget|python-requests/i;

/** Channel a visit is attributed to: explicit UTM first, then the referring site, else "direct". */
export function attributeSource(utmSource: string | undefined, referrer: string | null | undefined, selfHost: string): string {
  if (utmSource) return utmSource.toLowerCase();
  if (!referrer) return "direct";
  try {
    const host = new URL(referrer).hostname.replace(/^www\./, "");
    return host === selfHost.replace(/^www\./, "") ? "direct" : host;
  } catch {
    return "direct";
  }
}

/**
 * Cookieless audience measurement. At most one row per anonymous visitor per
 * day; the identifier is a daily-salted hash, so no IP address and no
 * cross-day profile is ever stored. Bots are ignored.
 */
export async function recordVisit(input: VisitInput): Promise<boolean> {
  if (!input.userAgent || BOT.test(input.userAgent)) return false;
  const day = new Date().toISOString().slice(0, 10);
  const result = await db.visit.createMany({
    data: [{
      day: new Date(`${day}T00:00:00.000Z`),
      visitorHash: visitorHash(input.ip, input.userAgent, day),
      path: input.path.slice(0, 200),
      locale: input.locale ?? null,
      source: attributeSource(input.utm.utmSource, input.referrer, input.selfHost).slice(0, 120),
      utmSource: input.utm.utmSource,
      utmMedium: input.utm.utmMedium,
      utmCampaign: input.utm.utmCampaign,
      country: input.country ?? null,
    }],
    skipDuplicates: true,
  });
  return result.count === 1;
}
