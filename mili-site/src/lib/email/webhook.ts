import "server-only";
import { createHmac, timingSafeEqual } from "node:crypto";
import { db } from "../db";

/**
 * Verifies a Resend webhook (Svix signature scheme):
 * signature = base64(HMAC-SHA256(secret, `${id}.${timestamp}.${body}`)).
 */
export function verifyWebhookSignature(
  secret: string,
  headers: { id: string | null; timestamp: string | null; signature: string | null },
  body: string,
  nowMs = Date.now(),
): boolean {
  if (!headers.id || !headers.timestamp || !headers.signature) return false;
  const ts = Number(headers.timestamp);
  if (!Number.isFinite(ts) || Math.abs(nowMs / 1000 - ts) > 5 * 60) return false; // replay window
  const key = Buffer.from(secret.replace(/^whsec_/, ""), "base64");
  const expected = createHmac("sha256", key).update(`${headers.id}.${headers.timestamp}.${body}`).digest();
  return headers.signature.split(" ").some((part) => {
    const [version, value] = part.split(",");
    if (version !== "v1" || !value) return false;
    const given = Buffer.from(value, "base64");
    return given.length === expected.length && timingSafeEqual(given, expected);
  });
}

type ResendEvent = { type?: string; created_at?: string; data?: { email_id?: string; bounce?: { type?: string } } };

const TRACKED = new Set(["email.sent", "email.delivered", "email.opened", "email.clicked", "email.bounced", "email.complained", "email.delivery_delayed"]);

/** Stores a provider event and applies its consequences (bounces and complaints stop all sending). */
export async function recordEmailEvent(event: ResendEvent): Promise<"stored" | "ignored"> {
  const providerId = event.data?.email_id;
  if (!event.type || !providerId || !TRACKED.has(event.type)) return "ignored";
  const type = event.type.replace(/^email\./, "");
  const occurredAt = event.created_at ? new Date(event.created_at) : new Date();
  const send = await db.emailSend.findUnique({ where: { providerId } });
  await db.emailEvent.upsert({
    where: { providerId_type_occurredAt: { providerId, type, occurredAt } },
    update: {},
    create: { providerId, type, occurredAt, sendId: send?.id },
  });
  if (send?.subscriberId) {
    const hardBounce = type === "bounced" && event.data?.bounce?.type !== "Transient";
    if (hardBounce) await db.subscriber.updateMany({ where: { id: send.subscriberId }, data: { status: "BOUNCED" } });
    if (type === "complained") {
      await db.subscriber.updateMany({
        where: { id: send.subscriberId },
        data: { status: "COMPLAINED", marketingConsent: false, unsubscribedAt: new Date() },
      });
      await db.consentEvent.create({
        data: { subscriberId: send.subscriberId, action: "WITHDRAWN", textVersion: "n/a", source: "spam_complaint" },
      });
    }
  }
  return "stored";
}
