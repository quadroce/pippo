import { auth } from "@/auth";
import { prisma } from "@/lib/db";
import { asIssues, issuesToCsv } from "@/lib/epg-view";

export const dynamic = "force-dynamic";

/** Issues table of a run as CSV, to hand to the EPG or scheduling team (runbook section 3). */
export async function GET(_req: Request, ctx: { params: Promise<{ runId: string }> }) {
  const session = await auth();
  if (!session?.user) return new Response("unauthorized", { status: 401 });

  const { runId } = await ctx.params;
  if (!/^[0-9a-f-]{36}$/i.test(runId)) return new Response("not found", { status: 404 });
  const run = await prisma.run.findUnique({ where: { id: runId }, select: { countryCode: true, country: { select: { timezone: true } }, epg: { select: { issues: true } } } });
  if (!run?.epg) return new Response("not found", { status: 404 });

  return new Response(issuesToCsv(asIssues(run.epg.issues), run.country.timezone), {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="epg-issues-${run.countryCode}-${runId.slice(0, 8)}.csv"`,
    },
  });
}
