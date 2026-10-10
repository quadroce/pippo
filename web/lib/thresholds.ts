/**
 * Threshold catalog for the Settings page. Defaults mirror docs/03-CHECK-CATALOG.md and the
 * agent's `pippo/thresholds.py`; keep both in sync when a check is added (later phases add
 * the player, EPG and subtitle checks here).
 *
 * Stored values are raw: ratios as 0..1, durations in seconds, counts as numbers. The form shows
 * ratios as percentages.
 */

export type Unit = "ratio" | "seconds" | "ms" | "count";

export type CheckDef = {
  id: string;
  name: string;
  unit: Unit;
  description: string;
  defaults: { warn: number | null; critical: number | null };
};

export const CHECK_CATALOG: CheckDef[] = [
  {
    id: "img.broken_ratio",
    name: "Broken image ratio",
    unit: "ratio",
    description: "Images that fail to load, divided by all images on the page.",
    defaults: { warn: 0.01, critical: 0.05 },
  },
  {
    id: "img.placeholder_ratio",
    name: "Placeholder ratio",
    unit: "ratio",
    description: "Images matching a known fallback/placeholder, divided by all images.",
    defaults: { warn: 0.02, critical: 0.1 },
  },
  {
    id: "img.lazy_load_timeout",
    name: "Lazy load time",
    unit: "seconds",
    description: "Longest wait for images in view to finish loading after a scroll.",
    defaults: { warn: 5, critical: null },
  },
  {
    id: "img.aspect_mismatch",
    name: "Aspect ratio mismatches",
    unit: "count",
    description: "Number of images with the wrong proportions for their card type.",
    defaults: { warn: 0, critical: null },
  },
  {
    id: "img.channel_logo_missing",
    name: "Channels with a missing logo",
    unit: "count",
    description: "Evaluated per channel: any missing or broken logo.",
    defaults: { warn: 0, critical: null },
  },
  {
    id: "player.start_failed",
    name: "Playback did not start",
    unit: "count",
    description: "No playback within 15 s or a media error before the first frame. Any occurrence is critical.",
    defaults: { warn: null, critical: 0 },
  },
  {
    id: "player.ttff",
    name: "Time to first frame",
    unit: "ms",
    description: "Measured from the start of the page load until the first frame advances.",
    defaults: { warn: 4000, critical: 10000 },
  },
  {
    id: "player.stall_ratio",
    name: "Stall ratio",
    unit: "ratio",
    description: "Time spent stalled after the first frame, divided by the observation window.",
    defaults: { warn: 0.03, critical: 0.15 },
  },
  {
    id: "player.stall_count",
    name: "Stall count",
    unit: "count",
    description: "Stall episodes longer than 250 ms. The default warns at 3 or more.",
    defaults: { warn: 2, critical: null },
  },
  {
    id: "player.longest_stall",
    name: "Longest stall",
    unit: "ms",
    description: "Longest single stall episode.",
    defaults: { warn: 3000, critical: 10000 },
  },
  {
    id: "player.black_screen",
    name: "Black screen",
    unit: "seconds",
    description: "Longest run of black frames while playback advances. Not measurable on DRM content.",
    defaults: { warn: 3, critical: 10 },
  },
  {
    id: "player.frozen_frame",
    name: "Frozen frame",
    unit: "seconds",
    description: "Longest run of identical frames while playback advances. Not measurable on DRM content.",
    defaults: { warn: 3, critical: 10 },
  },
  {
    id: "player.audio_silence",
    name: "Silent audio",
    unit: "seconds",
    description: "Longest silence (below -60 dBFS) while the video advances.",
    defaults: { warn: 5, critical: 20 },
  },
  {
    id: "player.media_error",
    name: "Media errors",
    unit: "count",
    description: "Any media error reported by the player is critical.",
    defaults: { warn: null, critical: 0 },
  },
  {
    id: "player.segment_errors",
    name: "Segment errors",
    unit: "count",
    description: "HLS playlist or segment requests that failed. The default warns at 1 or more, critical at 5 or more.",
    defaults: { warn: 0, critical: 4 },
  },
  {
    id: "player.rendition_switches",
    name: "Rendition switches",
    unit: "count",
    description: "Quality level changes during the window.",
    defaults: { warn: 6, critical: null },
  },
];

export type StoredThresholds = Record<string, { warn: number | null; critical: number | null }>;

/** Effective thresholds: stored overrides on top of the catalog defaults. Unknown ids are dropped. */
export function effectiveThresholds(stored: unknown): StoredThresholds {
  const overrides = stored && typeof stored === "object" ? (stored as StoredThresholds) : {};
  const out: StoredThresholds = {};
  for (const c of CHECK_CATALOG) {
    const o = overrides[c.id];
    out[c.id] = o && typeof o === "object" ? { warn: num(o.warn), critical: num(o.critical) } : { ...c.defaults };
  }
  return out;
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : null;
}

export const toDisplay = (unit: Unit, v: number | null): string => (v === null ? "" : String(unit === "ratio" ? round(v * 100) : v));
const round = (n: number) => Math.round(n * 1000) / 1000;

export type ParsedInput = { ok: true; value: { warn: number | null; critical: number | null } } | { ok: false; error: string };

/** Parses the two form fields of one check ("" = disabled). Ratios arrive as percentages (0-100). */
export function parseThresholdInput(unit: Unit, warnRaw: string, criticalRaw: string): ParsedInput {
  const one = (raw: string): number | null | "bad" => {
    const s = raw.trim().replace(",", ".");
    if (s === "") return null;
    const n = Number(s);
    if (!Number.isFinite(n) || n < 0) return "bad";
    if (unit === "ratio") return n > 100 ? "bad" : n / 100;
    return n;
  };
  const warn = one(warnRaw);
  const critical = one(criticalRaw);
  if (warn === "bad" || critical === "bad") {
    return { ok: false, error: unit === "ratio" ? "Enter a percentage between 0 and 100 (or leave empty)" : "Enter a number of 0 or more (or leave empty)" };
  }
  if (warn !== null && critical !== null && critical < warn) {
    return { ok: false, error: "The critical threshold must not be lower than the warning threshold" };
  }
  return { ok: true, value: { warn, critical } };
}

/** Recipient list from free text (commas, semicolons, spaces or new lines). */
export function parseEmails(text: string): { ok: true; emails: string[] } | { ok: false; error: string } {
  const parts = text.split(/[\s,;]+/).map((s) => s.trim().toLowerCase()).filter(Boolean);
  const bad = parts.filter((e) => !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e));
  if (bad.length) return { ok: false, error: `Not a valid email: ${bad.join(", ")}` };
  return { ok: true, emails: [...new Set(parts)] };
}
