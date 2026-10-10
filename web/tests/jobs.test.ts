import { describe, expect, it } from "vitest";
import { describeJob, isExpired, parseJobInput } from "@/lib/jobs";

const known = new Set(["it-a", "it-b"]);
const base = { country: "it", mode: "selected", channelIds: ["it-a"], windowSec: 60, includeImages: false };

describe("parseJobInput", () => {
  it("accepts selected channels and normalizes the country", () => {
    expect(parseJobInput(base, known)).toEqual({ ok: true, countryCode: "IT", channelIds: ["it-a"], options: { windowSec: 60, includeImages: false } });
  });
  it("treats entire country as an empty channel list", () => {
    const r = parseJobInput({ ...base, mode: "all", channelIds: ["ignored"] }, known);
    expect(r).toEqual({ ok: true, countryCode: "IT", channelIds: [], options: { windowSec: 60, includeImages: false } });
  });
  it("de-duplicates channels and rejects empty, unknown, oversized and bad values", () => {
    expect(parseJobInput({ ...base, channelIds: ["it-a", "it-a", "it-b"] }, known)).toMatchObject({ ok: true, channelIds: ["it-a", "it-b"] });
    expect(parseJobInput({ ...base, channelIds: [] }, known).ok).toBe(false);
    expect(parseJobInput({ ...base, channelIds: ["fr-x"] }, known).ok).toBe(false);
    const many = new Set(Array.from({ length: 300 }, (_, i) => `it-${i}`));
    expect(parseJobInput({ ...base, channelIds: [...many] }, many).ok).toBe(false);
    expect(parseJobInput({ ...base, windowSec: 45 }, known).ok).toBe(false);
    expect(parseJobInput({ ...base, country: "ITA" }, known).ok).toBe(false);
    expect(parseJobInput({ ...base, mode: "x" }, known).ok).toBe(false);
  });
});

describe("expiry and descriptions", () => {
  it("expires after 6 hours", () => {
    const now = new Date("2026-10-11T12:00:00Z");
    expect(isExpired(new Date("2026-10-11T06:30:00Z"), now)).toBe(false);
    expect(isExpired(new Date("2026-10-11T05:59:00Z"), now)).toBe(true);
  });
  it("describes each stage and says when the agent is offline", () => {
    const v = (o: object) => ({ status: "pending", runStatus: null, done: 0, total: null, ...o });
    expect(describeJob(v({}), true)).toContain("waiting for the agent");
    expect(describeJob(v({}), false)).toContain("agent is offline");
    expect(describeJob(v({ status: "running" }), true)).toContain("Picked up");
    expect(describeJob(v({ status: "running", done: 3, total: 10 }), true)).toBe("Running: 3 of 10 channels measured");
    expect(describeJob(v({ status: "done", runStatus: "completed", done: 10, total: 10 }), true)).toBe("Finished: 10 of 10 channels measured");
    expect(describeJob(v({ status: "done", runStatus: "blocked" }), true)).toContain("blocked");
    expect(describeJob(v({ status: "expired" }), true)).toContain("Expired");
  });
});
