import { assertAdmin, ForbiddenError } from "@/lib/admin-session";
import { audit } from "@/lib/audit";
import { db } from "@/lib/db";
import { storage } from "@/lib/storage";

/** Moderators download a submitted file. Always served as an attachment, never rendered in the browser. */
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  let admin;
  try {
    admin = await assertAdmin("challenges.moderate");
  } catch (err) {
    if (err instanceof ForbiddenError) return new Response("Forbidden", { status: 403 });
    throw err;
  }
  const { id } = await params;
  const challenge = await db.challenge.findUnique({ where: { id }, select: { fileKey: true, fileName: true } });
  if (!challenge?.fileKey) return new Response("Not found", { status: 404 });
  const bytes = await storage().get(challenge.fileKey);
  if (!bytes) return new Response("Not found", { status: 404 });
  await audit(admin, "challenge.file_downloaded", "Challenge", id);
  const name = (challenge.fileName ?? "file").replace(/[^\w.\- ]+/g, "_");
  return new Response(bytes as BodyInit, {
    headers: {
      "Content-Type": "application/octet-stream",
      "Content-Disposition": `attachment; filename="${name}"`,
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "default-src 'none'; sandbox",
      "Cache-Control": "private, no-store",
    },
  });
}
