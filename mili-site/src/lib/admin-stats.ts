import "server-only";
import { Prisma } from "@/generated/prisma/client";
import { db } from "./db";

export type Range = { from: Date; to: Date; days: number };

export function rangeOf(days: number, now = new Date()): Range {
  const to = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1));
  return { from: new Date(to.getTime() - days * 86_400_000), to, days };
}

/** "Source" of a subscriber, computed the same way as for a visit. */
const SUB_SOURCE = Prisma.sql`lower(coalesce(nullif("utmSource", ''), nullif("referrerHost", ''), 'direct'))`;

export async function dashboardStats(range: Range, source?: string) {
  const { from, to } = range;
  const visitFilter = source ? Prisma.sql`AND source = ${source}` : Prisma.empty;
  const subFilter = source ? Prisma.sql`AND ${SUB_SOURCE} = ${source}` : Prisma.empty;
  const n = (rows: { n: bigint }[]) => Number(rows[0]?.n ?? 0);

  const [visitors, signups, confirmed, referrals, unsubscribed, total, sent, events, daily, sources, subSources, countries, utmVisits, utmSubs] = await Promise.all([
    db.$queryRaw<{ n: bigint }[]>`SELECT count(*)::bigint n FROM "Visit" WHERE day >= ${from} AND day < ${to} ${visitFilter}`,
    db.$queryRaw<{ n: bigint }[]>`SELECT count(*)::bigint n FROM "Subscriber" WHERE "createdAt" >= ${from} AND "createdAt" < ${to} ${subFilter}`,
    db.$queryRaw<{ n: bigint }[]>`SELECT count(*)::bigint n FROM "Subscriber" WHERE "confirmedAt" >= ${from} AND "confirmedAt" < ${to} ${subFilter}`,
    db.$queryRaw<{ n: bigint }[]>`SELECT count(*)::bigint n FROM "Subscriber" WHERE "confirmedAt" >= ${from} AND "confirmedAt" < ${to} AND "referredById" IS NOT NULL AND "referralFlagged" = false ${subFilter}`,
    db.$queryRaw<{ n: bigint }[]>`SELECT count(*)::bigint n FROM "Subscriber" WHERE "unsubscribedAt" >= ${from} AND "unsubscribedAt" < ${to} ${subFilter}`,
    db.subscriber.count({ where: { status: "CONFIRMED" } }),
    db.emailSend.count({ where: { status: "SENT", kind: { not: "TEST" }, createdAt: { gte: from, lt: to } } }),
    // Distinct messages per event type, as reported by the provider's webhooks — nothing is estimated.
    db.$queryRaw<{ type: string; n: bigint }[]>`
      SELECT e.type, count(DISTINCT e."providerId")::bigint n FROM "EmailEvent" e
      JOIN "EmailSend" s ON s.id = e."sendId"
      WHERE s."createdAt" >= ${from} AND s."createdAt" < ${to} AND s.kind <> 'TEST' GROUP BY e.type`,
    db.$queryRaw<{ day: Date; visitors: bigint; signups: bigint }[]>`
      SELECT d::date AS day,
        (SELECT count(*) FROM "Visit" v WHERE v.day = d::date ${visitFilter})::bigint AS visitors,
        (SELECT count(*) FROM "Subscriber" s WHERE s."createdAt" >= d AND s."createdAt" < d + interval '1 day' ${subFilter})::bigint AS signups
      FROM generate_series(${from}::timestamp, ${to}::timestamp - interval '1 day', interval '1 day') d ORDER BY d`,
    db.$queryRaw<{ source: string; n: bigint }[]>`SELECT coalesce(source, 'direct') source, count(*)::bigint n FROM "Visit" WHERE day >= ${from} AND day < ${to} GROUP BY 1 ORDER BY n DESC LIMIT 12`,
    db.$queryRaw<{ source: string; n: bigint; c: bigint }[]>`SELECT ${SUB_SOURCE} source, count(*)::bigint n, count("confirmedAt")::bigint c FROM "Subscriber" WHERE "createdAt" >= ${from} AND "createdAt" < ${to} GROUP BY 1`,
    db.$queryRaw<{ country: string; n: bigint }[]>`SELECT country, count(*)::bigint n FROM "Subscriber" WHERE "createdAt" >= ${from} AND "createdAt" < ${to} AND country IS NOT NULL ${subFilter} GROUP BY 1 ORDER BY n DESC LIMIT 12`,
    db.$queryRaw<{ campaign: string; source: string; medium: string; n: bigint }[]>`
      SELECT coalesce("utmCampaign", '') campaign, coalesce("utmSource", '') source, coalesce("utmMedium", '') medium, count(*)::bigint n
      FROM "Visit" WHERE day >= ${from} AND day < ${to} AND ("utmCampaign" IS NOT NULL OR "utmSource" IS NOT NULL) GROUP BY 1, 2, 3`,
    db.$queryRaw<{ campaign: string; source: string; medium: string; n: bigint; c: bigint }[]>`
      SELECT coalesce("utmCampaign", '') campaign, coalesce("utmSource", '') source, coalesce("utmMedium", '') medium, count(*)::bigint n, count("confirmedAt")::bigint c
      FROM "Subscriber" WHERE "createdAt" >= ${from} AND "createdAt" < ${to} AND ("utmCampaign" IS NOT NULL OR "utmSource" IS NOT NULL) GROUP BY 1, 2, 3`,
  ]);

  const eventCount = (type: string) => Number(events.find((e) => e.type === type)?.n ?? 0);
  const subBySource = new Map(subSources.map((s) => [s.source, s]));
  const sourceNames = [...new Set([...sources.map((s) => s.source), ...subSources.map((s) => s.source)])];
  const utm = new Map<string, { campaign: string; source: string; medium: string; visitors: number; signups: number; confirmed: number }>();
  const row = (r: { campaign: string; source: string; medium: string }) => {
    const key = `${r.campaign}|${r.source}|${r.medium}`;
    if (!utm.has(key)) utm.set(key, { campaign: r.campaign, source: r.source, medium: r.medium, visitors: 0, signups: 0, confirmed: 0 });
    return utm.get(key)!;
  };
  for (const r of utmVisits) row(r).visitors = Number(r.n);
  for (const r of utmSubs) { const x = row(r); x.signups = Number(r.n); x.confirmed = Number(r.c); }

  return {
    visitors: n(visitors), signups: n(signups), confirmed: n(confirmed), referrals: n(referrals), unsubscribed: n(unsubscribed),
    totalConfirmed: total,
    emails: { sent, delivered: eventCount("delivered"), opened: eventCount("opened"), clicked: eventCount("clicked"), bounced: eventCount("bounced"), complained: eventCount("complained") },
    daily: daily.map((d) => ({ day: d.day.toISOString().slice(0, 10), visitors: Number(d.visitors), signups: Number(d.signups) })),
    sources: sourceNames
      .map((name) => ({ source: name, visitors: Number(sources.find((s) => s.source === name)?.n ?? 0), signups: Number(subBySource.get(name)?.n ?? 0), confirmed: Number(subBySource.get(name)?.c ?? 0) }))
      .sort((a, b) => b.visitors + b.signups - (a.visitors + a.signups)).slice(0, 12),
    countries: countries.map((c) => ({ country: c.country, signups: Number(c.n) })),
    utm: [...utm.values()].sort((a, b) => b.signups - a.signups || b.visitors - a.visitors).slice(0, 30),
  };
}
