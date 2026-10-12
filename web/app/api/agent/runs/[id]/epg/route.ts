import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { checkAgentAuth, parseJson } from "@/lib/agent-route";
import { loadWritableRun } from "@/lib/agent-run";
import { channelCountDropCheck } from "@/lib/epg";
import { getGlobalThresholds } from "@/lib/settings";
import { epgResultRequest } from "@/lib/schemas/agent";

export const dynamic = "force-dynamic";

/**
 * Stores the run-level EPG result. Adds `epg.channel_count_drop`, which needs the previous run
 * and is therefore evaluated here. Uploading again replaces the result.
 */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const denied = checkAgentAuth(req);
  if (denied) return denied;
  const { id } = await ctx.params;
  const loaded = await loadWritableRun(id);
  if ("error" in loaded) return loaded.error;
  const { run } = loaded;
  const body = await parseJson(req, epgResultRequest);
  if ("error" in body) return body.error;
  const epg = body.data;

  const previous = await prisma.epgResult.findFirst({
    where: { run: { countryCode: run.countryCode, status: "completed", startedAt: { lt: run.startedAt } } },
    orderBy: { run: { startedAt: "desc" } },
    select: { metrics: true },
  });
  const thresholds = await getGlobalThresholds();
  const drop = channelCountDropCheck(
    previous ? numberOf(previous.metrics, "epg.channel_count") : null,
    numberOf(epg.metrics, "epg.channel_count"),
    thresholds["epg.channel_count_drop"]?.critical ?? 0.1,
  );
  const checks = drop ? [...epg.checks, drop] : epg.checks;

  await prisma.epgResult.upsert({
    where: { runId: run.id },
    update: { metrics: epg.metrics as object, issues: epg.issues as object, checks: checks as object, screenshotUrl: epg.screenshotUrl ?? null },
    create: { runId: run.id, metrics: epg.metrics as object, issues: epg.issues as object, checks: checks as object, screenshotUrl: epg.screenshotUrl ?? null },
  });
  return NextResponse.json({ ok: true, checks: checks.length }, { status: 201 });
}

function numberOf(metrics: unknown, key: string): number | null {
  if (!metrics || typeof metrics !== "object") return null;
  const v = (metrics as Record<string, unknown>)[key];
  return typeof v === "number" ? v : null;
}
