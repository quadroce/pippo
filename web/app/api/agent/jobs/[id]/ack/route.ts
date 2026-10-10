import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { checkAgentAuth } from "@/lib/agent-route";

export const dynamic = "force-dynamic";

/** Marks a pending job as started. Only one caller can win: a job that is no longer pending answers 409. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const denied = checkAgentAuth(req);
  if (denied) return denied;
  const { id } = await ctx.params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) return NextResponse.json({ error: "invalid job id" }, { status: 400 });

  const res = await prisma.job.updateMany({ where: { id, status: "pending" }, data: { status: "running" } });
  if (res.count === 0) {
    const exists = await prisma.job.findUnique({ where: { id }, select: { status: true } });
    if (!exists) return NextResponse.json({ error: "unknown job" }, { status: 404 });
    return NextResponse.json({ error: `job is ${exists.status}` }, { status: 409 });
  }
  return NextResponse.json({ ok: true });
}
