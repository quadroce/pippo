/**
 * Retention rules (docs/01-PRD.md §7: screenshots kept 30 days, metrics 90 days, configurable) and the
 * scheduled-run health rules behind the "no run today" and "agent offline" notices
 * (docs/04-WEB-APP-SPEC.md §4.3). Pure functions, unit-tested; the database side is in retention-data.ts.
 */

export const DEFAULT_SCREENSHOT_DAYS = 30;
export const DEFAULT_METRICS_DAYS = 90;
export const MAX_RETENTION_DAYS = 3650;

const DAY_MS = 86_400_000;

export type Retention = { screenshotDays: number; metricsDays: number };

export function parseRetentionInput(screenshotRaw: string, metricsRaw: string): { ok: true; value: Retention } | { ok: false; error: string } {
  const toDays = (raw: string) => {
    const s = raw.trim();
    return /^\d+$/.test(s) ? Number(s) : NaN;
  };
  const screenshotDays = toDays(screenshotRaw);
  const metricsDays = toDays(metricsRaw);
  if (![screenshotDays, metricsDays].every((n) => Number.isInteger(n) && n >= 1 && n <= MAX_RETENTION_DAYS)) {
    return { ok: false, error: `Enter whole numbers of days between 1 and ${MAX_RETENTION_DAYS}` };
  }
  if (screenshotDays > metricsDays) {
    return { ok: false, error: "Screenshots cannot be kept longer than metrics: they belong to the results that metrics retention deletes" };
  }
  return { ok: true, value: { screenshotDays, metricsDays } };
}

/** Stored values with defaults; screenshots never outlive metrics. */
export function effectiveRetention(stored: { screenshotDays?: unknown; metricsDays?: unknown } | null | undefined): Retention {
  const num = (v: unknown, d: number) => (typeof v === "number" && Number.isInteger(v) && v >= 1 && v <= MAX_RETENTION_DAYS ? v : d);
  const metricsDays = num(stored?.metricsDays, DEFAULT_METRICS_DAYS);
  return { screenshotDays: Math.min(num(stored?.screenshotDays, DEFAULT_SCREENSHOT_DAYS), metricsDays), metricsDays };
}

export function retentionCutoffs(now: Date, r: Retention): { screenshotCutoff: Date; metricsCutoff: Date } {
  return {
    screenshotCutoff: new Date(now.getTime() - r.screenshotDays * DAY_MS),
    metricsCutoff: new Date(now.getTime() - r.metricsDays * DAY_MS),
  };
}

// --- scheduled-run health -----------------------------------------------------------------------

/** Wall-clock date ("YYYY-MM-DD") and minutes since midnight of an instant in an IANA timezone. */
export function localParts(at: Date, timeZone: string): { date: string; minutes: number } {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(at);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "00";
  return { date: `${get("year")}-${get("month")}-${get("day")}`, minutes: Number(get("hour")) * 60 + Number(get("minute")) };
}

export const GRACE_HOURS_NO_RUN = 3;          // how long after the scheduled time a run may still be on its way
export const AGENT_OFFLINE_HOURS = 2;          // spec: agent offline for more than 2 hours during a scheduled window

export type HealthInput = {
  now: Date;
  timeZone: string;
  runHour: string; // "HH:MM" local
  lastScheduledStart: Date | null; // start of the most recent scheduled run of the active country, of any status
  lastHeartbeat: Date | null;
};

export type HealthVerdict = { noRunToday: boolean; agentOffline: boolean; localDate: string };

/**
 * Notices due right now. Nothing is due before the scheduled time of the day; "no run today" needs
 * a grace period; "agent offline" applies during the window from the scheduled time until the grace
 * period ends, so a PC that is simply off at night does not raise it.
 */
export function healthVerdict(i: HealthInput): HealthVerdict {
  const local = localParts(i.now, i.timeZone);
  const [h, m] = i.runHour.split(":").map(Number);
  const due = (Number.isFinite(h) ? h : 6) * 60 + (Number.isFinite(m) ? m : 0);
  const sinceDue = local.minutes - due;

  const ranToday = !!i.lastScheduledStart && localParts(i.lastScheduledStart, i.timeZone).date === local.date;
  const noRunToday = sinceDue >= GRACE_HOURS_NO_RUN * 60 && !ranToday;

  const inWindow = sinceDue >= 0 && sinceDue <= GRACE_HOURS_NO_RUN * 60;
  const silentFor = i.lastHeartbeat ? (i.now.getTime() - i.lastHeartbeat.getTime()) / 3_600_000 : Infinity;
  const agentOffline = inWindow && !ranToday && silentFor > AGENT_OFFLINE_HOURS;
  return { noRunToday, agentOffline, localDate: local.date };
}

export function cronAuthorized(authorization: string | null, secret: string | undefined): boolean {
  if (!secret) return false;
  const token = authorization?.startsWith("Bearer ") ? authorization.slice(7) : "";
  if (token.length !== secret.length) return false;
  let diff = 0;
  for (let k = 0; k < token.length; k++) diff |= token.charCodeAt(k) ^ secret.charCodeAt(k);
  return diff === 0;
}
