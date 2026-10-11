import type { CheckInput } from "@/lib/schemas/agent";

/**
 * `epg.channel_count_drop`: channels in the guide versus the previous completed run of the same
 * country. Needs at least 10 channels before to be meaningful (a handful of channels moving is
 * normal churn, not an outage). Returns null when there is nothing to compare.
 */
export function channelCountDropCheck(previous: number | null, current: number | null, criticalShare: number): CheckInput | null {
  if (previous === null || current === null || previous < 10) return null;
  const drop = Math.max(0, (previous - current) / previous);
  const failed = drop > criticalShare;
  return {
    checkId: "epg.channel_count_drop",
    severity: failed ? "critical" : "info",
    passed: !failed,
    value: Math.round(drop * 10_000) / 10_000,
    threshold: criticalShare,
    detail: `${current} channels now, ${previous} in the previous run`,
    scope: "epg",
  };
}
