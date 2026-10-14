import { describe, expect, it } from "vitest";
import {
  cronAuthorized,
  effectiveRetention,
  healthVerdict,
  localParts,
  parseRetentionInput,
  retentionCutoffs,
} from "@/lib/retention";

describe("retention settings", () => {
  it("defaults to 30 days of screenshots and 90 of metrics", () => {
    expect(effectiveRetention(null)).toEqual({ screenshotDays: 30, metricsDays: 90 });
    expect(effectiveRetention({ screenshotDays: "x", metricsDays: -1 })).toEqual({ screenshotDays: 30, metricsDays: 90 });
  });
  it("never lets screenshots outlive metrics", () => {
    expect(effectiveRetention({ screenshotDays: 120, metricsDays: 60 })).toEqual({ screenshotDays: 60, metricsDays: 60 });
  });
  it("validates the form: whole days, in range, screenshots not longer than metrics", () => {
    expect(parseRetentionInput("14", "60")).toEqual({ ok: true, value: { screenshotDays: 14, metricsDays: 60 } });
    expect(parseRetentionInput("0", "60").ok).toBe(false);
    expect(parseRetentionInput("1.5", "60").ok).toBe(false);
    expect(parseRetentionInput("abc", "60").ok).toBe(false);
    expect(parseRetentionInput("10", "99999").ok).toBe(false);
    const bad = parseRetentionInput("90", "30");
    expect(!bad.ok && bad.error).toContain("longer than metrics");
  });
  it("computes the cutoffs from now", () => {
    const c = retentionCutoffs(new Date("2026-10-31T12:00:00Z"), { screenshotDays: 30, metricsDays: 90 });
    expect(c.screenshotCutoff.toISOString()).toBe("2026-10-01T12:00:00.000Z");
    expect(c.metricsCutoff.toISOString()).toBe("2026-08-02T12:00:00.000Z");
  });
});

describe("localParts", () => {
  it("gives the wall clock of the country, including a date that differs from UTC", () => {
    expect(localParts(new Date("2026-10-11T04:30:00Z"), "Europe/Rome")).toEqual({ date: "2026-10-11", minutes: 6 * 60 + 30 }); // CEST, UTC+2
    expect(localParts(new Date("2026-10-11T23:30:00Z"), "Europe/Rome")).toEqual({ date: "2026-10-12", minutes: 1 * 60 + 30 });
    expect(localParts(new Date("2026-10-11T03:00:00Z"), "America/New_York")).toEqual({ date: "2026-10-10", minutes: 23 * 60 });
  });
});

describe("healthVerdict (Europe/Rome, run at 06:00 local = 04:00 UTC in October)", () => {
  const base = { timeZone: "Europe/Rome", runHour: "06:00" };
  const at = (iso: string) => new Date(iso);

  it("is quiet before the scheduled time and during the grace period", () => {
    expect(healthVerdict({ ...base, now: at("2026-10-11T03:00:00Z"), lastScheduledStart: null, lastHeartbeat: at("2026-10-11T02:59:00Z") }).noRunToday).toBe(false);
    expect(healthVerdict({ ...base, now: at("2026-10-11T06:30:00Z"), lastScheduledStart: null, lastHeartbeat: at("2026-10-11T06:29:00Z") }).noRunToday).toBe(false); // 08:30 local: 2.5 h after
  });

  it("raises no-run-today three hours after the scheduled time when nothing ran today", () => {
    const v = healthVerdict({ ...base, now: at("2026-10-11T07:30:00Z"), lastScheduledStart: at("2026-10-10T04:00:00Z"), lastHeartbeat: at("2026-10-11T07:29:00Z") }); // 09:30 local
    expect(v).toEqual({ noRunToday: true, agentOffline: false, localDate: "2026-10-11" });
  });

  it("is satisfied by a scheduled run that started today in the country's day, even a failed one", () => {
    const v = healthVerdict({ ...base, now: at("2026-10-11T09:00:00Z"), lastScheduledStart: at("2026-10-11T04:05:00Z"), lastHeartbeat: at("2026-10-11T08:59:00Z") });
    expect(v.noRunToday).toBe(false);
  });

  it("raises agent-offline only inside the window and after two silent hours", () => {
    const silent = at("2026-10-11T01:00:00Z");
    expect(healthVerdict({ ...base, now: at("2026-10-11T05:00:00Z"), lastScheduledStart: null, lastHeartbeat: silent }).agentOffline).toBe(true);   // 07:00 local, silent 4 h
    expect(healthVerdict({ ...base, now: at("2026-10-11T02:00:00Z"), lastScheduledStart: null, lastHeartbeat: silent }).agentOffline).toBe(false);  // 04:00 local: not in the window yet
    expect(healthVerdict({ ...base, now: at("2026-10-11T05:00:00Z"), lastScheduledStart: null, lastHeartbeat: at("2026-10-11T04:30:00Z") }).agentOffline).toBe(false); // heard 30 min ago
    expect(healthVerdict({ ...base, now: at("2026-10-11T05:00:00Z"), lastScheduledStart: null, lastHeartbeat: null }).agentOffline).toBe(true);       // never heard
    expect(healthVerdict({ ...base, now: at("2026-10-11T08:00:00Z"), lastScheduledStart: null, lastHeartbeat: silent }).agentOffline).toBe(false);  // after the window it is "no run today", not offline
  });

  it("does not report an offline agent once the run has happened", () => {
    expect(healthVerdict({ ...base, now: at("2026-10-11T05:00:00Z"), lastScheduledStart: at("2026-10-11T04:00:00Z"), lastHeartbeat: at("2026-10-11T01:00:00Z") }).agentOffline).toBe(false);
  });

  it("copes with a malformed run hour by assuming 06:00", () => {
    const v = healthVerdict({ timeZone: "Europe/Rome", runHour: "soon", now: at("2026-10-11T08:00:00Z"), lastScheduledStart: null, lastHeartbeat: at("2026-10-11T07:59:00Z") });
    expect(v.noRunToday).toBe(true);
  });
});

describe("cronAuthorized", () => {
  it("accepts only the exact Bearer secret and rejects everything when no secret is configured", () => {
    expect(cronAuthorized("Bearer s3cret", "s3cret")).toBe(true);
    expect(cronAuthorized("Bearer s3cres", "s3cret")).toBe(false);
    expect(cronAuthorized("Bearer s3cret-longer", "s3cret")).toBe(false);
    expect(cronAuthorized("s3cret", "s3cret")).toBe(false);
    expect(cronAuthorized(null, "s3cret")).toBe(false);
    expect(cronAuthorized("Bearer ", "")).toBe(false);
    expect(cronAuthorized("Bearer x", undefined)).toBe(false);
  });
});
