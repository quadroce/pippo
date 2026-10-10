import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { checkAgentAuth, parseJson } from "@/lib/agent-route";
import { loadWritableRun } from "@/lib/agent-run";
import { countStatuses, type ResultStatus } from "@/lib/results";
import { finishRunRequest } from "@/lib/schemas/agent";

export const dynamic = "force-dynamic";

/** Closes a run. Report emails and alerts are triggered from here in later steps (1.4, 2.5). */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const denied = checkAgentAuth(req);
  if (denied) return denied;
  const { id } = await ctx.params;
  const loaded = await loadWritableRun(id);
  if ("error" in loaded) return loaded.error;
  const body = await parseJson(req, finishRunRequest);
  if ("error" in body) return body.error;

  const results = await prisma.channelResult.findMany({ where: { runId: loaded.run.id }, select: { status: true } });
  const counts = countStatuses(results.map((r) => r.status as ResultStatus));

  const run = await prisma.run.update({
    where: { id: loaded.run.id },
    data: { status: body.data.status, finishedAt: new Date(), ...(body.data.log ? { log: body.data.log } : {}) },
  });
  return NextResponse.json({ id: run.id, status: run.status, counts });
}
