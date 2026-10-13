/** Channel flags edited in Settings (docs/04-WEB-APP-SPEC.md §3.3, §3.8). Pure, unit-tested. */

/** Whisper runs on the operator PC's CPU: a sample bigger than this makes the daily run much longer. */
export const RECOMMENDED_SAMPLE_MAX = 10;

export type FlagChannel = { id: string; isReference: boolean; subtitleSample: boolean };

export type FlagSelection = { referenceIds: string[]; sampleIds: string[] };

export type FlagUpdate =
  | { ok: true; referenceIds: string[]; sampleIds: string[]; changes: FlagChanges }
  | { ok: false; error: string };

export type FlagChanges = {
  referenceAdded: string[];
  referenceRemoved: string[];
  sampleAdded: string[];
  sampleRemoved: string[];
};

const diff = (before: Set<string>, after: Set<string>) => ({
  added: [...after].filter((id) => !before.has(id)).sort(),
  removed: [...before].filter((id) => !after.has(id)).sort(),
});

/**
 * Validates a selection against the channels of one country and works out what changes.
 * Ids that do not belong to the country are an error, not silently ignored.
 */
export function planFlagUpdate(channels: FlagChannel[], selection: FlagSelection): FlagUpdate {
  const known = new Set(channels.map((c) => c.id));
  const reference = [...new Set(selection.referenceIds)];
  const sample = [...new Set(selection.sampleIds)];
  const stray = [...reference, ...sample].filter((id) => !known.has(id));
  if (stray.length) return { ok: false, error: "Some selected channels do not belong to this country" };

  const ref = diff(new Set(channels.filter((c) => c.isReference).map((c) => c.id)), new Set(reference));
  const sub = diff(new Set(channels.filter((c) => c.subtitleSample).map((c) => c.id)), new Set(sample));
  return {
    ok: true,
    referenceIds: reference.sort(),
    sampleIds: sample.sort(),
    changes: { referenceAdded: ref.added, referenceRemoved: ref.removed, sampleAdded: sub.added, sampleRemoved: sub.removed },
  };
}

export const hasChanges = (c: FlagChanges) =>
  c.referenceAdded.length + c.referenceRemoved.length + c.sampleAdded.length + c.sampleRemoved.length > 0;

/** Message after saving, including the warning about an oversized sample. */
export function savedMessage(changes: FlagChanges, sampleSize: number): string {
  if (!hasChanges(changes)) return "Nothing changed.";
  const parts = [`Saved. Subtitle sample: ${sampleSize} channel(s).`];
  if (sampleSize > RECOMMENDED_SAMPLE_MAX) {
    parts.push(`That is more than the recommended ${RECOMMENDED_SAMPLE_MAX}: transcription runs on the agent PC and lengthens the daily run.`);
  }
  parts.push("The agent picks it up at its next heartbeat.");
  return parts.join(" ");
}
