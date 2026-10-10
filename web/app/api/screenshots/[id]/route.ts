import { get } from "@vercel/blob";
import { auth } from "@/auth";
import { prisma } from "@/lib/db";

export const dynamic = "force-dynamic";

/**
 * Serves a private screenshot to a signed-in user (docs/02 §5: screenshots are never public).
 * The Blob URL is never exposed to the browser; this route streams the bytes and allows only a
 * short private cache.
 */
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user) return new Response("unauthorized", { status: 401 });

  const { id } = await ctx.params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) return new Response("not found", { status: 404 });
  const shot = await prisma.screenshot.findUnique({ where: { id }, select: { blobUrl: true } });
  if (!shot) return new Response("not found", { status: 404 });

  const blob = await get(shot.blobUrl, { access: "private" });
  if (!blob || blob.statusCode !== 200) return new Response("not found", { status: 404 });
  return new Response(blob.stream, {
    headers: { "Content-Type": blob.blob.contentType || "image/png", "Cache-Control": "private, max-age=300" },
  });
}
