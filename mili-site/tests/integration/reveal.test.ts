import { beforeEach, describe, expect, it } from "vitest";
import { publicClues, publicFaqs, publicProofVideos, revealContent } from "@/lib/content";
import { db } from "@/lib/db";
import { processDueEmails } from "@/lib/email/sequences";
import { subscriberVars } from "@/lib/email/send";
import { applyRetention } from "@/lib/retention";
import { getSettings } from "@/lib/settings";
import { confirmSubscription, subscribe } from "@/lib/subscribers";
import { ctx, plantConfirmToken, resetDatabase } from "../helpers";

const SECRET = "SECRET-SPINDLE-42";

async function seedSecrets() {
  await db.productSection.updateMany({ where: { key: "overview" }, data: { body: { en: `Spindle ${SECRET}` }, published: true } });
  await db.productSpec.create({ data: { groupName: { en: "G" }, label: { en: "Validated" }, value: { en: `${SECRET} rpm` }, validated: true } });
  await db.productSpec.create({ data: { groupName: { en: "G" }, label: { en: "Unvalidated" }, value: { en: "NOT-VALIDATED" }, validated: false } });
  await db.siteSettings.update({ where: { id: 1 }, data: { filmUrl: "https://youtu.be/abcdefghijk", kickstarterUrl: "https://www.kickstarter.com/projects/mili/mili" } });
}

describe("Mystery / Reveal gate", () => {
  beforeEach(resetDatabase);

  it("returns nothing about the product while in Mystery mode", async () => {
    await seedSecrets();
    expect(await revealContent("en")).toBeNull();
  });

  it("an authenticated preview sees the content before the reveal", async () => {
    await seedSecrets();
    const preview = await revealContent("en", { preview: true });
    expect(JSON.stringify(preview)).toContain(SECRET);
  });

  it("after the reveal, shows validated figures only and active rewards only", async () => {
    await seedSecrets();
    await db.siteSettings.update({ where: { id: 1 }, data: { mode: "REVEAL" } });
    const content = await revealContent("en");
    const json = JSON.stringify(content);
    expect(json).toContain(SECRET);
    expect(json).not.toContain("NOT-VALIDATED");
    // The seeded reward tiers are proposals: none is shown until a Super Admin activates it.
    expect(content?.tiers).toEqual([]);
  });

  it("keeps Reveal-only FAQ entries out of Mystery mode", async () => {
    await db.faq.create({ data: { question: { en: "Secret question" }, answer: { en: SECRET }, scope: "REVEAL" } });
    expect(JSON.stringify(await publicFaqs("en", "MYSTERY"))).not.toContain(SECRET);
    expect(JSON.stringify(await publicFaqs("en", "REVEAL"))).toContain(SECRET);
  });

  it("never sends the Kickstarter link by e-mail before the reveal", async () => {
    await seedSecrets();
    await subscribe({ email: "a@example.org", locale: "en" }, ctx());
    const sub = await db.subscriber.findUniqueOrThrow({ where: { email: "a@example.org" } });
    expect(subscriberVars(sub, await getSettings()).kickstarterUrl).toBe("");
    await db.siteSettings.update({ where: { id: 1 }, data: { mode: "REVEAL" } });
    expect(subscriberVars(sub, await getSettings()).kickstarterUrl).toContain("kickstarter.com");
  });
});

describe("Clues and proof", () => {
  beforeEach(resetDatabase);

  it("sends no title or content for a clue that is not open yet", async () => {
    await db.clue.deleteMany();
    await db.clue.create({ data: { number: 1, title: { en: "Open" }, content: { en: "visible" }, status: "PUBLISHED" } });
    await db.clue.create({ data: { number: 2, title: { en: SECRET }, content: { en: SECRET }, status: "SCHEDULED", publishAt: new Date(Date.now() + 86_400_000) } });
    await db.clue.create({ data: { number: 3, title: { en: "Draft" }, content: { en: SECRET }, status: "DRAFT" } });
    const clues = await publicClues("en");
    expect(clues.map((c) => [c.number, c.unlocked])).toEqual([[1, true], [2, false]]);
    expect(JSON.stringify(clues)).not.toContain(SECRET);
    // …and it opens by itself once its date has passed.
    const later = await publicClues("en", new Date(Date.now() + 2 * 86_400_000));
    expect(later[1]).toMatchObject({ unlocked: true, title: SECRET });
  });

  it("lists a demonstration only when it is both published and technically validated", async () => {
    const base = { title: { en: "T" }, description: {}, category: "FIVE_AXIS" as const, videoUrl: "https://youtu.be/abcdefghijk" };
    await db.proofVideo.create({ data: { ...base, status: "PUBLISHED", validated: false } });
    await db.proofVideo.create({ data: { ...base, status: "DRAFT", validated: true } });
    expect(await publicProofVideos("en")).toEqual([]);
    await db.proofVideo.create({ data: { ...base, status: "PUBLISHED", validated: true } });
    expect(await publicProofVideos("en")).toHaveLength(1);
  });
});

describe("Automation and retention", () => {
  beforeEach(resetDatabase);

  it("claims no delivery while no e-mail provider is configured", async () => {
    await subscribe({ email: "b@example.org", locale: "en" }, ctx());
    await plantConfirmToken("b@example.org", "tok-b");
    await confirmSubscription("tok-b");
    const reports = await processDueEmails(new Date(Date.now() + 10 * 86_400_000));
    expect(reports.length).toBeGreaterThan(0);
    expect(reports.every((r) => r.sent === 0 && r.skippedReason === "No e-mail provider configured")).toBe(true);
    expect(await db.emailSend.count({ where: { status: "SENT" } })).toBe(0);
    expect(await db.emailSend.count({ where: { stepId: { not: null }, status: "QUEUED" } })).toBe(0);
  });

  it("deletes unconfirmed registrations after 30 days and keeps confirmed ones", async () => {
    await subscribe({ email: "old@example.org", locale: "en" }, ctx("1"));
    await subscribe({ email: "new@example.org", locale: "en" }, ctx("2"));
    await subscribe({ email: "kept@example.org", locale: "en" }, ctx("3"));
    await plantConfirmToken("kept@example.org", "tok-k");
    await confirmSubscription("tok-k");
    const longAgo = new Date(Date.now() - 40 * 86_400_000);
    await db.subscriber.updateMany({ where: { email: { in: ["old@example.org", "kept@example.org"] } }, data: { createdAt: longAgo } });
    const result = await applyRetention();
    expect(result.pendingSubscribers).toBe(1);
    expect((await db.subscriber.findMany({ orderBy: { email: "asc" } })).map((s) => s.email)).toEqual(["kept@example.org", "new@example.org"]);
  });
});
