import { recordEmailEvent, verifyWebhookSignature } from "@/lib/email/webhook";
import { env } from "@/lib/env";

export const dynamic = "force-dynamic";

/**
 * Delivery events from Resend (delivered, opened, clicked, bounced, complained…).
 * These are the only source of e-mail statistics shown in the back office.
 * Requests without a valid Svix signature are rejected.
 */
export async function POST(req: Request) {
  const secret = env().RESEND_WEBHOOK_SECRET;
  if (!secret) return new Response("Webhook secret not configured", { status: 503 });
  const body = await req.text();
  if (body.length > 256_000) return new Response("Payload too large", { status: 413 });
  const valid = verifyWebhookSignature(
    secret,
    { id: req.headers.get("svix-id"), timestamp: req.headers.get("svix-timestamp"), signature: req.headers.get("svix-signature") },
    body,
  );
  if (!valid) return new Response("Invalid signature", { status: 401 });
  let event: unknown;
  try {
    event = JSON.parse(body);
  } catch {
    return new Response("Invalid JSON", { status: 400 });
  }
  const result = await recordEmailEvent(event as Parameters<typeof recordEmailEvent>[0]);
  return Response.json({ ok: true, result });
}
