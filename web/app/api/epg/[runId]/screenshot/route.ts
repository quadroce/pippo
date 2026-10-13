import { get } from "@vercel/blob";
import { auth } from "@/auth";
import { prisma } from "@/lib/db";

export const dynamic = "force-dynamic";

/** The guide screenshot of a run, streamed from private Blob storage to signed-in users only. */
export async function GET(_req: Request, ctx: { params: Promise<{ runId: string }> }) {
  const session = await auth();
  if (!session?.user) return new Response("unauthorized", { status: 401 });

  const { runId } = await ctx.params;
  if (!/^[0-9a-f-]{36}$/i.test(runId)) return new Response("not found", { status: 404 });
  const epg = await prisma.epgResult.findUnique({ where: { runId }, select: { screenshotUrl: true } });
  if (!epg?.screenshotUrl) return new Response("not found", { status: 404 });

  const blob = await get(epg.screenshotUrl, { access: "private" });
  if (!blob || blob.statusCode !== 200) return new Response("not found", { status: 404 });
  return new Response(blob.stream, {
    headers: { "Content-Type": blob.blob.contentType || "image/png", "Cache-Control": "private, max-age=300" },
  });
}
