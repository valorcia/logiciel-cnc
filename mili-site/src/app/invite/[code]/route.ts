import { NextResponse } from "next/server";
import { db } from "@/lib/db";
import { rateLimit } from "@/lib/rate-limit";
import { requestMeta } from "@/lib/request";

/**
 * Referral entry point: /invite/CODE. Remembers the code in a first-party,
 * httpOnly cookie for 30 days and sends the visitor to the home page with UTM
 * parameters. The point is only granted later, when the invited person
 * confirms their e-mail address.
 */
export async function GET(req: Request, { params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  const url = new URL(req.url);
  const target = new URL("/", url.origin);
  for (const key of ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"]) {
    const value = url.searchParams.get(key);
    if (value) target.searchParams.set(key, value.slice(0, 100));
  }
  if (!target.searchParams.has("utm_source")) target.searchParams.set("utm_source", "referral");
  if (!target.searchParams.has("utm_medium")) target.searchParams.set("utm_medium", "referral");
  if (!target.searchParams.has("utm_campaign")) target.searchParams.set("utm_campaign", "insider-invite");

  const res = NextResponse.redirect(target, 307);
  res.headers.set("X-Robots-Tag", "noindex");
  const normalized = code.toUpperCase();
  if (!/^[A-Z0-9]{6,12}$/.test(normalized)) return res;
  const meta = await requestMeta();
  const limit = await rateLimit(`invite:${meta.ipHash}`, 60, 3600);
  if (!limit.allowed) return res;
  const owner = await db.subscriber.findFirst({ where: { referralCode: normalized, status: "CONFIRMED" }, select: { id: true } });
  if (owner) {
    res.cookies.set("mili_ref", normalized, {
      httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", maxAge: 60 * 60 * 24 * 30, path: "/",
    });
  }
  return res;
}
