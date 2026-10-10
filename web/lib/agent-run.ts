import type { Run } from "@prisma/client";
import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";

/** Loads a run the agent is allowed to write to: it must exist and still be running. */
export async function loadWritableRun(id: string): Promise<{ run: Run } | { error: NextResponse }> {
  if (!/^[0-9a-f-]{36}$/i.test(id)) {
    return { error: NextResponse.json({ error: "invalid run id" }, { status: 400 }) };
  }
  const run = await prisma.run.findUnique({ where: { id } });
  if (!run) return { error: NextResponse.json({ error: "unknown run" }, { status: 404 }) };
  if (run.status !== "running") {
    return { error: NextResponse.json({ error: `run is ${run.status}` }, { status: 409 }) };
  }
  return { run };
}
