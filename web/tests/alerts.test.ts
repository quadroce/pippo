import { describe, expect, it } from "vitest";
import { countryWideChecks, countryWideEmail, decideEmail, digestEmail, formatValue, individualAlertEmail } from "@/lib/alerts";

const now = new Date("2026-10-11T10:00:00Z");
const hoursAgo = (h: number) => new Date(now.getTime() - h * 3_600_000);

describe("decideEmail", () => {
  it("sends the first findings of a check, holds the rest, and never repeats within 24 h", () => {
    expect(decideEmail({ lastEmailedAt: null, now, sentThisRunForCheck: 0 })).toBe("send");
    expect(decideEmail({ lastEmailedAt: null, now, sentThisRunForCheck: 2 })).toBe("send");
    expect(decideEmail({ lastEmailedAt: null, now, sentThisRunForCheck: 3 })).toBe("hold");
    expect(decideEmail({ lastEmailedAt: hoursAgo(23), now, sentThisRunForCheck: 0 })).toBe("dedupe");
    expect(decideEmail({ lastEmailedAt: hoursAgo(25), now, sentThisRunForCheck: 0 })).toBe("send");
  });
  it("deduplication wins over the per-run cap", () => {
    expect(decideEmail({ lastEmailedAt: hoursAgo(1), now, sentThisRunForCheck: 10 })).toBe("dedupe");
  });
});

describe("countryWideChecks", () => {
  const failing = (n: number) => Array.from({ length: n }, (_, i) => `c${i}`);
  it("flags a check failing on more than 30% of at least 10 channels", () => {
    expect(countryWideChecks(new Map([["player.ttff", failing(31)]]), 100)).toEqual(["player.ttff"]);
    expect(countryWideChecks(new Map([["player.ttff", failing(30)]]), 100)).toEqual([]);   // exactly 30% is not more than 30%
  });
  it("ignores tiny runs and isolated failures", () => {
    expect(countryWideChecks(new Map([["player.ttff", failing(1)]]), 1)).toEqual([]);      // single-channel test
    expect(countryWideChecks(new Map([["player.ttff", failing(2)]]), 5)).toEqual([]);
    expect(countryWideChecks(new Map([["player.ttff", failing(4)]]), 10)).toEqual(["player.ttff"]);
  });
});

describe("emails", () => {
  it("formats values with the unit of the check", () => {
    expect(formatValue("player.stall_ratio", 0.154)).toBe("15.4%");
    expect(formatValue("player.ttff", 12614.4)).toBe("12614 ms");
    expect(formatValue("player.black_screen", 10)).toBe("10 s");
    expect(formatValue("player.media_error", 2)).toBe("2");
    expect(formatValue("x.unknown", null)).toBe("n/a");
  });

  it("individual alert follows the spec subject and includes evidence and acknowledge links", () => {
    const m = individualAlertEmail({
      country: "IT",
      finding: { checkId: "player.start_failed", channelName: "Rai News", value: 1, threshold: 0, detail: "no source" },
      runAt: new Date("2026-10-11T04:00:00Z"),
      channelUrl: "https://p.example/channels/it-rai-news",
      alertsUrl: "https://p.example/alerts",
    });
    expect(m.subject).toBe("[Pippo] IT — CRITICAL: Rai News — Playback did not start");
    for (const body of [m.text, m.html]) {
      expect(body).toContain("https://p.example/channels/it-rai-news");
      expect(body).toContain("https://p.example/alerts");
    }
    expect(m.text).toContain("no source");
  });

  it("country-wide email lists affected channels and escapes HTML", () => {
    const m = countryWideEmail({ country: "IT", checkId: "player.ttff", channels: ["<b>X</b>", "Y", "Z"], total: 10, runUrl: "https://p/r" });
    expect(m.subject).toBe("[Pippo] IT — CRITICAL: 3 of 10 channels — Time to first frame");
    expect(m.text).toContain("30%");
    expect(m.html).not.toContain("<b>X</b>");
  });

  it("digest truncates long lists", () => {
    const findings = Array.from({ length: 50 }, (_, i) => ({ checkId: "player.ttff", channelName: `C${i}`, value: 12000, threshold: 10000 }));
    const m = digestEmail({ country: "IT", findings, runUrl: "https://p/r", alertsUrl: "https://p/a" });
    expect(m.subject).toContain("50 more critical");
    expect(m.text).toContain("and 10 more");
  });
});
