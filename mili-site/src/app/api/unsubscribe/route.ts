import { rateLimit } from "@/lib/rate-limit";
import { requestMeta } from "@/lib/request";
import { subscriberFromToken, unsubscribe } from "@/lib/subscribers";

/**
 * RFC 8058 one-click unsubscribe, called by mailbox providers when the
 * recipient uses their "Unsubscribe" button. POST only: a link scanner that
 * merely fetches the URL cannot unsubscribe anybody.
 */
export async function POST(req: Request) {
  const meta = await requestMeta();
  const limit = await rateLimit(`unsub:${meta.ipHash}`, 30, 3600);
  if (!limit.allowed) return new Response("Too many requests", { status: 429 });
  const token = new URL(req.url).searchParams.get("t") ?? "";
  const sub = await subscriberFromToken(token);
  // Same answer whether or not the token is valid: nothing to probe.
  if (sub) await unsubscribe(sub, "one_click_header", { ipHash: meta.ipHash, userAgent: meta.userAgent });
  return new Response(null, { status: 200 });
}

export function GET(req: Request) {
  const url = new URL(req.url);
  return Response.redirect(new URL(`/unsubscribe?t=${encodeURIComponent(url.searchParams.get("t") ?? "")}`, url.origin), 303);
}
