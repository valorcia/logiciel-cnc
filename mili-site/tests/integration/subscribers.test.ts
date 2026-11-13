import { beforeEach, describe, expect, it } from "vitest";
import { db } from "@/lib/db";
import { rateLimit } from "@/lib/rate-limit";
import {
  confirmSubscription, eraseSubscriber, exportSubscriber, leaderboard, referralRank, referralStats,
  subscribe, subscriberFromToken, unsubscribe,
} from "@/lib/subscribers";
import { insiderToken } from "@/lib/links";
import { ctx, plantConfirmToken, resetDatabase } from "../helpers";

async function join(email: string, opts: { ip?: string; ref?: string } = {}) {
  await subscribe({ email, locale: "en" }, { ...ctx(opts.ip ?? email), referralCode: opts.ref });
  return db.subscriber.findUniqueOrThrow({ where: { email } });
}

async function joinAndConfirm(email: string, opts: { ip?: string; ref?: string } = {}) {
  await join(email, opts);
  await plantConfirmToken(email, `tok-${email}`);
  const result = await confirmSubscription(`tok-${email}`, { ipHash: `iphash-${opts.ip ?? email}` });
  if (!result.ok) throw new Error(result.error);
  return result.subscriber;
}

beforeEach(resetDatabase);

describe("sign-up with double opt-in", () => {
  it("creates a pending prospect, records consent and issues a confirmation e-mail", async () => {
    const sub = await join("ana@example.com");
    expect(sub.status).toBe("PENDING");
    expect(sub.publicId).toMatch(/^MILI-[A-Z2-9]{8}$/);
    expect(sub.confirmTokenHash).toBeTruthy();
    const consents = await db.consentEvent.findMany({ where: { subscriberId: sub.id } });
    expect(consents.map((c) => c.action)).toEqual(["GRANTED"]);
    const sends = await db.emailSend.findMany({ where: { subscriberId: sub.id } });
    expect(sends).toHaveLength(1);
    expect(sends[0]).toMatchObject({ templateKey: "confirm", kind: "TRANSACTIONAL", status: "NOT_SENT_NO_PROVIDER" });
  });

  it("never sends marketing e-mail before the address is confirmed", async () => {
    const sub = await join("ana@example.com");
    const marketing = await db.emailSend.count({ where: { subscriberId: sub.id, templateKey: { startsWith: "welcome" } } });
    expect(marketing).toBe(0);
  });

  it("prevents duplicates: a second sign-up re-issues the confirmation instead of creating a row", async () => {
    const first = await join("ana@example.com");
    await join("ana@example.com");
    expect(await db.subscriber.count()).toBe(1);
    const again = await db.subscriber.findUniqueOrThrow({ where: { id: first.id } });
    expect(again.confirmTokenHash).not.toBe(first.confirmTokenHash);
  });

  it("rejects disposable addresses", async () => {
    const result = await subscribe({ email: "x@mailinator.com", locale: "en" }, ctx());
    expect(result).toEqual({ ok: false, error: "disposable" });
    expect(await db.subscriber.count()).toBe(0);
  });

  it("confirms with a valid token, then sends the welcome e-mail exactly once", async () => {
    const sub = await joinAndConfirm("ana@example.com");
    expect(sub.status).toBe("CONFIRMED");
    expect(sub.confirmedAt).toBeInstanceOf(Date);
    const again = await confirmSubscription("tok-ana@example.com");
    expect(again).toMatchObject({ ok: true, alreadyConfirmed: true });
    const welcome = await db.emailSend.count({ where: { subscriberId: sub.id, templateKey: "welcome-1" } });
    expect(welcome).toBe(1);
    const actions = (await db.consentEvent.findMany({ where: { subscriberId: sub.id }, orderBy: { createdAt: "asc" } })).map((c) => c.action);
    expect(actions).toEqual(["GRANTED", "CONFIRMED"]);
  });

  it("rejects unknown and expired tokens", async () => {
    expect(await confirmSubscription("nope")).toEqual({ ok: false, error: "invalid" });
    await join("ana@example.com");
    await plantConfirmToken("ana@example.com", "tok");
    await db.subscriber.update({ where: { email: "ana@example.com" }, data: { confirmSentAt: new Date(Date.now() - 8 * 86_400_000) } });
    expect(await confirmSubscription("tok")).toEqual({ ok: false, error: "expired" });
  });
});

describe("referral programme", () => {
  it("awards a point only when the referred person confirms", async () => {
    const referrer = await joinAndConfirm("ref@example.com");
    await join("friend1@example.com", { ref: referrer.referralCode });
    expect(await referralStats(referrer.id)).toEqual({ points: 0, pending: 1, underReview: 0 });
    await joinAndConfirm("friend2@example.com", { ref: referrer.referralCode });
    expect(await referralStats(referrer.id)).toEqual({ points: 1, pending: 1, underReview: 0 });
  });

  it("ignores codes of unconfirmed referrers and self-referral through an alias", async () => {
    const pending = await join("pending@example.com");
    const a = await join("a@example.com", { ref: pending.referralCode });
    expect(a.referredById).toBeNull();
    const referrer = await joinAndConfirm("me@gmail.com");
    const alias = await join("m.e+bonus@gmail.com", { ref: referrer.referralCode });
    expect(alias.referredById).toBeNull();
  });

  it("holds back referrals coming from the referrer's own network", async () => {
    const referrer = await joinAndConfirm("ref@example.com", { ip: "home" });
    const friend = await joinAndConfirm("sock@example.com", { ip: "home", ref: referrer.referralCode });
    expect(friend.referralFlagged).toBe(true);
    expect(await referralStats(referrer.id)).toEqual({ points: 0, pending: 0, underReview: 1 });
  });

  it("holds back a burst of referrals from a single network", async () => {
    const referrer = await joinAndConfirm("ref@example.com", { ip: "a" });
    await joinAndConfirm("f1@example.com", { ip: "cafe", ref: referrer.referralCode });
    await joinAndConfirm("f2@example.com", { ip: "cafe", ref: referrer.referralCode });
    const third = await joinAndConfirm("f3@example.com", { ip: "cafe", ref: referrer.referralCode });
    expect(third.referralFlagged).toBe(true);
    expect((await referralStats(referrer.id)).points).toBe(2);
  });

  it("ranks referrers without exposing personal data", async () => {
    const top = await joinAndConfirm("top@example.com");
    const second = await joinAndConfirm("second@example.com");
    await joinAndConfirm("t1@example.com", { ref: top.referralCode });
    await joinAndConfirm("t2@example.com", { ref: top.referralCode });
    await joinAndConfirm("s1@example.com", { ref: second.referralCode });
    expect(await referralRank(top.id, 2)).toBe(1);
    expect(await referralRank(second.id, 1)).toBe(2);
    const board = await leaderboard();
    expect(board.map((r) => r.points)).toEqual([2, 1]);
    expect(JSON.stringify(board)).not.toMatch(/example\.com|top|second/);
    expect(board[0].label).toMatch(/^MILI-[A-Z2-9]{3}••••$/);
  });
});

describe("GDPR rights", () => {
  it("resolves a personal link and rejects a forged one", async () => {
    const sub = await joinAndConfirm("ana@example.com");
    expect((await subscriberFromToken(insiderToken(sub)))?.id).toBe(sub.id);
    expect(await subscriberFromToken(`${sub.publicId}-${"A".repeat(32)}`)).toBeNull();
  });

  it("unsubscribes, records the withdrawal and stops marketing", async () => {
    const sub = await joinAndConfirm("ana@example.com");
    await unsubscribe(sub, "unsubscribe_link");
    const after = await db.subscriber.findUniqueOrThrow({ where: { id: sub.id } });
    expect(after).toMatchObject({ status: "UNSUBSCRIBED", marketingConsent: false });
    const last = await db.consentEvent.findFirst({ where: { subscriberId: sub.id }, orderBy: { createdAt: "desc" } });
    expect(last?.action).toBe("WITHDRAWN");
  });

  it("exports everything held about a person", async () => {
    const sub = await joinAndConfirm("ana@example.com");
    const data = await exportSubscriber(sub.id);
    expect(data?.profile.email).toBe("ana@example.com");
    expect(data?.consentHistory).toHaveLength(2);
    expect(data?.emails.map((e) => e.templateKey)).toEqual(["confirm", "welcome-1"]);
  });

  it("erases a person completely while keeping the referrer's row intact", async () => {
    const referrer = await joinAndConfirm("ref@example.com");
    const friend = await joinAndConfirm("friend@example.com", { ref: referrer.referralCode });
    await eraseSubscriber(friend.id);
    expect(await db.subscriber.findUnique({ where: { id: friend.id } })).toBeNull();
    expect(await db.consentEvent.count({ where: { subscriberId: friend.id } })).toBe(0);
    expect(await db.subscriber.findUnique({ where: { id: referrer.id } })).not.toBeNull();
    await eraseSubscriber(referrer.id);
    expect(await db.subscriber.count()).toBe(0);
  });
});

describe("rate limiting", () => {
  it("blocks after the limit and reports when to retry", async () => {
    const key = `test:${Date.now()}`;
    expect((await rateLimit(key, 2, 60)).allowed).toBe(true);
    expect((await rateLimit(key, 2, 60)).allowed).toBe(true);
    const blocked = await rateLimit(key, 2, 60);
    expect(blocked.allowed).toBe(false);
    expect(blocked.retryAfterSec).toBeGreaterThan(0);
  });
});
