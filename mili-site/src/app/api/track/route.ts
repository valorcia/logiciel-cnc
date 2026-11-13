import { NextResponse, type NextRequest } from "next/server";
import { recordVisit } from "@/lib/analytics";
import { ipHash } from "@/lib/crypto";
import { rateLimit } from "@/lib/rate-limit";
import { parseUtm } from "@/lib/validation";

/** Anonymous page-view beacon (no cookie, no stored IP). Always answers 204. */
export async function POST(request: NextRequest) {
  const done = () => new NextResponse(null, { status: 204 });
  try {
    const body = (await request.json()) as Record<string, unknown>;
    const str = (key: string) => (typeof body[key] === "string" ? (body[key] as string) : null);
    const ip = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "0.0.0.0";
    const limit = await rateLimit(`track:${ipHash(ip)}`, 120, 60);
    if (!limit.allowed) return done();
    const path = str("path");
    if (!path || !path.startsWith("/") || path.startsWith("/admin")) return done();
    const country = request.headers.get("x-vercel-ip-country");
    await recordVisit({
      ip,
      userAgent: request.headers.get("user-agent") ?? "",
      path,
      locale: str("locale")?.slice(0, 5),
      referrer: str("referrer"),
      country: country && /^[A-Z]{2}$/.test(country) ? country : null,
      utm: parseUtm(str),
      selfHost: request.nextUrl.hostname,
    });
  } catch {
    // Measurement must never surface an error to the visitor.
  }
  return done();
}
