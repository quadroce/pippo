import Link from "next/link";
import { checkName, formatValue } from "@/lib/alerts";
import { prisma } from "@/lib/db";
import { asChecks, asIssues, findCheck, formatRange, issueTypeLabel, metricNumber, type EpgCheck } from "@/lib/epg-view";
import { getActiveCountry } from "@/lib/queries";
import { StatusBadge } from "../status-badge";

export const dynamic = "force-dynamic";

const pct = (v: number | null) => (v === null ? "—" : `${(v * 100).toFixed(1)}%`);
const num = (v: number | null, digits = 0) => (v === null ? "—" : v.toFixed(digits));

/** A metric with its verdict; the threshold is on hover and written out, never only a color. */
function Row({ label, value, check, hint }: { label: string; value: string; check?: EpgCheck; hint?: string }) {
  const failed = check && !check.passed;
  return (
    <tr className={`border-b border-neutral-100 ${failed ? "bg-red-50" : ""}`}>
      <td className="py-2 pr-4">{label}</td>
      <td title={check?.threshold != null ? `Threshold ${formatValue(check.checkId, check.threshold)}` : undefined}>{value}</td>
      <td>{check ? check.passed ? "OK" : <StatusBadge status={check.severity} /> : <span className="text-neutral-500">{hint ?? ""}</span>}</td>
      <td className="text-neutral-600">{failed && check?.detail ? check.detail : ""}</td>
    </tr>
  );
}

export default async function EpgPage({ searchParams }: { searchParams: Promise<{ country?: string; type?: string }> }) {
  const sp = await searchParams;
  const code = (sp.country && /^[A-Za-z]{2}$/.test(sp.country) ? sp.country : await getActiveCountry())?.toUpperCase();
  const country = code ? await prisma.country.findUnique({ where: { code } }) : null;
  const run = code
    ? await prisma.run.findFirst({
        where: { countryCode: code, status: "completed", epg: { isNot: null } },
        orderBy: { startedAt: "desc" },
        include: { epg: true },
      })
    : null;
  const epg = run?.epg ?? null;

  if (!country || !run || !epg) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold">EPG{code ? ` · ${code}` : ""}</h1>
        <p className="text-neutral-600">
          No EPG result for {code ?? "any country"} yet — set it as active country, switch your VPN and run a full measurement with the images and EPG
          checks.
        </p>
      </div>
    );
  }

  const m = epg.metrics;
  const checks = asChecks(epg.checks);
  const all = asIssues(epg.issues);
  const types = [...new Set(all.map((i) => i.type))].sort();
  const type = sp.type && types.includes(sp.type) ? sp.type : undefined;
  const issues = type ? all.filter((i) => i.type === type) : all;
  const tz = country.timezone;

  const rendered = metricNumber(m, "epg.rendered_channels");
  const apiCount = metricNumber(m, "epg.guide_total") ?? metricNumber(m, "epg.channel_count");

  return (
    <div className="space-y-8">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">
          EPG · {country.code} · {country.name}
        </h1>
        <p className="text-sm text-neutral-600">
          From the{" "}
          <Link className="underline" href={`/runs/${run.id}`}>
            latest completed run
          </Link>{" "}
          ({run.startedAt.toISOString().slice(0, 16).replace("T", " ")} UTC). Times below are in {tz}. Hover a value to see its threshold.
        </p>
      </div>

      <section aria-label="Data quality" className="space-y-2">
        <h2 className="text-lg font-medium">Data quality</h2>
        <table className="w-full text-left text-sm">
          <tbody>
            <Row label="Guide API" value={metricNumber(m, "epg.api_failed") ? "failed" : "reachable"} check={findCheck(checks, "epg.api_failed")} />
            <Row label="Channels with data" value={`${num(metricNumber(m, "epg.channel_count"))} of ${num(apiCount)}`} check={findCheck(checks, "epg.channel_count_drop")} />
            <Row label="Coverage ahead (shortest channel)" value={`${num(metricNumber(m, "epg.coverage_hours"), 1)} h`} check={findCheck(checks, "epg.coverage_hours")} />
            <Row label="Channels with schedule gaps" value={num(metricNumber(m, "epg.channels_with_gaps"))} hint="per channel, see issues" />
            <Row label="Channels with overlaps" value={num(metricNumber(m, "epg.channels_with_overlaps"))} hint="per channel, see issues" />
            <Row label="Channels with no programme now" value={num(metricNumber(m, "epg.channels_no_now"))} hint="per channel, see issues" />
            <Row label="Programmes missing metadata" value={pct(metricNumber(m, "epg.missing_metadata_ratio"))} check={findCheck(checks, "epg.missing_metadata")} />
            <Row label="Descriptions in the wrong language" value={pct(metricNumber(m, "epg.language_mismatch_ratio"))} check={findCheck(checks, "epg.language_mismatch")} />
            <Row label="Timezone offset" value="not measured" hint="the guide has no time axis, see the check catalog notes" />
          </tbody>
        </table>
      </section>

      <section aria-label="Rendering" className="space-y-2">
        <h2 className="text-lg font-medium">Rendering</h2>
        <table className="w-full text-left text-sm">
          <tbody>
            <Row label="Rendered channels vs API" value={`${num(rendered)} of ${num(apiCount)}`} check={findCheck(checks, "epg.render_channel_count")} />
            <Row label="Highlighted programme differs from the API" value={`${num(metricNumber(m, "epg.highlight_mismatches"))} channel(s)`} check={findCheck(checks, "epg.highlight_mismatch")} />
            <Row label="Empty tiles" value={pct(metricNumber(m, "epg.empty_tile_ratio"))} check={findCheck(checks, "epg.empty_cells")} />
            <Row label="Scroll load time" value={`${num(metricNumber(m, "epg.scroll_load_seconds"), 1)} s`} check={findCheck(checks, "epg.scroll_load_time")} />
            <Row label="Now marker position" value="not applicable" hint="the guide has no now marker" />
          </tbody>
        </table>
      </section>

      <section aria-label="Issues" className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-medium">Issues ({issues.length}{type ? ` of ${all.length}` : ""})</h2>
          <div className="flex items-center gap-3 text-sm">
            <form method="get" className="flex items-center gap-2">
              <input type="hidden" name="country" value={country.code} />
              <label>
                Type{" "}
                <select name="type" defaultValue={type ?? ""} className="rounded border border-neutral-300 px-2 py-1">
                  <option value="">All</option>
                  {types.map((t) => (
                    <option key={t} value={t}>
                      {issueTypeLabel(t)}
                    </option>
                  ))}
                </select>
              </label>
              <button className="rounded bg-black px-3 py-1 text-white">Filter</button>
            </form>
            <a className="underline" href={`/api/epg/${run.id}/issues.csv`}>
              Download CSV
            </a>
          </div>
        </div>
        {issues.length === 0 ? (
          <p className="text-sm text-neutral-600">No issues in this run.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-neutral-300">
                <th className="py-2">Channel</th>
                <th>Issue</th>
                <th>Time range</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {issues.map((i, k) => (
                <tr key={k} className="border-b border-neutral-100">
                  <td className="py-2">{i.channel}</td>
                  <td>{issueTypeLabel(i.type)}</td>
                  <td>{formatRange(i.from, i.to, tz)}</td>
                  <td>{i.detail ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {all.length >= 300 && <p className="text-xs text-neutral-500">The agent keeps at most 300 issues per run; the counts above are complete.</p>}
      </section>

      <section aria-label="Failed checks" className="space-y-2">
        <h2 className="text-lg font-medium">Failed checks</h2>
        {checks.filter((c) => !c.passed).length === 0 ? (
          <p className="text-sm text-neutral-600">Every run-level EPG check passed.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {checks
              .filter((c) => !c.passed)
              .map((c) => (
                <li key={c.checkId}>
                  <StatusBadge status={c.severity} /> {checkName(c.checkId)}: {formatValue(c.checkId, c.value ?? null)} (threshold {formatValue(c.checkId, c.threshold ?? null)})
                  {c.detail ? ` — ${c.detail}` : ""}
                </li>
              ))}
          </ul>
        )}
      </section>

      <section aria-label="Guide preview" className="space-y-2">
        <h2 className="text-lg font-medium">Guide as rendered during the run</h2>
        {epg.screenshotUrl ? (
          <a href={`/api/epg/${run.id}/screenshot`} target="_blank" rel="noreferrer">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`/api/epg/${run.id}/screenshot`} alt="Screenshot of the EPG guide taken during the run" className="max-w-full rounded border border-neutral-200" width={960} />
          </a>
        ) : (
          <p className="text-sm text-neutral-600">No screenshot was uploaded for this run.</p>
        )}
      </section>
    </div>
  );
}
