import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { checkAgentAuth, parseJson } from "@/lib/agent-route";
import { getEffectiveThresholds } from "@/lib/settings";
import { heartbeatRequest, type HeartbeatResponse } from "@/lib/schemas/agent";

export const dynamic = "force-dynamic";

const DEFAULT_POLL_SEC = 10;

export async function POST(req: Request) {
  const denied = checkAgentAuth(req);
  if (denied) return denied;
  const body = await parseJson(req, heartbeatRequest);
  if ("error" in body) return body.error;
  const hb = body.data;

  await prisma.agent.upsert({
    where: { id: "default" },
    update: {
      lastHeartbeatAt: new Date(),
      detectedCountry: hb.detectedCountry ?? null,
      currentVersion: hb.agentVersion,
      info: { hostname: hb.hostname ?? null },
    },
    create: {
      id: "default",
      lastHeartbeatAt: new Date(),
      detectedCountry: hb.detectedCountry ?? null,
      currentVersion: hb.agentVersion,
      info: { hostname: hb.hostname ?? null },
    },
  });

  const [active, poll] = await Promise.all([
    prisma.setting.findUnique({ where: { key: "activeCountry" } }),
    prisma.setting.findUnique({ where: { key: "agent.pollIntervalSec" } }),
  ]);

  const activeCode = typeof active?.value === "string" ? active.value : null;
  const country = activeCode ? await prisma.country.findUnique({ where: { code: activeCode } }) : null;

  const thresholds = await getEffectiveThresholds(activeCode); // global overrides, then the active country's own
  const sample = activeCode
    ? await prisma.channel.findMany({ where: { countryCode: activeCode, subtitleSample: true }, select: { id: true }, orderBy: { id: "asc" } })
    : [];

  const res: HeartbeatResponse = {
    activeCountry: activeCode,
    schedule: country ? { countryCode: country.code, runHour: country.runHour, timezone: country.timezone } : null,
    thresholds,
    subtitleSample: sample.map((c) => c.id),
    pollIntervalSec: typeof poll?.value === "number" ? poll.value : DEFAULT_POLL_SEC,
  };
  return NextResponse.json(res);
}