/**
 * Threshold catalog for the Settings page. Defaults mirror docs/03-CHECK-CATALOG.md and the
 * agent's `pippo/thresholds.py`; keep both in sync when a check is added (later phases add
 * the player, EPG and subtitle checks here).
 *
 * Stored values are raw: ratios as 0..1, durations in seconds, counts as numbers. The form shows
 * ratios as percentages.
 */

export type Unit = "ratio" | "seconds" | "count";

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
