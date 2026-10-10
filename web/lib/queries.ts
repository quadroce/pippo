import { prisma } from "@/lib/db";

export async function getActiveCountry(): Promise<string | null> {
  const s = await prisma.setting.findUnique({ where: { key: "activeCountry" } });
  return typeof s?.value === "string" ? s.value : null;
}

/** Most recent completed run of a country, with per-status channel counts. */
export async function latestCompletedRun(countryCode: string) {
  return prisma.run.findFirst({
    where: { countryCode, status: "completed" },
    orderBy: { startedAt: "desc" },
  });
}

export async function statusCountsForRun(runId: string) {
  const groups = await prisma.channelResult.groupBy({
    by: ["status"],
    where: { runId },
    _count: { _all: true },
  });
  const counts = { ok: 0, warning: 0, critical: 0, error: 0 };
  for (const g of groups) counts[g.status] = g._count._all;
  return counts;
}

export type ImagesSummary = {
  pages: Record<string, { url: string; metrics: Record<string, unknown>; loadError?: string | null }>;
  checks: { checkId: string; severity: string; passed: boolean; value?: number | null; threshold?: number | null; detail?: string | null; scope?: string }[];
} | null;

export function asImagesSummary(value: unknown): ImagesSummary {
  if (value && typeof value === "object" && "pages" in value && "checks" in value) return value as ImagesSummary;
  return null;
}
