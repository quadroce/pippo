import { describe, expect, it } from "vitest";
import { isOlder, parseLatestVersionInput, parseVersion } from "@/lib/agent-version";

describe("agent version", () => {
  it("parses plain and v-prefixed versions only", () => {
    expect(parseVersion("1.2.3")).toEqual([1, 2, 3]);
    expect(parseVersion(" v0.10.0 ")).toEqual([0, 10, 0]);
    expect(parseVersion("1.2")).toBeNull();
    expect(parseVersion("1.2.3-beta")).toBeNull();
  });

  it("compares numerically, not as text", () => {
    expect(isOlder("0.9.0", "0.10.0")).toBe(true);
    expect(isOlder("0.1.0", "0.2.0")).toBe(true);
    expect(isOlder("0.2.0", "0.2.0")).toBe(false);
    expect(isOlder("1.0.0", "0.9.9")).toBe(false);
    expect(isOlder("0.1.0", null)).toBe(false);
    expect(isOlder(undefined, "0.2.0")).toBe(false);
    expect(isOlder("garbage", "0.2.0")).toBe(false);
  });

  it("validates the Settings field: empty clears it, otherwise a version", () => {
    expect(parseLatestVersionInput("")).toEqual({ ok: true, value: null });
    expect(parseLatestVersionInput(" v0.2.0 ")).toEqual({ ok: true, value: "0.2.0" });
    expect(parseLatestVersionInput("latest").ok).toBe(false);
  });
});
