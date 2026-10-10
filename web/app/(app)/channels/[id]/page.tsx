import Link from "next/link";
import { notFound } from "next/navigation";
import { checkName, formatValue } from "@/lib/alerts";
import { prisma } from "@/lib/db";
import { getGlobalThresholds } from "@/lib/settings";
import { CHECK_CATALOG } from "@/lib/thresholds";
import { StatusBadge } from "../../status-badge";
import { runTestOnChannel } from "./actions";
import { HistoryCharts, type Point } from "./history-charts";

export const dynamic = "force-dynamic";

const num = (m: unknown, key: string): number | null => {
  if (!m || typeof m !== "object") return null;
  const v = (m as Record<string, unknown>)[key];
  return typeof v === "number" ? v : null;
};
const when = (d: Date) => d.toISOString().slice(0, 16).replace("T", " ") + " UTC";
const LETTER: Record<string, string> = { ok: "O", warning: "W", critical: "C", error: "E" };

export default async function ChannelDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[\w-]{1,120}$/.test(id)) notFound();
  const channel = await prisma.channel.findUnique({ where: { id }, include: { country: true } });
  if (!channel) notFound();

  const since = new Date(Date.now() - 90 * 24 * 3_600_000);
  const [results, thresholds] = await Promise.all([
    prisma.channelResult.findMany({
      where: { channelId: id, measuredAt: { gt: since } },
      orderBy: { measuredAt: "desc" },
      take: 400,
      include: { run: { select: { id: true, startedAt: true } }, checks: true, screenshots: { orderBy: { tOffsetSec: "asc" } } },
    }),
    getGlobalThresholds(),
  ]);
  const latest = results[0];
  const ascending = [...results].reverse();
  const failedIds = new Set(latest?.checks.filter((c) => !c.passed).map((c) => c.checkId) ?? []);

  const points: Point[] = ascending.map((r) => ({
    label: r.measuredAt.toISOString().slice(5, 10),
    ttff: num(r.metrics, "player.ttff") === null ? null : Math.round((num(r.metrics, "player.ttff") as number) / 100) / 10,
    stall: num(r.metrics, "player.stall_ratio") === null ? null : Math.round((num(r.metrics, "player.stall_ratio") as number) * 1000) / 10,
    black: num(r.metrics, "player.black_screen"),
    frozen: num(r.metrics, "player.frozen_frame"),
    silence: num(r.metrics, "player.audio_silence"),
  }));

  return (
    <div className="space-y-8">
      <div className="space-y-1">
        <Link href={`/channels?country=${channel.countryCode}`} className="text-sm underline">
          ← Channels {channel.countryCode}
        </Link>
        <h1 className="text-2xl font-semibold">{channel.name}</h1>
        <p className="text-sm text-neutral-600">
          {channel.country.name} · {channel.category ?? "no category"}
          {channel.isReference ? " · reference channel" : ""}
          {channel.drm ? " · DRM" : ""}
          {channel.subtitleSample ? " · subtitle sample" : ""}
        </p>
        <form action={runTestOnChannel}>
          <input type="hidden" name="channelId" value={channel.id} />
          <button className="mt-2 rounded bg-black px-3 py-1 text-sm text-white">Run test on this channel</button>
        </form>
      </div>

      {!latest ? (
        <p className="text-neutral-600">No measurements in the last 90 days.</p>
      ) : (
        <>
          <section aria-label="Latest result" className="space-y-3">
            <h2 className="text-lg font-medium">Latest result</h2>
            <p className="text-sm">
              <StatusBadge status={latest.status} /> measured {when(latest.measuredAt)} in{" "}
              <Link className="underline" href={`/runs/${latest.run.id}`}>
                this run
              </Link>
              {latest.rawBufferUrl && (
                <>
                  {" "}
                  ·{" "}
                  <a className="underline" href={`/api/raw/${latest.id}`}>
                    download the raw event buffer
                  </a>
                </>
              )}
            </p>
            {typeof (latest.metrics as Record<string, unknown>)?.error === "string" && (
              <p role="alert" className="text-sm text-red-700">
                Measurement error: {String((latest.metrics as Record<string, unknown>).error)}
              </p>
            )}
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-neutral-300">
                  <th className="py-2">Metric</th>
                  <th>Value</th>
                  <th>Warning above</th>
                  <th>Critical above</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {CHECK_CATALOG.filter((c) => num(latest.metrics, c.id) !== null).map((c) => {
                  const check = latest.checks.find((k) => k.checkId === c.id);
                  const t = thresholds[c.id];
                  const failed = failedIds.has(c.id);
                  return (
                    <tr key={c.id} className={`border-b border-neutral-100 ${failed ? "bg-red-50" : ""}`}>
                      <td className="py-2">{checkName(c.id)}</td>
                      <td>{formatValue(c.id, num(latest.metrics, c.id))}</td>
                      <td>{t.warn === null ? "off" : formatValue(c.id, t.warn)}</td>
                      <td>{t.critical === null ? "off" : formatValue(c.id, t.critical)}</td>
                      <td>{check ? (check.passed ? "OK" : <StatusBadge status={check.severity} />) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {latest.checks.some((c) => !c.passed && c.detail) && (
              <ul className="text-sm text-neutral-700">
                {latest.checks
                  .filter((c) => !c.passed && c.detail)
                  .map((c) => (
                    <li key={c.id}>
                      {checkName(c.checkId)}: {c.detail}
                    </li>
                  ))}
              </ul>
            )}
          </section>

          <section aria-label="Screenshots" className="space-y-2">
            <h2 className="text-lg font-medium">Screenshots</h2>
            {latest.screenshots.length === 0 ? (
              <p className="text-sm text-neutral-600">No screenshots for this result.</p>
            ) : (
              <ul className="flex flex-wrap gap-3">
                {latest.screenshots.map((s) => (
                  <li key={s.id} className="text-xs">
                    <a href={`/api/screenshots/${s.id}`} target="_blank" rel="noreferrer">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={`/api/screenshots/${s.id}`} alt={`${s.kind} screenshot at ${s.tOffsetSec} seconds`} width={240} className="rounded border border-neutral-200" />
                    </a>
                    {s.kind === "failure" ? "On failure" : `t = ${s.tOffsetSec} s`}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}

      {results.length > 0 && (
        <>
          <section aria-label="History" className="space-y-3">
            <h2 className="text-lg font-medium">History (90 days)</h2>
            <HistoryCharts data={points} />
            <div role="img" aria-label="Status of each measurement, oldest first" className="flex flex-wrap gap-1">
              {ascending.map((r) => (
                <span
                  key={r.id}
                  title={`${when(r.measuredAt)}: ${r.status}`}
                  className={`inline-flex h-6 w-6 items-center justify-center rounded text-xs font-medium ${
                    r.status === "ok" ? "bg-green-100 text-green-900" : r.status === "warning" ? "bg-amber-100 text-amber-900" : r.status === "critical" ? "bg-red-100 text-red-900" : "bg-neutral-200 text-neutral-800"
                  }`}
                >
                  {LETTER[r.status]}
                </span>
              ))}
            </div>
            <p className="text-xs text-neutral-500">O = ok, W = warning, C = critical, E = error.</p>
          </section>

          <section aria-label="Past results" className="space-y-2">
            <h2 className="text-lg font-medium">Past results</h2>
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-neutral-300">
                  <th className="py-2">Measured</th>
                  <th>Status</th>
                  <th>Failed checks</th>
                  <th>Run</th>
                </tr>
              </thead>
              <tbody>
                {results.slice(0, 30).map((r) => (
                  <tr key={r.id} className="border-b border-neutral-100">
                    <td className="py-2">{when(r.measuredAt)}</td>
                    <td>
                      <StatusBadge status={r.status} />
                    </td>
                    <td>
                      {r.checks
                        .filter((c) => !c.passed)
                        .map((c) => checkName(c.checkId))
                        .join(", ") || "—"}
                    </td>
                    <td>
                      <Link className="underline" href={`/runs/${r.run.id}`}>
                        open
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}
