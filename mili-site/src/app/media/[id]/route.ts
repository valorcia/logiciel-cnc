import { currentAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";
import { can } from "@/lib/permissions";
import { getSettings } from "@/lib/settings";
import { storage } from "@/lib/storage";

/**
 * Every image goes through this handler: files live in private storage, never
 * in /public. An asset marked REVEAL_ONLY answers 404 — exactly like an asset
 * that does not exist — until the site is in Reveal mode. Signed-in
 * administrators allowed to preview can see it earlier, uncached.
 */
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[a-z0-9]{10,40}$/.test(id)) return new Response("Not found", { status: 404 });
  const asset = await db.mediaAsset.findUnique({ where: { id } });
  if (!asset) return new Response("Not found", { status: 404 });

  let cache = "public, max-age=3600, stale-while-revalidate=86400";
  if (asset.visibility === "REVEAL_ONLY") {
    const settings = await getSettings();
    if (settings.mode === "REVEAL") {
      cache = "public, max-age=60";
    } else {
      const admin = await currentAdmin();
      if (!admin || !can(admin.role, "product.edit")) return new Response("Not found", { status: 404 });
      cache = "private, no-store";
    }
  }

  const bytes = await storage().get(asset.storageKey);
  if (!bytes) return new Response("Not found", { status: 404 });
  return new Response(bytes as BodyInit, {
    headers: {
      "Content-Type": asset.mime,
      "Content-Length": String(bytes.length),
      "Cache-Control": cache,
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "default-src 'none'; sandbox",
      ...(asset.visibility === "REVEAL_ONLY" ? { "X-Robots-Tag": "noindex" } : {}),
    },
  });
}
