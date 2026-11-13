import { safeEqual } from "@/lib/crypto";
import { processDueEmails } from "@/lib/email/sequences";
import { env } from "@/lib/env";
import { applyRetention } from "@/lib/retention";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

/**
 * Scheduled job (see vercel.json): sends the automated e-mails that are due
 * and applies data-retention rules. Vercel Cron calls it with
 * "Authorization: Bearer <CRON_SECRET>"; without that secret configured the
 * endpoint refuses every call.
 */
export async function GET(req: Request) {
  const secret = env().CRON_SECRET;
  const given = req.headers.get("authorization") ?? "";
  if (!secret || !safeEqual(given, `Bearer ${secret}`)) return new Response("Unauthorized", { status: 401 });

  const emails = await processDueEmails();
  const retention = await applyRetention();
  return Response.json({ ok: true, emails, retention });
}
