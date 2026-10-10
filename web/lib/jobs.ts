/** On-demand jobs (docs/04-WEB-APP-SPEC.md §3.7). Pure helpers, unit-tested. */

export const JOB_TTL_HOURS = 6;
export const WINDOWS = [30, 60, 120] as const;
export const MAX_CHANNELS_PER_JOB = 200;

export type JobOptions = { windowSec: number; includeImages: boolean; total: number };

export type JobInput = {
  country: string;
  mode: string; // "all" | "selected"
  channelIds: string[];
  windowSec: number;
  includeImages: boolean;
};

export type ParsedJob =
  | { ok: true; countryCode: string; channelIds: string[]; options: Omit<JobOptions, "total"> }
  | { ok: false; error: string };

/** Validates the form. `knownIds` are the channel ids that exist for the chosen country. */
export function parseJobInput(input: JobInput, knownIds: Set<string>): ParsedJob {
  const countryCode = input.country.trim().toUpperCase();
  if (!/^[A-Z]{2}$/.test(countryCode)) return { ok: false, error: "Pick a country" };
  if (!(WINDOWS as readonly number[]).includes(input.windowSec)) return { ok: false, error: "Pick an observation window" };

  const options = { windowSec: input.windowSec, includeImages: input.includeImages };
  if (input.mode === "all") return { ok: true, countryCode, channelIds: [], options };
  if (input.mode !== "selected") return { ok: false, error: "Pick entire country or selected channels" };

  const ids = [...new Set(input.channelIds)];
  if (ids.length === 0) return { ok: false, error: "Select at least one channel" };
  if (ids.length > MAX_CHANNELS_PER_JOB) return { ok: false, error: `Select at most ${MAX_CHANNELS_PER_JOB} channels` };
  const unknown = ids.filter((id) => !knownIds.has(id));
  if (unknown.length) return { ok: false, error: "Some selected channels do not belong to this country" };
  return { ok: true, countryCode, channelIds: ids, options };
}

export const isExpired = (createdAt: Date, now: Date = new Date()) => now.getTime() - createdAt.getTime() > JOB_TTL_HOURS * 3_600_000;

export type JobView = { status: string; runStatus: string | null; done: number; total: number | null };

/** Human description of a job's progress: queued, picked up, N of M channels, finished. */
export function describeJob(v: JobView, agentOnline: boolean): string {
  if (v.status === "expired") return "Expired: the agent did not pick it up within 6 hours";
  if (v.status === "pending") {
    return agentOnline ? "Queued: waiting for the agent to pick it up" : "Queued: the agent is offline, the job starts when it is back (expires after 6 hours)";
  }
  if (v.status === "running") {
    if (v.total) return `Running: ${v.done} of ${v.total} channels measured`;
    return v.done > 0 ? `Running: ${v.done} channels measured` : "Picked up by the agent: preparing the measurement";
  }
  if (v.runStatus === "blocked") return "Finished: blocked by the country pre-check";
  if (v.runStatus === "failed") return "Finished: the run failed";
  return v.total ? `Finished: ${v.done} of ${v.total} channels measured` : `Finished: ${v.done} channels measured`;
}
