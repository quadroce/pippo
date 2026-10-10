import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { checkAgentAuth, parseJson } from "@/lib/agent-route";
import { loadWritableRun } from "@/lib/agent-run";
import { countStatuses, type ResultStatus } from "@/lib/results";
import { finalizeAlerts } from "@/lib/alerts-data";
import { sendDailyReport } from "@/lib/report-data";
import { finishRunRequest } from "@/lib/schemas/agent";

export const dynamic = "force-dynamic";

/** Closes a run. A completed scheduled run triggers the daily report email; alerts follow in step 2.5. */
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

  if (run.status === "completed") {
    try {
      await finalizeAlerts(run.id);
    } catch (e) {
      console.error("finalizing alerts failed", e);
    }
  }

  // An on-demand run closes its job (the run status tells whether it succeeded).
  if (run.jobId) await prisma.job.update({ where: { id: run.jobId }, data: { status: "done" } });

  // The report must never make the agent's finish call fail: errors are recorded in the run log.
  let reportSentTo = 0;
  if (run.trigger === "scheduled" && run.status === "completed") {
    try {
      reportSentTo = await sendDailyReport(run.id);
    } catch (e) {
      console.error("daily report failed", e);
      const prev = Array.isArray(run.log) ? (run.log as object[]) : [];
      await prisma.run.update({
        where: { id: run.id },
        data: { log: [...prev, { level: "error", msg: `daily report email failed: ${String(e).slice(0, 300)}` }] },
      });
    }
  }
  return NextResponse.json({ id: run.id, status: run.status, counts, reportSentTo });
}
