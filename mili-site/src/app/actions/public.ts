"use server";

import { createId } from "@/lib/ids";
import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { newFormToken, plausibleSubmission } from "@/lib/antispam";
import { hmac, randomToken, sign, verify } from "@/lib/crypto";
import { db } from "@/lib/db";
import { CHALLENGE_FILE_TYPES, checkUpload } from "@/lib/files";
import { rateLimit } from "@/lib/rate-limit";
import { requestMeta } from "@/lib/request";
import { maxUploadBytes, storage } from "@/lib/storage";
import { eraseSubscriber, subscribe, subscriberFromToken, unsubscribe } from "@/lib/subscribers";
import { challengeSchema, inquirySchema, parseUtm, subscribeSchema } from "@/lib/validation";

export type FormState =
  | { status: "idle" }
  | { status: "success"; email?: string }
  | { status: "error"; code: string; fields?: Record<string, string> };

/** Handed to forms when they are displayed; see src/lib/antispam.ts. */
export async function issueFormToken(): Promise<string> {
  return newFormToken();
}

function fieldErrors(issues: { path: PropertyKey[]; message: string }[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const issue of issues) {
    const field = String(issue.path[0] ?? "form");
    if (!out[field]) out[field] = field === "consent" ? "consent" : field === "email" ? "email" : field;
  }
  return out;
}

const text = (formData: FormData, key: string) => {
  const value = formData.get(key);
  return typeof value === "string" ? value : "";
};

/* ───────────── Insider List sign-up ───────────── */

export async function subscribeAction(_prev: FormState, formData: FormData): Promise<FormState> {
  if (!plausibleSubmission(formData)) return { status: "error", code: "spam" };
  const meta = await requestMeta();
  const limit = await rateLimit(`subscribe:${meta.ipHash}`, 6, 3600);
  if (!limit.allowed) return { status: "error", code: "rate" };

  const parsed = subscribeSchema.safeParse({
    email: text(formData, "email"),
    firstName: text(formData, "firstName"),
    country: text(formData, "country"),
    locale: text(formData, "locale") || "en",
    consent: formData.get("consent") === "on",
  });
  if (!parsed.success) return { status: "error", code: "invalid", fields: fieldErrors(parsed.error.issues) };

  // Three confirmation e-mails per address and per hour at most: the form cannot be used to flood an inbox.
  const perAddress = await rateLimit(`subscribe-to:${hmac("email", parsed.data.email).slice(0, 24)}`, 3, 3600);
  if (!perAddress.allowed) return { status: "success", email: parsed.data.email };

  const jar = await cookies();
  const result = await subscribe(parsed.data, {
    ipHash: meta.ipHash,
    userAgent: meta.userAgent,
    utm: parseUtm((key) => text(formData, key)),
    referralCode: jar.get("milli_ref")?.value ?? null,
    referrerHost: safeHost(text(formData, "referrer")),
    landingPath: text(formData, "landing") || null,
  });
  if (!result.ok) return { status: "error", code: result.error, fields: { email: result.error } };
  return { status: "success", email: parsed.data.email };
}

function safeHost(url: string): string | null {
  try {
    return new URL(url).hostname;
  } catch {
    return null;
  }
}

/* ───────────── Challenge submission ───────────── */

export async function submitChallengeAction(_prev: FormState, formData: FormData): Promise<FormState> {
  if (!plausibleSubmission(formData)) return { status: "error", code: "spam" };
  const meta = await requestMeta();
  const limit = await rateLimit(`challenge:${meta.ipHash}`, 5, 3600);
  if (!limit.allowed) return { status: "error", code: "rate" };

  const parsed = challengeSchema.safeParse({
    name: text(formData, "name"),
    email: text(formData, "email"),
    description: text(formData, "description"),
    category: text(formData, "category"),
    locale: text(formData, "locale") || "en",
    consent: formData.get("consent") === "on",
  });
  if (!parsed.success) return { status: "error", code: "invalid", fields: fieldErrors(parsed.error.issues) };

  let file: { key: string; name: string; mime: string; size: number } | null = null;
  const upload = formData.get("file");
  if (upload instanceof File && upload.size > 0) {
    if (upload.size > maxUploadBytes()) return { status: "error", code: "fileTooLarge", fields: { file: "fileTooLarge" } };
    const bytes = new Uint8Array(await upload.arrayBuffer());
    const check = checkUpload(bytes, upload.name, CHALLENGE_FILE_TYPES, maxUploadBytes());
    if (!check.ok) {
      const code = check.error === "too_large" ? "fileTooLarge" : check.error === "extension_mismatch" ? "fileMismatch" : "fileType";
      return { status: "error", code, fields: { file: code } };
    }
    // The stored name is generated; the original name is kept only as metadata.
    const key = `challenges/${createId()}.${check.file.ext}`;
    await storage().put(key, bytes, check.file.mime);
    file = { key, name: check.safeName, mime: check.file.mime, size: bytes.length };
  }

  await db.challenge.create({
    data: {
      name: parsed.data.name,
      email: parsed.data.email,
      description: parsed.data.description,
      category: parsed.data.category,
      locale: parsed.data.locale,
      ipHash: meta.ipHash,
      fileKey: file?.key,
      fileName: file?.name,
      fileMime: file?.mime,
      fileSize: file?.size,
    },
  });
  return { status: "success" };
}

/* ───────────── Votes ───────────── */

export type VoteResult = { ok: boolean; votes?: number; code?: "rate" | "alreadyVoted" | "generic" };

/**
 * One vote per browser and per challenge, at most three per network and per
 * challenge, thirty votes per hour per network. The voter id is a signed,
 * random, httpOnly cookie — it identifies a browser, not a person.
 */
export async function voteAction(challengeId: string): Promise<VoteResult> {
  if (!/^[a-z0-9]{10,40}$/.test(challengeId)) return { ok: false, code: "generic" };
  const meta = await requestMeta();
  const limit = await rateLimit(`vote:${meta.ipHash}`, 30, 3600);
  if (!limit.allowed) return { ok: false, code: "rate" };

  const jar = await cookies();
  let voter = verify<{ v: string }>("voter", jar.get("milli_voter")?.value)?.v;
  if (!voter) {
    voter = randomToken(16);
    jar.set("milli_voter", sign("voter", { v: voter }), {
      httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", maxAge: 60 * 60 * 24 * 365, path: "/",
    });
  }
  const voterHash = hmac("voter", voter).slice(0, 32);

  const challenge = await db.challenge.findFirst({ where: { id: challengeId, status: "APPROVED" }, select: { id: true } });
  if (!challenge) return { ok: false, code: "generic" };
  const sameNetwork = await db.challengeVote.count({ where: { challengeId, ipHash: meta.ipHash } });
  if (sameNetwork >= 3) return { ok: false, code: "rate" };

  try {
    const [, updated] = await db.$transaction([
      db.challengeVote.create({ data: { challengeId, voterHash, ipHash: meta.ipHash } }),
      db.challenge.update({ where: { id: challengeId }, data: { voteCount: { increment: 1 } }, select: { voteCount: true } }),
    ]);
    revalidatePath("/", "layout");
    return { ok: true, votes: updated.voteCount };
  } catch {
    return { ok: false, code: "alreadyVoted" };
  }
}

/* ───────────── Contact and GDPR requests ───────────── */

export async function inquiryAction(_prev: FormState, formData: FormData): Promise<FormState> {
  if (!plausibleSubmission(formData)) return { status: "error", code: "spam" };
  const meta = await requestMeta();
  const limit = await rateLimit(`inquiry:${meta.ipHash}`, 5, 3600);
  if (!limit.allowed) return { status: "error", code: "rate" };

  const parsed = inquirySchema.safeParse({
    kind: text(formData, "kind"),
    name: text(formData, "name"),
    email: text(formData, "email"),
    message: text(formData, "message"),
    locale: text(formData, "locale") || "en",
  });
  if (!parsed.success) return { status: "error", code: "invalid", fields: fieldErrors(parsed.error.issues) };
  await db.inquiry.create({ data: parsed.data });
  return { status: "success" };
}

/* ───────────── Self-service privacy controls ───────────── */

export async function unsubscribeAction(token: string): Promise<{ ok: boolean }> {
  const sub = await subscriberFromToken(token);
  if (!sub) return { ok: false };
  const meta = await requestMeta();
  await unsubscribe(sub, "unsubscribe_link", { ipHash: meta.ipHash, userAgent: meta.userAgent });
  return { ok: true };
}

export async function deleteMyDataAction(token: string): Promise<{ ok: boolean }> {
  const sub = await subscriberFromToken(token);
  if (!sub) return { ok: false };
  await eraseSubscriber(sub.id);
  await db.auditLog.create({ data: { action: "subscriber.self_erased", entity: "Subscriber", meta: {} } });
  return { ok: true };
}
