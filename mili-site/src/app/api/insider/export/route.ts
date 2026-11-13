import { rateLimit } from "@/lib/rate-limit";
import { requestMeta } from "@/lib/request";
import { exportSubscriber, subscriberFromToken } from "@/lib/subscribers";

/** A subscriber downloads everything held about them (GDPR access and portability). */
export async function GET(req: Request) {
  const meta = await requestMeta();
  const limit = await rateLimit(`export:${meta.ipHash}`, 10, 3600);
  if (!limit.allowed) return new Response("Too many requests", { status: 429 });
  const sub = await subscriberFromToken(new URL(req.url).searchParams.get("t") ?? "");
  if (!sub) return new Response("Not found", { status: 404 });
  const data = await exportSubscriber(sub.id);
  return new Response(JSON.stringify(data, null, 2), {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Content-Disposition": `attachment; filename="milli-data-${sub.publicId}.json"`,
      "Cache-Control": "private, no-store",
      "X-Robots-Tag": "noindex",
    },
  });
}
