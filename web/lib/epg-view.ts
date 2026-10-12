/** Helpers for the EPG page: reading the stored result and exporting issues. Pure and unit-tested. */

export type EpgIssue = {
  channel: string;
  type: string;
  from?: number | null;
  to?: number | null;
  detail?: string | null;
};

export type EpgCheck = {
  checkId: string;
  severity: string;
  passed: boolean;
  value?: number | null;
  threshold?: number | null;
  detail?: string | null;
};

export function asIssues(value: unknown): EpgIssue[] {
  return Array.isArray(value) ? (value.filter((x) => x && typeof x === "object" && typeof (x as EpgIssue).channel === "string") as EpgIssue[]) : [];
}

export function asChecks(value: unknown): EpgCheck[] {
  return Array.isArray(value) ? (value.filter((x) => x && typeof x === "object" && typeof (x as EpgCheck).checkId === "string") as EpgCheck[]) : [];
}

export function metricNumber(metrics: unknown, key: string): number | null {
  if (!metrics || typeof metrics !== "object") return null;
  const v = (metrics as Record<string, unknown>)[key];
  return typeof v === "number" ? v : null;
}

const TYPE_LABELS: Record<string, string> = {
  gap: "Schedule gap",
  overlap: "Schedule overlap",
  no_now_program: "No programme now",
  missing_metadata: "Missing metadata",
  highlight_mismatch: "Highlighted programme differs from the API",
  not_rendered: "Not rendered in the guide",
};

export const issueTypeLabel = (type: string) => TYPE_LABELS[type] ?? type;

/** "10 Oct 18:25–19:10" in the given IANA timezone; "—" when there is no time. */
export function formatRange(from: number | null | undefined, to: number | null | undefined, timeZone: string): string {
  if (!from && !to) return "—";
  const fmt = (ms: number, withDate: boolean) => {
    try {
      return new Intl.DateTimeFormat("en-GB", {
        timeZone,
        ...(withDate ? { day: "2-digit", month: "short" } : {}),
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(new Date(ms));
    } catch {
      return new Date(ms).toISOString().slice(11, 16);
    }
  };
  if (from && to && from !== to) return `${fmt(from, true)} – ${fmt(to, false)}`;
  return fmt((from ?? to) as number, true);
}

const csvCell = (s: string) => (/[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);

/** CSV of the issues table (the runbook asks for an export to hand to the EPG team). */
export function issuesToCsv(issues: EpgIssue[], timeZone: string): string {
  const head = ["channel", "type", "from_utc", "to_utc", "local_range", "detail"];
  const iso = (ms?: number | null) => (ms ? new Date(ms).toISOString() : "");
  const rows = issues.map((i) =>
    [i.channel, issueTypeLabel(i.type), iso(i.from), iso(i.to), formatRange(i.from, i.to, timeZone), i.detail ?? ""].map(csvCell).join(","),
  );
  return [head.join(","), ...rows].join("\r\n") + "\r\n";
}

/** The check with this id, if the run has it. */
export const findCheck = (checks: EpgCheck[], id: string) => checks.find((c) => c.checkId === id);
