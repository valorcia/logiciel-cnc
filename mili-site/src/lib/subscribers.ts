import "server-only";
import { hashToken, randomCode, randomToken } from "./crypto";
import { db } from "./db";
import { sendImmediateWelcome } from "./email/sequences";
import { sendToSubscriber } from "./email/send";
import { confirmUrl, parseInsiderToken, verifyManageSignature } from "./links";
import { isDisposableEmail, normalizeEmail, type Utm } from "./validation";
import type { Subscriber } from "@/generated/prisma/client";

/** Version of the consent wording shown next to the sign-up checkbox. Bump it when the text changes. */
export const CONSENT_VERSION = "2026-11-v1";
const CONFIRM_TTL_MS = 7 * 24 * 60 * 60 * 1000;

export type SubscribeInput = {
  email: string;
  firstName?: string;
  country?: string;
  locale: string;
};

export type SubscribeContext = {
  ipHash: string;
  userAgent: string;
  utm: Utm;
  referralCode?: string | null;
  referrerHost?: string | null;
  landingPath?: string | null;
};

export type SubscribeOutcome = { ok: true } | { ok: false; error: "disposable" };

async function uniqueCode(field: "referralCode" | "publicId"): Promise<string> {
  for (let attempt = 0; attempt < 8; attempt++) {
    const value = field === "publicId" ? `MILLI-${randomCode(8)}` : randomCode(7);
    const clash = await db.subscriber.findFirst({ where: { [field]: value }, select: { id: true } });
    if (!clash) return value;
  }
  throw new Error(`Could not allocate a unique ${field}`);
}

async function issueConfirmation(sub: Subscriber): Promise<void> {
  const token = randomToken();
  const updated = await db.subscriber.update({
    where: { id: sub.id },
    data: { confirmTokenHash: hashToken(token), confirmSentAt: new Date() },
  });
  await sendToSubscriber(updated, "confirm", {
    kind: "TRANSACTIONAL",
    extraVars: { confirmUrl: confirmUrl(token, updated.locale) },
  });
}

/**
 * Sign-up with double opt-in. The response is identical whether or not the
 * address was already known, so the form cannot be used to probe the list.
 */
export async function subscribe(input: SubscribeInput, ctx: SubscribeContext): Promise<SubscribeOutcome> {
  if (isDisposableEmail(input.email)) return { ok: false, error: "disposable" };

  const existing = await db.subscriber.findUnique({ where: { email: input.email } });
  if (existing) {
    if (existing.status === "CONFIRMED") {
      await sendToSubscriber(existing, "already-subscribed", { kind: "TRANSACTIONAL" });
      return { ok: true };
    }
    if (existing.status === "BOUNCED" || existing.status === "COMPLAINED") return { ok: true };
    // PENDING or UNSUBSCRIBED: a fresh, explicit consent restarts the opt-in.
    const refreshed = await db.subscriber.update({
      where: { id: existing.id },
      data: {
        status: "PENDING",
        marketingConsent: true,
        unsubscribedAt: null,
        firstName: input.firstName ?? existing.firstName,
        country: input.country ?? existing.country,
        locale: input.locale,
      },
    });
    await db.consentEvent.create({
      data: {
        subscriberId: existing.id, action: "GRANTED", textVersion: CONSENT_VERSION,
        source: "signup_form", ipHash: ctx.ipHash, userAgent: ctx.userAgent,
      },
    });
    await issueConfirmation(refreshed);
    return { ok: true };
  }

  const emailNormalized = normalizeEmail(input.email);
  let referredById: string | null = null;
  if (ctx.referralCode) {
    const referrer = await db.subscriber.findUnique({ where: { referralCode: ctx.referralCode.toUpperCase() } });
    if (referrer && referrer.status === "CONFIRMED" && referrer.emailNormalized !== emailNormalized) {
      referredById = referrer.id;
    }
  }

  const created = await db.subscriber.create({
    data: {
      publicId: await uniqueCode("publicId"),
      referralCode: await uniqueCode("referralCode"),
      email: input.email,
      emailNormalized,
      firstName: input.firstName,
      country: input.country,
      locale: input.locale,
      marketingConsent: true,
      referredById,
      ipHash: ctx.ipHash,
      userAgent: ctx.userAgent,
      referrerHost: ctx.referrerHost?.slice(0, 120),
      landingPath: ctx.landingPath?.slice(0, 200),
      ...ctx.utm,
      consents: {
        create: {
          action: "GRANTED", textVersion: CONSENT_VERSION, source: "signup_form",
          ipHash: ctx.ipHash, userAgent: ctx.userAgent,
        },
      },
    },
  });
  await issueConfirmation(created);
  return { ok: true };
}

/** Decides whether a confirmed referral may count. Returns a reason when it must be reviewed instead. */
async function referralFlag(sub: Subscriber): Promise<string | null> {
  if (!sub.referredById) return null;
  const referrer = await db.subscriber.findUnique({ where: { id: sub.referredById } });
  if (!referrer) return null;
  if (sub.ipHash && referrer.ipHash && sub.ipHash === referrer.ipHash) return "Same network as the referrer";
  const alias = await db.subscriber.count({ where: { emailNormalized: sub.emailNormalized, id: { not: sub.id } } });
  if (alias > 0) return "Alias of an address already on the list";
  if (sub.ipHash) {
    const sameNetwork = await db.subscriber.count({
      where: {
        referredById: referrer.id, ipHash: sub.ipHash, id: { not: sub.id },
        confirmedAt: { gte: new Date(Date.now() - 24 * 60 * 60 * 1000) },
      },
    });
    if (sameNetwork >= 2) return "Several referrals from one network within 24 hours";
  }
  return null;
}

export type ConfirmOutcome =
  | { ok: true; subscriber: Subscriber; alreadyConfirmed: boolean }
  | { ok: false; error: "invalid" | "expired" };

export async function confirmSubscription(token: string, ctx: { ipHash?: string; userAgent?: string } = {}): Promise<ConfirmOutcome> {
  if (!token || token.length > 200) return { ok: false, error: "invalid" };
  const sub = await db.subscriber.findUnique({ where: { confirmTokenHash: hashToken(token) } });
  if (!sub) return { ok: false, error: "invalid" };
  if (sub.status === "CONFIRMED") return { ok: true, subscriber: sub, alreadyConfirmed: true };
  if (sub.status !== "PENDING") return { ok: false, error: "invalid" };
  if (!sub.confirmSentAt || Date.now() - sub.confirmSentAt.getTime() > CONFIRM_TTL_MS) return { ok: false, error: "expired" };

  const flag = await referralFlag(sub);
  const confirmed = await db.subscriber.update({
    where: { id: sub.id },
    data: {
      status: "CONFIRMED",
      confirmedAt: new Date(),
      referralFlagged: Boolean(flag),
      referralFlagNote: flag,
      consents: {
        create: {
          action: "CONFIRMED", textVersion: CONSENT_VERSION, source: "double_opt_in",
          ipHash: ctx.ipHash, userAgent: ctx.userAgent,
        },
      },
    },
  });
  await sendImmediateWelcome(confirmed);
  return { ok: true, subscriber: confirmed, alreadyConfirmed: false };
}

/** Resolves a personal link (insider space, unsubscribe, export, deletion). */
export async function subscriberFromToken(token: string): Promise<Subscriber | null> {
  const parsed = parseInsiderToken(token);
  if (!parsed) return null;
  const sub = await db.subscriber.findUnique({ where: { publicId: parsed.publicId } });
  if (!sub || !verifyManageSignature(sub, parsed.signature)) return null;
  return sub;
}

export async function unsubscribe(sub: Subscriber, source: string, ctx: { ipHash?: string; userAgent?: string } = {}): Promise<void> {
  if (sub.status === "UNSUBSCRIBED" && !sub.marketingConsent) return;
  await db.subscriber.update({
    where: { id: sub.id },
    data: {
      status: sub.status === "BOUNCED" || sub.status === "COMPLAINED" ? sub.status : "UNSUBSCRIBED",
      marketingConsent: false,
      unsubscribedAt: new Date(),
      consents: { create: { action: "WITHDRAWN", textVersion: CONSENT_VERSION, source, ipHash: ctx.ipHash, userAgent: ctx.userAgent } },
    },
  });
}

/** Permanent erasure (GDPR art. 17). Consent history and e-mail links go with the row. */
export async function eraseSubscriber(id: string): Promise<void> {
  await db.subscriber.delete({ where: { id } });
}

/** Everything held about a subscriber, in a portable form (GDPR art. 15 and 20). */
export async function exportSubscriber(id: string) {
  const sub = await db.subscriber.findUnique({
    where: { id },
    include: {
      consents: { orderBy: { createdAt: "asc" } },
      emailSends: { orderBy: { createdAt: "asc" }, select: { templateKey: true, subject: true, status: true, createdAt: true } },
    },
  });
  if (!sub) return null;
  const stats = await referralStats(sub.id);
  return {
    exportedAt: new Date().toISOString(),
    profile: {
      publicId: sub.publicId, email: sub.email, firstName: sub.firstName, country: sub.country, locale: sub.locale,
      status: sub.status, marketingConsent: sub.marketingConsent, createdAt: sub.createdAt, confirmedAt: sub.confirmedAt,
      unsubscribedAt: sub.unsubscribedAt,
    },
    acquisition: {
      utmSource: sub.utmSource, utmMedium: sub.utmMedium, utmCampaign: sub.utmCampaign, utmTerm: sub.utmTerm,
      utmContent: sub.utmContent, referrerHost: sub.referrerHost, landingPath: sub.landingPath, userAgent: sub.userAgent,
    },
    referral: { code: sub.referralCode, confirmedReferrals: stats.points, wasReferred: Boolean(sub.referredById) },
    consentHistory: sub.consents.map((c) => ({
      purpose: c.purpose, action: c.action, textVersion: c.textVersion, source: c.source, at: c.createdAt,
    })),
    emails: sub.emailSends,
  };
}

export type ReferralStats = { points: number; pending: number; underReview: number };

/** A point is a referred person who confirmed their address and was not flagged by the fraud rules. */
export async function referralStats(subscriberId: string): Promise<ReferralStats> {
  const referred = await db.subscriber.findMany({
    where: { referredById: subscriberId },
    select: { confirmedAt: true, referralFlagged: true },
  });
  let points = 0, pending = 0, underReview = 0;
  for (const r of referred) {
    if (!r.confirmedAt) pending++;
    else if (r.referralFlagged) underReview++;
    else points++;
  }
  return { points, pending, underReview };
}

export type LeaderboardRow = { rank: number; label: string; points: number };

/** Top referrers, identified only by a masked public id — no personal data. */
export async function leaderboard(limit = 10): Promise<LeaderboardRow[]> {
  const grouped = await db.subscriber.groupBy({
    by: ["referredById"],
    where: { referredById: { not: null }, confirmedAt: { not: null }, referralFlagged: false },
    _count: { _all: true },
    orderBy: { _count: { referredById: "desc" } },
    take: limit,
  });
  const ids = grouped.map((g) => g.referredById!).filter(Boolean);
  const owners = await db.subscriber.findMany({ where: { id: { in: ids } }, select: { id: true, publicId: true } });
  const publicIds = new Map(owners.map((o) => [o.id, o.publicId]));
  return grouped.map((g, index) => ({
    rank: index + 1,
    label: `${(publicIds.get(g.referredById!) ?? "MILLI-????????").slice(0, 9)}••••`,
    points: g._count._all,
  }));
}

export async function referralRank(subscriberId: string, points: number): Promise<number | null> {
  if (points === 0) return null;
  const rows = await db.$queryRaw<{ ahead: bigint }[]>`
    SELECT count(*)::bigint AS ahead FROM (
      SELECT "referredById" FROM "Subscriber"
      WHERE "referredById" IS NOT NULL AND "confirmedAt" IS NOT NULL AND "referralFlagged" = false
        AND "referredById" <> ${subscriberId}
      GROUP BY "referredById" HAVING count(*) > ${points}
    ) t`;
  return Number(rows[0]?.ahead ?? 0) + 1;
}
