import { describe, expect, it } from "vitest";
import { CHECK_CATALOG, effectiveThresholds, parseEmails, parseThresholdInput, toDisplay } from "@/lib/thresholds";

describe("effectiveThresholds", () => {
  it("returns the catalog defaults when nothing is stored", () => {
    const t = effectiveThresholds(undefined);
    expect(Object.keys(t)).toEqual(CHECK_CATALOG.map((c) => c.id));
    expect(t["img.broken_ratio"]).toEqual({ warn: 0.01, critical: 0.05 });
  });

  it("applies stored overrides, drops unknown ids and ignores invalid numbers", () => {
    const t = effectiveThresholds({
      "img.broken_ratio": { warn: 0.02, critical: null },
      "img.lazy_load_timeout": { warn: -3, critical: "x" },
      "nope.check": { warn: 1, critical: 2 },
    });
    expect(t["img.broken_ratio"]).toEqual({ warn: 0.02, critical: null });
    expect(t["img.lazy_load_timeout"]).toEqual({ warn: null, critical: null });
    expect("nope.check" in t).toBe(false);
  });
});

describe("parseThresholdInput", () => {
  it("converts percentages to ratios and blank to disabled", () => {
    expect(parseThresholdInput("ratio", "2", "7,5")).toEqual({ ok: true, value: { warn: 0.02, critical: 0.075 } });
    expect(parseThresholdInput("seconds", "5", "")).toEqual({ ok: true, value: { warn: 5, critical: null } });
    expect(parseThresholdInput("count", "", "")).toEqual({ ok: true, value: { warn: null, critical: null } });
  });

  it("rejects negatives, text, over 100 percent and critical below warning", () => {
    expect(parseThresholdInput("seconds", "-1", "").ok).toBe(false);
    expect(parseThresholdInput("seconds", "abc", "").ok).toBe(false);
    expect(parseThresholdInput("ratio", "101", "").ok).toBe(false);
    const r = parseThresholdInput("ratio", "10", "5");
    expect(r.ok).toBe(false);
    expect(!r.ok && r.error).toContain("critical");
  });

  it("round-trips through the display format", () => {
    expect(toDisplay("ratio", 0.075)).toBe("7.5");
    expect(toDisplay("seconds", 5)).toBe("5");
    expect(toDisplay("ratio", null)).toBe("");
  });
});

describe("parseEmails", () => {
  it("splits, lowercases and de-duplicates", () => {
    expect(parseEmails("A@x.com, b@x.com;\nA@x.com  c@y.org")).toEqual({ ok: true, emails: ["a@x.com", "b@x.com", "c@y.org"] });
    expect(parseEmails("")).toEqual({ ok: true, emails: [] });
  });
  it("reports invalid addresses", () => {
    const r = parseEmails("ok@x.com, nope, also bad@");
    expect(r.ok).toBe(false);
    expect(!r.ok && r.error).toContain("nope");
  });
});

describe("lower-is-worse checks", () => {
  it("catalogs the EPG checks and flags coverage as lower-is-worse", () => {
    const cov = CHECK_CATALOG.find((c) => c.id === "epg.coverage_hours");
    expect(cov?.lowerIsWorse).toBe(true);
    expect(cov?.defaults).toEqual({ warn: 6, critical: 2 });
    expect(CHECK_CATALOG.some((c) => c.id === "epg.no_now_program")).toBe(true);
  });
  it("validates the order the other way round", () => {
    expect(parseThresholdInput("hours", "6", "2", true).ok).toBe(true);
    const bad = parseThresholdInput("hours", "2", "6", true);
    expect(bad.ok).toBe(false);
    expect(!bad.ok && bad.error).toContain("lower is worse");
    expect(parseThresholdInput("hours", "2", "6").ok).toBe(true);
  });
});

describe("layerThresholds (per-country overrides)", () => {
  it("applies defaults, then global overrides, then the country's own", async () => {
    const { layerThresholds } = await import("@/lib/thresholds");
    const global = { "img.broken_ratio": { warn: 0.02, critical: 0.08 }, "player.ttff": { warn: 5000, critical: 12000 } };
    const t = layerThresholds(global, [{ checkId: "player.ttff", warn: 8000, critical: null }]);
    expect(t["player.ttff"]).toEqual({ warn: 8000, critical: null });          // the country replaces both levels
    expect(t["img.broken_ratio"]).toEqual({ warn: 0.02, critical: 0.08 });     // untouched checks follow the global value
    expect(t["player.stall_ratio"]).toEqual({ warn: 0.03, critical: 0.15 });   // and the defaults below that
  });

  it("drops unknown checks and invalid numbers, and leaves the global map alone", async () => {
    const { layerThresholds, effectiveThresholds } = await import("@/lib/thresholds");
    const t = layerThresholds(undefined, [
      { checkId: "nope.check", warn: 1, critical: 2 },
      { checkId: "player.ttff", warn: -5, critical: Number.NaN },
    ]);
    expect("nope.check" in t).toBe(false);
    expect(t["player.ttff"]).toEqual({ warn: null, critical: null });
    expect(effectiveThresholds(undefined)["player.ttff"]).toEqual({ warn: 4000, critical: 10000 });
  });
});
