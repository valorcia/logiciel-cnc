import { assertAdmin, ForbiddenError } from "@/lib/admin-session";
import { audit } from "@/lib/audit";
import { db } from "@/lib/db";
import type { Prisma, SubscriberStatus } from "@/generated/prisma/client";

/** Neutralises spreadsheet formula injection and escapes CSV. */
function cell(value: unknown): string {
  let text = value == null ? "" : value instanceof Date ? value.toISOString() : String(value);
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

export async function GET(req: Request) {
  let admin;
  try {
    admin = await assertAdmin("prospects.export");
  } catch (err) {
    if (err instanceof ForbiddenError) return new Response("Forbidden", { status: 403 });
    throw err;
  }
  const p = new URL(req.url).searchParams;
  const q = p.get("q")?.trim();
  const where: Prisma.SubscriberWhereInput = {
    ...(q ? { OR: [{ email: { contains: q, mode: "insensitive" } }, { firstName: { contains: q, mode: "insensitive" } }] } : {}),
    ...(p.get("status") ? { status: p.get("status") as SubscriberStatus } : {}),
    ...(p.get("country") ? { country: p.get("country")!.toUpperCase() } : {}),
    ...(p.get("source") ? { utmSource: p.get("source")! } : {}),
    ...(p.get("flagged") ? { referralFlagged: true } : {}),
  };
  const rows = await db.subscriber.findMany({
    where, orderBy: { createdAt: "asc" }, take: 100_000,
    include: { _count: { select: { referrals: { where: { confirmedAt: { not: null }, referralFlagged: false } } } } },
  });
  const header = ["insider_id", "email", "first_name", "country", "language", "status", "marketing_consent", "created_at", "confirmed_at", "unsubscribed_at", "utm_source", "utm_medium", "utm_campaign", "referrer", "referral_code", "confirmed_referrals"];
  const lines = rows.map((s) =>
    [s.publicId, s.email, s.firstName, s.country, s.locale, s.status, s.marketingConsent, s.createdAt, s.confirmedAt, s.unsubscribedAt, s.utmSource, s.utmMedium, s.utmCampaign, s.referrerHost, s.referralCode, s._count.referrals].map(cell).join(","),
  );
  await audit(admin, "prospects.exported", "Subscriber", null, { rows: rows.length });
  return new Response(`﻿${header.join(",")}\r\n${lines.join("\r\n")}\r\n`, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="mili-prospects-${new Date().toISOString().slice(0, 10)}.csv"`,
      "Cache-Control": "private, no-store",
    },
  });
}
