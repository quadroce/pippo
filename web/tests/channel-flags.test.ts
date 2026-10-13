import { describe, expect, it } from "vitest";
import { hasChanges, planFlagUpdate, RECOMMENDED_SAMPLE_MAX, savedMessage } from "@/lib/channel-flags";

const channels = [
  { id: "it-a", isReference: true, subtitleSample: false },
  { id: "it-b", isReference: false, subtitleSample: true },
  { id: "it-c", isReference: false, subtitleSample: false },
];

describe("planFlagUpdate", () => {
  it("computes what was added and removed for each flag", () => {
    const r = planFlagUpdate(channels, { referenceIds: ["it-a", "it-c"], sampleIds: ["it-c"] });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.changes).toEqual({ referenceAdded: ["it-c"], referenceRemoved: [], sampleAdded: ["it-c"], sampleRemoved: ["it-b"] });
    expect(hasChanges(r.changes)).toBe(true);
  });

  it("reports no changes for an identical selection and de-duplicates ids", () => {
    const r = planFlagUpdate(channels, { referenceIds: ["it-a", "it-a"], sampleIds: ["it-b"] });
    expect(r.ok && hasChanges(r.changes)).toBe(false);
    expect(r.ok && r.referenceIds).toEqual(["it-a"]);
  });

  it("clears a flag when nothing is selected", () => {
    const r = planFlagUpdate(channels, { referenceIds: [], sampleIds: [] });
    expect(r.ok && r.changes.referenceRemoved).toEqual(["it-a"]);
    expect(r.ok && r.changes.sampleRemoved).toEqual(["it-b"]);
  });

  it("rejects channels of another country instead of ignoring them", () => {
    expect(planFlagUpdate(channels, { referenceIds: ["fr-x"], sampleIds: [] })).toEqual({
      ok: false,
      error: "Some selected channels do not belong to this country",
    });
    expect(planFlagUpdate(channels, { referenceIds: [], sampleIds: ["nope"] }).ok).toBe(false);
  });
});

describe("savedMessage", () => {
  const changed = { referenceAdded: [], referenceRemoved: [], sampleAdded: ["x"], sampleRemoved: [] };
  it("says nothing changed when nothing did", () => {
    expect(savedMessage({ referenceAdded: [], referenceRemoved: [], sampleAdded: [], sampleRemoved: [] }, 3)).toBe("Nothing changed.");
  });
  it("warns above the recommended sample size only", () => {
    expect(savedMessage(changed, RECOMMENDED_SAMPLE_MAX)).not.toContain("recommended");
    expect(savedMessage(changed, RECOMMENDED_SAMPLE_MAX + 1)).toContain(`recommended ${RECOMMENDED_SAMPLE_MAX}`);
    expect(savedMessage(changed, 4)).toContain("next heartbeat");
  });
});
