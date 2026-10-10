import Link from "next/link";
import { prisma } from "@/lib/db";
import { checkName, formatValue } from "@/lib/alerts";
import { StatusBadge } from "../status-badge";
import { acknowledgeAlert } from "./actions";

export const dynamic = "force-dynamic";

type Row = {
  alert: { id: string; createdAt: Date; acknowledgedAt: Date | null; user: { email: string } | null };
  checkResult: {
    checkId: string;
    value: number | null;
    threshold: number | null;
    channelResult: { channelId: string; runId: string; channel: { name: string; countryCode: string } };
  };
};

type Group = {
  key: string;
  channelId: string;
  channelName: string;
  country: string;
  checkId: string;
  firstSeen: Date;
  lastSeen: Date;
  occurrences: number;
  latest: { value: number | null; threshold: number | null; runId: string };
  acknowledgedBy?: string;
  acknowledgedAt?: Date | null;
};

function group(rows: Row[]): Group[] {
  const map = new Map<string, Group>();
  for (const { alert, checkResult } of rows) {
    const cr = checkResult.channelResult;
    const key = `${cr.channelId}|${checkResult.checkId}`;
    const g = map.get(key);
    if (!g) {
      map.set(key, {
        key,
        channelId: cr.channelId,
        channelName: cr.channel.name,
        country: cr.channel.countryCode,
        checkId: checkResult.checkId,
        firstSeen: alert.createdAt,
        lastSeen: alert.createdAt,
        occurrences: 1,
        latest: { value: checkResult.value, threshold: checkResult.threshold, runId: cr.runId },
        acknowledgedBy: alert.user?.email,
        acknowledgedAt: alert.acknowledgedAt,
      });
      continue;
    }
    g.occurrences += 1;
    if (alert.createdAt < g.firstSeen) g.firstSeen = alert.createdAt;
    if (alert.createdAt > g.lastSeen) {
      g.lastSeen = alert.createdAt;
      g.latest = { value: checkResult.value, threshold: checkResult.threshold, runId: cr.runId };
    }
  }
  return [...map.values()].sort((a, b) => b.lastSeen.getTime() - a.lastSeen.getTime());
}

const when = (d: Date) => d.toISOString().slice(0, 16).replace("T", " ") + " UTC";

export default async function AlertsPage({ searchParams }: { searchParams: Promise<{ country?: string; check?: string }> }) {
  const sp = await searchParams;
  const country = sp.country && /^[A-Za-z]{2}$/.test(sp.country) ? sp.country.toUpperCase() : undefined;
  const check = sp.check && /^[\w.]{1,80}$/.test(sp.check) ? sp.check : undefined;

  const where = {
    checkResult: { ...(check ? { checkId: check } : {}), ...(country ? { channelResult: { channel: { countryCode: country } } } : {}) },
  };
  const include = {
    user: { select: { email: true } },
    checkResult: { include: { channelResult: { include: { channel: true } } } },
  };

  const [openRows, ackRows, countries, checks] = await Promise.all([
    prisma.alert.findMany({ where: { status: "open", ...where }, include, orderBy: { createdAt: "desc" }, take: 2000 }),
    prisma.alert.findMany({ where: { status: "acknowledged", ...where }, include, orderBy: { acknowledgedAt: "desc" }, take: 500 }),
    prisma.country.findMany({ where: { active: true }, orderBy: { code: "asc" }, select: { code: true } }),
    prisma.checkResult.findMany({ where: { severity: "critical", passed: false }, distinct: ["checkId"], select: { checkId: true } }),
  ]);
  const toRows = (r: typeof openRows): Row[] => r.map((a) => ({ alert: a, checkResult: a.checkResult }));
  const open = group(toRows(openRows));
  const acknowledged = group(toRows(ackRows)).slice(0, 50);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Alerts</h1>

      <form method="get" className="flex flex-wrap items-end gap-3 text-sm">
        <label>
          Country{" "}
          <select name="country" defaultValue={country ?? ""} className="rounded border border-neutral-300 px-2 py-1">
            <option value="">All</option>
            {countries.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code}
              </option>
            ))}
          </select>
        </label>
        <label>
          Check{" "}
          <select name="check" defaultValue={check ?? ""} className="rounded border border-neutral-300 px-2 py-1">
            <option value="">All</option>
            {checks.map((c) => (
              <option key={c.checkId} value={c.checkId}>
                {checkName(c.checkId)}
              </option>
            ))}
          </select>
        </label>
        <button className="rounded bg-black px-3 py-1 text-white">Filter</button>
      </form>

      <section aria-label="Open alerts" className="space-y-2">
        <h2 className="text-lg font-medium">Open ({open.length})</h2>
        {open.length === 0 ? (
          <p className="text-sm text-neutral-600">No open alerts. Critical findings appear here as soon as a run reports them.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-neutral-300">
                <th className="py-2">Channel</th>
                <th>Check</th>
                <th>Measured</th>
                <th>First seen</th>
                <th>Last seen</th>
                <th>Occurrences</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {open.map((g) => (
                <tr key={g.key} className="border-b border-neutral-100 align-top">
                  <td className="py-2">
                    <Link className="underline" href={`/channels/${g.channelId}`}>
                      {g.channelName}
                    </Link>{" "}
                    <span className="text-neutral-500">{g.country}</span>
                  </td>
                  <td>
                    <StatusBadge status="critical" /> {checkName(g.checkId)}
                  </td>
                  <td>
                    {formatValue(g.checkId, g.latest.value)} <span className="text-neutral-500">(threshold {formatValue(g.checkId, g.latest.threshold)})</span>
                  </td>
                  <td>{when(g.firstSeen)}</td>
                  <td>
                    <Link className="underline" href={`/runs/${g.latest.runId}`}>
                      {when(g.lastSeen)}
                    </Link>
                  </td>
                  <td>{g.occurrences}</td>
                  <td>
                    <form action={acknowledgeAlert}>
                      <input type="hidden" name="channelId" value={g.channelId} />
                      <input type="hidden" name="checkId" value={g.checkId} />
                      <button className="underline">Acknowledge</button>
                    </form>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="text-xs text-neutral-500">Acknowledging does not stop future alerts if the problem persists.</p>
      </section>

      <details>
        <summary className="cursor-pointer text-lg font-medium">Acknowledged ({acknowledged.length})</summary>
        {acknowledged.length === 0 ? (
          <p className="mt-2 text-sm text-neutral-600">Nothing acknowledged yet.</p>
        ) : (
          <ul className="mt-2 space-y-1 text-sm">
            {acknowledged.map((g) => (
              <li key={g.key}>
                {g.channelName} ({g.country}) — {checkName(g.checkId)}, {g.occurrences} occurrence(s), acknowledged by {g.acknowledgedBy ?? "unknown"}
                {g.acknowledgedAt ? ` on ${when(g.acknowledgedAt)}` : ""}
              </li>
            ))}
          </ul>
        )}
      </details>
    </div>
  );
}
