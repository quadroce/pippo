import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { checkAgentAuth, parseJson } from "@/lib/agent-route";
import { sendBlockedNotice } from "@/lib/notices";
import { createRunRequest } from "@/lib/schemas/agent";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const denied = checkAgentAuth(req);
  if (denied) return denied;
  const body = await parseJson(req, createRunRequest);
  if ("error" in body) return body.error;
  const r = body.data;

  const country = await prisma.country.findUnique({ where: { code: r.countryCode } });
  if (!country) {
    return NextResponse.json({ error: `unknown country ${r.countryCode}` }, { status: 422 });
  }

  // FR-3: never record measurements for a country the agent is not actually in.
  const blocked = r.detectedCountry !== r.countryCode;
  const run = await prisma.run.create({
    data: {
      countryCode: r.countryCode,
      trigger: r.trigger,
      status: blocked ? "blocked" : "running",
      detectedCountry: r.detectedCountry ?? null,
      agentVersion: r.agentVersion,
      jobId: r.jobId,
      finishedAt: blocked ? new Date() : null,
      log: blocked
        ? [{ level: "error", msg: `country pre-check failed: selected ${r.countryCode}, detected ${r.detectedCountry ?? "unknown"}` }]
        : undefined,
    },
  });

  if (blocked && r.jobId) await prisma.job.update({ where: { id: r.jobId }, data: { status: "done" } });
  if (blocked) await sendBlockedNotice({ runId: run.id, selected: r.countryCode, detected: r.detectedCountry ?? null });

  return NextResponse.json({ id: run.id, status: run.status }, { status: 201 });
}