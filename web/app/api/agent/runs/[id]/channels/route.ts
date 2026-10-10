import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { checkAgentAuth, parseJson } from "@/lib/agent-route";
import { loadWritableRun } from "@/lib/agent-run";
import { channelStatus } from "@/lib/results";
import { channelResultRequest } from "@/lib/schemas/agent";

export const dynamic = "force-dynamic";

/** Uploads one channel result. Creates the channel on first sight and derives the status from the checks. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const denied = checkAgentAuth(req);
  if (denied) return denied;
  const { id } = await ctx.params;
  const loaded = await loadWritableRun(id);
  if ("error" in loaded) return loaded.error;
  const { run } = loaded;
  const body = await parseJson(req, channelResultRequest);
  if ("error" in body) return body.error;
  const r = body.data;

  const channelId = `${run.countryCode.toLowerCase()}-${r.channel.slug}`;
  const status = channelStatus(r.checks, r.error);

  const result = await prisma.$transaction(async (tx) => {
    await tx.channel.upsert({
      where: { id: channelId },
      update: { name: r.channel.name, category: r.channel.category ?? null },
      create: {
        id: channelId,
        countryCode: run.countryCode,
        slug: r.channel.slug,
        name: r.channel.name,
        category: r.channel.category ?? null,
      },
    });
    return tx.channelResult.create({
      data: {
        runId: run.id,
        channelId,
        status,
        metrics: { ...r.metrics, ...(r.error ? { error: r.error } : {}) } as object,
        rawBufferUrl: r.rawBufferUrl ?? null,
        measuredAt: r.measuredAt ? new Date(r.measuredAt) : undefined,
        screenshots: {
          create: r.screenshots.map((s) => ({ blobUrl: s.blobUrl, tOffsetSec: s.tOffsetSec, kind: s.kind })),
        },
        checks: {
          create: r.checks.map((c) => ({
            checkId: c.checkId,
            severity: c.severity,
            passed: c.passed,
            value: c.value ?? null,
            threshold: c.threshold ?? null,
            detail: c.detail ?? null,
          })),
        },
      },
    });
  });

  return NextResponse.json({ id: result.id, channelId, status }, { status: 201 });
}
