import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { checkAgentAuth } from "@/lib/agent-route";
import { JOB_TTL_HOURS } from "@/lib/jobs";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

const POLL_MS = 1000;
const LONG_POLL_MS = 20_000; // stays under the function limit; the agent simply asks again

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Pending jobs for the agent, oldest first. Long-polls: waits up to ~20 s for one to appear. */
export async function GET(req: Request) {
  const denied = checkAgentAuth(req);
  if (denied) return denied;

  const wait = new URL(req.url).searchParams.get("wait") !== "0";
  const deadline = Date.now() + (wait ? LONG_POLL_MS : 0);

  for (;;) {
    await prisma.job.updateMany({
      where: { status: "pending", createdAt: { lt: new Date(Date.now() - JOB_TTL_HOURS * 3_600_000) } },
      data: { status: "expired" },
    });
    // A job acknowledged by an agent that then died before creating its run would stay "running" forever.
    await prisma.job.updateMany({
      where: { status: "running", run: { is: null }, createdAt: { lt: new Date(Date.now() - 2 * JOB_TTL_HOURS * 3_600_000) } },
      data: { status: "expired" },
    });
    const job = await prisma.job.findFirst({ where: { status: "pending" }, orderBy: { createdAt: "asc" } });
    if (job) {
      const options = (job.options ?? {}) as { windowSec?: number; includeImages?: boolean };
      return NextResponse.json({
        jobs: [
          {
            id: job.id,
            countryCode: job.countryCode,
            channelIds: Array.isArray(job.channelIds) ? job.channelIds : [],
            windowSec: options.windowSec ?? 60,
            includeImages: options.includeImages ?? true,
          },
        ],
      });
    }
    if (Date.now() >= deadline) return NextResponse.json({ jobs: [] });
    await sleep(POLL_MS);
  }
}
