/**
 * Daily report email (docs/04-WEB-APP-SPEC.md §4.1). Pure functions: data in, subject/html/text out.
 * Fetching lives in report-data.ts so this file stays unit-testable.
 */

export type Issue = {
  severity: "critical" | "warning";
  scope: string; // channel name, or page name for page-level checks
  checkId: string;
  value: number | null;
  threshold: number | null;
  detail?: string | null;
};

export type ReportInput = {
  countryCode: string;
  countryName: string;
  startedAt: Date;
  finishedAt: Date | null;
  counts: { ok: number; warning: number; critical: number; error: number };
  images: { page: string; total: number; broken: number; placeholder: number }[];
  issues: Issue[]; // every failed critical/warning check, unsorted
  becameCritical: string[]; // channel names, vs the previous completed run
  recovered: string[];
  dashboardUrl: string;
};

const TOP_ISSUES = 10;

const esc = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const fmt = (v: number | null) => (v === null ? "n/a" : Number.isInteger(v) ? String(v) : v.toFixed(3));

export function rankIssues(issues: Issue[]): Issue[] {
  const weight = { critical: 0, warning: 1 };
  return [...issues].sort(
    (a, b) => weight[a.severity] - weight[b.severity] || a.scope.localeCompare(b.scope) || a.checkId.localeCompare(b.checkId),
  );
}

export function buildReport(r: ReportInput): { subject: string; html: string; text: string } {
  const critical = r.issues.filter((i) => i.severity === "critical").length;
  const warnings = r.issues.filter((i) => i.severity === "warning").length;
  const date = r.startedAt.toISOString().slice(0, 10);
  const subject = `[Pippo] ${r.countryCode} — Daily report ${date} — ${critical} critical, ${warnings} warnings`;

  const top = rankIssues(r.issues).slice(0, TOP_ISSUES);
  const total = r.counts.ok + r.counts.warning + r.counts.critical + r.counts.error;
  const time = r.startedAt.toISOString().slice(0, 16).replace("T", " ") + " UTC";

  const issueLine = (i: Issue) =>
    `${i.severity.toUpperCase()} ${i.scope}: ${i.checkId} = ${fmt(i.value)} (threshold ${fmt(i.threshold)})${i.detail ? ` — ${i.detail}` : ""}`;
  const imageLine = (m: ReportInput["images"][number]) =>
    `${m.page}: ${m.total} images, broken ${pct(m.total ? m.broken / m.total : 0)}, placeholders ${pct(m.total ? m.placeholder / m.total : 0)}`;

  const text = [
    `Pippo daily report — ${r.countryName} (${r.countryCode})`,
    `Run: ${time}`,
    "",
    `Channels (${total}): ${r.counts.ok} ok, ${r.counts.warning} warning, ${r.counts.critical} critical, ${r.counts.error} error`,
    "",
    "Images",
    ...(r.images.length ? r.images.map((m) => `  ${imageLine(m)}`) : ["  no images result for this run"]),
    "",
    `Top issues (${top.length} of ${r.issues.length})`,
    ...(top.length ? top.map((i) => `  ${issueLine(i)}`) : ["  none"]),
    "",
    "Changes vs previous run",
    `  Became critical: ${r.becameCritical.length ? r.becameCritical.join(", ") : "none"}`,
    `  Recovered: ${r.recovered.length ? r.recovered.join(", ") : "none"}`,
    "",
    `Dashboard: ${r.dashboardUrl}`,
  ].join("\n");

  const li = (s: string) => `<li>${esc(s)}</li>`;
  const html = `<!doctype html><html><body style="font-family:Arial,sans-serif;color:#111;max-width:640px">
<h2>Pippo daily report — ${esc(r.countryName)} (${esc(r.countryCode)})</h2>
<p>Run: ${esc(time)}</p>
<p><strong>Channels (${total}):</strong> ${r.counts.ok} ok, ${r.counts.warning} warning, ${r.counts.critical} critical, ${r.counts.error} error</p>
<h3>Images</h3>
<ul>${r.images.length ? r.images.map((m) => li(imageLine(m))).join("") : li("no images result for this run")}</ul>
<h3>Top issues (${top.length} of ${r.issues.length})</h3>
<ul>${top.length ? top.map((i) => li(issueLine(i))).join("") : li("none")}</ul>
<h3>Changes vs previous run</h3>
<ul>${li(`Became critical: ${r.becameCritical.length ? r.becameCritical.join(", ") : "none"}`)}${li(`Recovered: ${r.recovered.length ? r.recovered.join(", ") : "none"}`)}</ul>
<p><a href="${esc(r.dashboardUrl)}">Open the run in the dashboard</a></p>
</body></html>`;

  return { subject, html, text };
}
