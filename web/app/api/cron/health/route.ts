import { NextResponse } from "next/server";
import { requireCron } from "@/lib/cron";
import { prisma } from "@/lib/db";
import { sendAgentOfflineNotice, sendNoRunNotice } from "@/lib/notices";
import { healthVerdict } from "@/lib/retention";

export const dynamic = "force-dynamic";

const KEY_NO_RUN = "notice.noRun";
const KEY_OFFLINE = "notice.agentOffline";

async function alreadyNotified(key: string, country: string, date: string) {
  const s = await prisma.setting.findUnique({ where: { key } });
  return !!s && typeof s.value === "object" && s.value !== null && (s.value as Record<string, unknown>)[country] === date;
}

async function markNotified(key: string, country: string, date: string) {
  const s = await prisma.setting.findUnique({ where: { key } });
  const value = { ...(s && typeof s.value === "object" && s.value !== null ? (s.value as Record<string, string>) : {}), [country]: date };
  await prisma.setting.upsert({ where: { key }, update: { value }, create: { key, value } });
}

/**
 * Checks whether today's scheduled run happened and whether the agent is alive, and sends the two operational
 * notices at most once per country and local day. Vercel Hobby allows daily crons only, so this runs once a day
 * (see vercel.json); on a plan with hourly crons run it hourly for earlier notices.
 */
export async function GET(req: Request) {
  const denied = requireCron(req);
  if (denied) return denied;

  const active = await prisma.setting.findUnique({ where: { key: "activeCountry" } });
  const code = typeof active?.value === "string" ? active.value : null;
  const country = code ? await prisma.country.findUnique({ where: { code } }) : null;
  if (!country) return NextResponse.json({ checked: false, reason: "no active country" });

  const [lastRun, agent] = await Promise.all([
    prisma.run.findFirst({ where: { countryCode: country.code, trigger: "scheduled" }, orderBy: { startedAt: "desc" }, select: { startedAt: true } }),
    prisma.agent.findUnique({ where: { id: "default" } }),
  ]);
  const verdict = healthVerdict({
    now: new Date(),
    timeZone: country.timezone,
    runHour: country.runHour,
    lastScheduledStart: lastRun?.startedAt ?? null,
    lastHeartbeat: agent?.lastHeartbeatAt ?? null,
  });

  const sent = { noRun: false, offline: false };
  if (verdict.noRunToday && !(await alreadyNotified(KEY_NO_RUN, country.code, verdict.localDate))) {
    sent.noRun = await sendNoRunNotice({ country: country.code, localDate: verdict.localDate, runHour: country.runHour });
    if (sent.noRun) await markNotified(KEY_NO_RUN, country.code, verdict.localDate);
  }
  if (verdict.agentOffline && !(await alreadyNotified(KEY_OFFLINE, country.code, verdict.localDate))) {
    sent.offline = await sendAgentOfflineNotice({ country: country.code, localDate: verdict.localDate, lastHeartbeat: agent?.lastHeartbeatAt ?? null });
    if (sent.offline) await markNotified(KEY_OFFLINE, country.code, verdict.localDate);
  }
  return NextResponse.json({ checked: true, country: country.code, ...verdict, sent });
}
