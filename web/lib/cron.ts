import { NextResponse } from "next/server";
import { cronAuthorized } from "@/lib/retention";

/** Vercel Cron calls with `Authorization: Bearer $CRON_SECRET`; everything else is refused. */
export function requireCron(req: Request): NextResponse | null {
  if (!process.env.CRON_SECRET) {
    console.error("CRON_SECRET is not configured");
    return NextResponse.json({ error: "cron not configured" }, { status: 503 });
  }
  if (!cronAuthorized(req.headers.get("authorization"), process.env.CRON_SECRET)) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  return null;
}
