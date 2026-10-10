/**
 * Alert rules and email content (docs/03-CHECK-CATALOG.md noise control, docs/04-WEB-APP-SPEC.md §4.2).
 * Pure functions; the database side is in alerts-data.ts.
 *
 * Policy:
 *  - a failed critical check creates an alert occurrence;
 *  - an email for the same (channel, check) is sent at most once per 24 h;
 *  - the first few new critical findings of a check in a run are emailed immediately, so a
 *    broken channel is reported within minutes; further ones are held until the run ends;
 *  - when a check fails on more than 30 % of the channels of a run (at least 3 channels, at
 *    least 10 measured) the held findings are replaced by one country-wide email.
 */

import { CHECK_CATALOG, type Unit } from "@/lib/thresholds";

export const DEDUP_HOURS = 24;
export const IMMEDIATE_CAP_PER_CHECK = 3;
export const COUNTRY_WIDE_SHARE = 0.3;
export const COUNTRY_WIDE_MIN_CHANNELS = 10;
export const COUNTRY_WIDE_MIN_FAILING = 3;

export type Decision = "send" | "hold" | "dedupe";

export function decideEmail(opts: { lastEmailedAt: Date | null; now: Date; sentThisRunForCheck: number; cap?: number }): Decision {
  const { lastEmailedAt, now } = opts;
  if (lastEmailedAt && now.getTime() - lastEmailedAt.getTime() < DEDUP_HOURS * 3_600_000) return "dedupe";
  if (opts.sentThisRunForCheck >= (opts.cap ?? IMMEDIATE_CAP_PER_CHECK)) return "hold";
  return "send";
}

/** Checks that failed on enough channels of a run to count as a platform-wide incident. */
export function countryWideChecks(failingChannelsByCheck: Map<string, string[]>, totalChannels: number): string[] {
  if (totalChannels < COUNTRY_WIDE_MIN_CHANNELS) return [];
  return [...failingChannelsByCheck.entries()]
    .filter(([, channels]) => channels.length >= COUNTRY_WIDE_MIN_FAILING && channels.length / totalChannels > COUNTRY_WIDE_SHARE)
    .map(([checkId]) => checkId);
}

const DEF = new Map(CHECK_CATALOG.map((c) => [c.id, c]));

export const checkName = (checkId: string) => DEF.get(checkId)?.name ?? checkId;

export function formatValue(checkId: string, v: number | null): string {
  if (v === null || v === undefined) return "n/a";
  const unit: Unit = DEF.get(checkId)?.unit ?? "count";
  if (unit === "ratio") return `${Math.round(v * 1000) / 10}%`;
  if (unit === "ms") return `${Math.round(v)} ms`;
  if (unit === "seconds") return `${Math.round(v * 10) / 10} s`;
  return String(Math.round(v * 1000) / 1000);
}

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const wrap = (text: string, links: { label: string; url: string }[]) => ({
  text: [text, "", ...links.map((l) => `${l.label}: ${l.url}`)].join("\n"),
  html: `<div style="font-family:Arial,sans-serif;color:#111;max-width:640px">${text
    .split("\n")
    .map((l) => (l ? `<p style="margin:4px 0">${esc(l)}</p>` : "<br>"))
    .join("")}<p>${links.map((l) => `<a href="${esc(l.url)}">${esc(l.label)}</a>`).join(" · ")}</p></div>`,
});

export type FindingForEmail = {
  checkId: string;
  channelName: string;
  value: number | null;
  threshold: number | null;
  detail?: string | null;
};

export function individualAlertEmail(opts: { country: string; finding: FindingForEmail; runAt: Date; channelUrl: string; alertsUrl: string }) {
  const f = opts.finding;
  const body = wrap(
    [
      `Channel: ${f.channelName}`,
      `Check: ${checkName(f.checkId)} (${f.checkId})`,
      `Measured: ${formatValue(f.checkId, f.value)} (threshold ${formatValue(f.checkId, f.threshold)})`,
      ...(f.detail ? [`Detail: ${f.detail}`] : []),
      `Run: ${opts.runAt.toISOString().slice(0, 16).replace("T", " ")} UTC`,
    ].join("\n"),
    [
      { label: "Evidence (screenshots and metrics)", url: opts.channelUrl },
      { label: "Acknowledge", url: opts.alertsUrl },
    ],
  );
  return { subject: `[Pippo] ${opts.country} — CRITICAL: ${f.channelName} — ${checkName(f.checkId)}`, ...body };
}

export function countryWideEmail(opts: {
  country: string;
  checkId: string;
  channels: string[];
  total: number;
  runUrl: string;
}) {
  const shown = [...opts.channels].sort().slice(0, 40);
  const more = opts.channels.length - shown.length;
  const body = wrap(
    [
      `${opts.channels.length} of ${opts.total} channels failed "${checkName(opts.checkId)}" in the same run (${Math.round((opts.channels.length / opts.total) * 100)}%).`,
      "This looks like a platform-wide incident (CDN or service): check it first instead of channel by channel.",
      "",
      "Affected channels:",
      ...shown.map((c) => `  - ${c}`),
      ...(more > 0 ? [`  ... and ${more} more`] : []),
    ].join("\n"),
    [{ label: "Open the run", url: opts.runUrl }],
  );
  return { subject: `[Pippo] ${opts.country} — CRITICAL: ${opts.channels.length} of ${opts.total} channels — ${checkName(opts.checkId)}`, ...body };
}

export function digestEmail(opts: { country: string; findings: FindingForEmail[]; runUrl: string; alertsUrl: string }) {
  const shown = opts.findings.slice(0, 40);
  const more = opts.findings.length - shown.length;
  const body = wrap(
    [
      `${opts.findings.length} more critical finding(s) in this run:`,
      ...shown.map((f) => `  - ${f.channelName}: ${checkName(f.checkId)} = ${formatValue(f.checkId, f.value)} (threshold ${formatValue(f.checkId, f.threshold)})`),
      ...(more > 0 ? [`  ... and ${more} more`] : []),
    ].join("\n"),
    [
      { label: "Open the run", url: opts.runUrl },
      { label: "Alerts", url: opts.alertsUrl },
    ],
  );
  return { subject: `[Pippo] ${opts.country} — CRITICAL: ${opts.findings.length} more critical finding(s)`, ...body };
}
