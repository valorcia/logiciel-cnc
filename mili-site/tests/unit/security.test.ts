import { createHmac } from "node:crypto";
import { describe, expect, it } from "vitest";
import { attributeSource } from "@/lib/analytics";
import { hashToken, ipHash, randomCode, randomToken, sign, verify, visitorHash } from "@/lib/crypto";
import { verifyWebhookSignature } from "@/lib/email/webhook";
import { insiderToken, parseInsiderToken, referralShareUrl, verifyManageSignature } from "@/lib/links";
import { can, permissions } from "@/lib/permissions";
import { isDisposableEmail, normalizeEmail, parseUtm, subscribeSchema } from "@/lib/validation";

describe("tokens and hashes", () => {
  it("generates unpredictable tokens and readable codes", () => {
    expect(randomToken()).not.toBe(randomToken());
    expect(randomToken().length).toBeGreaterThanOrEqual(43);
    expect(randomCode(7)).toMatch(/^[A-HJ-NP-Z2-9]{7}$/);
    expect(hashToken("a")).toHaveLength(64);
  });

  it("signs payloads and rejects tampering", () => {
    const token = sign("form", { t: 1 });
    expect(verify("form", token)).toEqual({ t: 1 });
    expect(verify("other", token)).toBeNull();
    expect(verify("form", token.replace(/.$/, "x"))).toBeNull();
    expect(verify("form", null)).toBeNull();
  });

  it("never exposes the IP and rotates the analytics identifier daily", () => {
    expect(ipHash("203.0.113.9")).not.toContain("203");
    expect(visitorHash("1.1.1.1", "ua", "2026-11-13")).not.toBe(visitorHash("1.1.1.1", "ua", "2026-11-14"));
  });
});

describe("personal links", () => {
  const sub = { id: "sub_1", publicId: "MILI-ABCD2345", tokenVersion: 1 };
  it("round-trips and verifies a personal token", () => {
    const parsed = parseInsiderToken(insiderToken(sub));
    expect(parsed?.publicId).toBe("MILI-ABCD2345");
    expect(verifyManageSignature(sub, parsed!.signature)).toBe(true);
  });
  it("is invalidated by a token version bump and rejects forgeries", () => {
    const parsed = parseInsiderToken(insiderToken(sub))!;
    expect(verifyManageSignature({ ...sub, tokenVersion: 2 }, parsed.signature)).toBe(false);
    expect(verifyManageSignature({ ...sub, id: "sub_2" }, parsed.signature)).toBe(false);
    expect(parseInsiderToken("MILI-ABCD2345")).toBeNull();
    expect(parseInsiderToken("../../etc/passwd")).toBeNull();
  });
  it("tags shared referral links with UTM parameters", () => {
    const url = new URL(referralShareUrl("ABC2345", "reddit"));
    expect(url.pathname).toBe("/invite/ABC2345");
    expect(url.searchParams.get("utm_source")).toBe("reddit");
    expect(url.searchParams.get("utm_medium")).toBe("referral");
  });
});

describe("Resend webhook signature", () => {
  const secret = `whsec_${Buffer.from("super-secret-key").toString("base64")}`;
  const body = '{"type":"email.delivered"}';
  const now = 1_800_000_000_000;
  const ts = String(now / 1000);
  const good = createHmac("sha256", Buffer.from("super-secret-key")).update(`msg_1.${ts}.${body}`).digest("base64");

  it("accepts a valid signature", () => {
    expect(verifyWebhookSignature(secret, { id: "msg_1", timestamp: ts, signature: `v1,${good}` }, body, now)).toBe(true);
  });
  it("rejects a wrong signature, a modified body and a replayed message", () => {
    expect(verifyWebhookSignature(secret, { id: "msg_1", timestamp: ts, signature: "v1,AAAA" }, body, now)).toBe(false);
    expect(verifyWebhookSignature(secret, { id: "msg_1", timestamp: ts, signature: `v1,${good}` }, body + " ", now)).toBe(false);
    expect(verifyWebhookSignature(secret, { id: "msg_1", timestamp: ts, signature: `v1,${good}` }, body, now + 10 * 60_000)).toBe(false);
    expect(verifyWebhookSignature(secret, { id: null, timestamp: ts, signature: `v1,${good}` }, body, now)).toBe(false);
  });
});

describe("validation", () => {
  it("normalises e-mail aliases to detect duplicates", () => {
    expect(normalizeEmail("John.Doe+mili@GoogleMail.com")).toBe("johndoe@gmail.com");
    expect(normalizeEmail("a.b+x@proton.me")).toBe("a.b@proton.me");
  });
  it("flags disposable domains", () => {
    expect(isDisposableEmail("x@mailinator.com")).toBe(true);
    expect(isDisposableEmail("x@gmail.com")).toBe(false);
  });
  it("requires explicit consent to subscribe", () => {
    expect(subscribeSchema.safeParse({ email: "a@b.co", consent: false }).success).toBe(false);
    const ok = subscribeSchema.safeParse({ email: " A@B.co ", consent: true, country: "us", firstName: "" });
    expect(ok.success && ok.data).toMatchObject({ email: "a@b.co", country: "US", locale: "en" });
    expect(ok.success && ok.data.firstName).toBeUndefined();
  });
  it("keeps only clean UTM values", () => {
    const params = new URLSearchParams("utm_source=reddit&utm_campaign=<script>&utm_medium=social+post");
    expect(parseUtm((k) => params.get(k))).toEqual({ utmSource: "reddit", utmMedium: "social post" });
  });
  it("attributes a visit to its channel", () => {
    expect(attributeSource("Reddit", "https://x.com", "mili.test")).toBe("reddit");
    expect(attributeSource(undefined, "https://www.youtube.com/watch", "mili.test")).toBe("youtube.com");
    expect(attributeSource(undefined, "https://mili.test/journal", "mili.test")).toBe("direct");
    expect(attributeSource(undefined, null, "mili.test")).toBe("direct");
  });
});

describe("role permissions", () => {
  it("gives the Super Admin everything and Read Only nothing but the dashboard", () => {
    for (const p of permissions) expect(can("SUPER_ADMIN", p)).toBe(true);
    expect(permissions.filter((p) => can("READ_ONLY", p))).toEqual(["dashboard.view"]);
  });
  it("reserves the reveal switch, validations and user management to the Super Admin", () => {
    for (const role of ["MARKETING_ADMIN", "CONTENT_EDITOR", "READ_ONLY"] as const) {
      expect(can(role, "reveal.switch")).toBe(false);
      expect(can(role, "users.manage")).toBe(false);
      expect(can(role, "product.validate")).toBe(false);
      expect(can(role, "proof.validate")).toBe(false);
    }
  });
  it("keeps prospects' personal data away from Content Editors", () => {
    expect(can("CONTENT_EDITOR", "prospects.view")).toBe(false);
    expect(can("CONTENT_EDITOR", "prospects.export")).toBe(false);
    expect(can("MARKETING_ADMIN", "prospects.export")).toBe(true);
  });
});
