import type { CheckInput } from "@/lib/schemas/agent";

export type ResultStatus = "ok" | "warning" | "critical" | "error";

/**
 * Channel status rule (docs/03-CHECK-CATALOG.md): critical if any critical check failed,
 * warning if any warning check failed, otherwise ok. A crashed measurement is "error".
 */
export function channelStatus(checks: CheckInput[], error?: string): ResultStatus {
  if (error) return "error";
  const failed = checks.filter((c) => !c.passed);
  if (failed.some((c) => c.severity === "critical")) return "critical";
  if (failed.some((c) => c.severity === "warning")) return "warning";
  return "ok";
}

export type StatusCounts = Record<ResultStatus, number>;

export function countStatuses(statuses: ResultStatus[]): StatusCounts {
  const counts: StatusCounts = { ok: 0, warning: 0, critical: 0, error: 0 };
  for (const s of statuses) counts[s] += 1;
  return counts;
}

/** Worst status of a set, used for country and run badges. "none" when there is no data. */
export function worstStatus(statuses: ResultStatus[]): ResultStatus | "none" {
  if (statuses.length === 0) return "none";
  for (const s of ["critical", "warning", "error"] as const) if (statuses.includes(s)) return s;
  return "ok";
}
