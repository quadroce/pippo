import { get } from "@vercel/blob";
import { auth } from "@/auth";
import { prisma } from "@/lib/db";

export const dynamic = "force-dynamic";

/** Downloads the gzipped raw event buffer of a channel result (signed-in users only). */
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user) return new Response("unauthorized", { status: 401 });

  const { id } = await ctx.params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) return new Response("not found", { status: 404 });
  const result = await prisma.channelResult.findUnique({ where: { id }, select: { rawBufferUrl: true, channelId: true } });
  if (!result?.rawBufferUrl) return new Response("not found", { status: 404 });

  const blob = await get(result.rawBufferUrl, { access: "private" });
  if (!blob || blob.statusCode !== 200) return new Response("not found", { status: 404 });
  return new Response(blob.stream, {
    headers: {
      "Content-Type": "application/gzip",
      "Content-Disposition": `attachment; filename="${result.channelId}-buffer.json.gz"`,
      "Cache-Control": "private, max-age=300",
    },
  });
}
