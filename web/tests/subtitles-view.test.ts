import { describe, expect, it } from "vitest";
import { subtitleState } from "@/lib/subtitles-view";

describe("subtitleState", () => {
  it("words every state the agent can report", () => {
    const labels = ["no_subtitles", "not_enabled", "ok", "placeholder_only", "loaded_empty", "not_loaded"].map((s) => subtitleState({ "sub.state": s })?.label);
    expect(labels).toEqual(["None declared", "Not tested", "Working", "Track without content", "No cues yet", "Failed to load"]);
  });
  it("explains the placeholder case so it is not mistaken for a failure", () => {
    expect(subtitleState({ "sub.state": "placeholder_only" })?.hint).toContain("placeholder");
  });
  it("passes unknown states through and ignores missing or malformed metrics", () => {
    expect(subtitleState({ "sub.state": "brand_new" })).toEqual({ label: "brand_new", hint: "" });
    expect(subtitleState({})).toBeNull();
    expect(subtitleState(null)).toBeNull();
    expect(subtitleState({ "sub.state": 3 })).toBeNull();
  });
});
