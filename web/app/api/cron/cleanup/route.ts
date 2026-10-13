import { NextResponse } from "next/server";
import { requireCron } from "@/lib/cron";
import { runCleanup } from "@/lib/retention-data";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

/** Daily retention cleanup (vercel.json). Safe to call again: it works in bounded batches and resumes. */
export async function GET(req: Request) {
  const denied = requireCron(req);
  if (denied) return denied;
  return NextResponse.json(await runCleanup());
}
