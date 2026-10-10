import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { checkAgentAuth, parseJson } from "@/lib/agent-route";
import { loadWritableRun } from "@/lib/agent-run";
import { imagesResultRequest } from "@/lib/schemas/agent";

export const dynamic = "force-dynamic";

/** Stores the page-level images result (home, EPG) on the run. Uploading again replaces it. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const denied = checkAgentAuth(req);
  if (denied) return denied;
  const { id } = await ctx.params;
  const loaded = await loadWritableRun(id);
  if ("error" in loaded) return loaded.error;
  const body = await parseJson(req, imagesResultRequest);
  if ("error" in body) return body.error;

  await prisma.run.update({ where: { id: loaded.run.id }, data: { images: body.data as object } });
  return NextResponse.json({ ok: true }, { status: 201 });
}
