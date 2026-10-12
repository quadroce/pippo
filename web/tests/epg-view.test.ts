import { describe, expect, it } from "vitest";
import { asChecks, asIssues, findCheck, formatRange, issueTypeLabel, issuesToCsv, metricNumber } from "@/lib/epg-view";

const T = Date.UTC(2026, 9, 10, 16, 25, 0); // 2026-10-10 16:25 UTC = 18:25 in Rome (CEST)

describe("reading the stored result", () => {
  it("keeps only well-formed issues and checks and tolerates garbage", () => {
    expect(asIssues([{ channel: "A", type: "gap" }, { type: "gap" }, null, "x"])).toEqual([{ channel: "A", type: "gap" }]);
    expect(asIssues(undefined)).toEqual([]);
    expect(asChecks([{ checkId: "epg.gap", severity: "warning", passed: false }, { nope: 1 }])).toHaveLength(1);
    expect(findCheck(asChecks([{ checkId: "x", severity: "info", passed: true }]), "x")?.passed).toBe(true);
  });
  it("reads numeric metrics only", () => {
    expect(metricNumber({ a: 3, b: "3" }, "a")).toBe(3);
    expect(metricNumber({ a: 3, b: "3" }, "b")).toBeNull();
    expect(metricNumber(null, "a")).toBeNull();
  });
});

describe("formatRange", () => {
  it("shows the range in the country timezone", () => {
    expect(formatRange(T, T + 45 * 60_000, "Europe/Rome")).toBe("10 Oct, 18:25 – 19:10");
    expect(formatRange(T, T + 45 * 60_000, "UTC")).toBe("10 Oct, 16:25 – 17:10");
  });
  it("handles a single instant, no time, and an invalid timezone", () => {
    expect(formatRange(T, T, "Europe/Rome")).toBe("10 Oct, 18:25");
    expect(formatRange(null, null, "Europe/Rome")).toBe("—");
    expect(formatRange(T, T + 60_000, "Not/AZone")).toContain("16:25");
  });
});

describe("issues export", () => {
  it("labels known types and passes unknown ones through", () => {
    expect(issueTypeLabel("no_now_program")).toBe("No programme now");
    expect(issueTypeLabel("brand_new")).toBe("brand_new");
  });
  it("writes a CSV with UTC and local columns and escapes commas, quotes and new lines", () => {
    const csv = issuesToCsv([{ channel: 'Rai "News", 24', type: "gap", from: T, to: T + 120_000, detail: "120 s\nlong" }], "Europe/Rome");
    const [head, row] = csv.split("\r\n");
    expect(head).toBe("channel,type,from_utc,to_utc,local_range,detail");
    expect(row.startsWith('"Rai ""News"", 24",Schedule gap,2026-10-10T16:25:00.000Z,2026-10-10T16:27:00.000Z,')).toBe(true);
    expect(csv).toContain('"120 s\nlong"');
    expect(csv.endsWith("\r\n")).toBe(true);
  });
  it("exports just the header for an empty list", () => {
    expect(issuesToCsv([], "UTC")).toBe("channel,type,from_utc,to_utc,local_range,detail\r\n");
  });
});
