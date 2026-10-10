import Link from "next/link";
import { prisma } from "@/lib/db";
import { StatusBadge } from "../status-badge";

export const dynamic = "force-dynamic";

function duration(start: Date, end: Date | null) {
  if (!end) return "—";
  const min = Math.round((end.getTime() - start.getTime()) / 60000);
  return `${min} min`;
}

export default async function RunsPage() {
  const runs = await prisma.run.findMany({
    orderBy: { startedAt: "desc" },
    take: 100,
    include: { results: { select: { status: true } } },
  });

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Runs</h1>
      {runs.length === 0 ? (
        <p className="text-neutral-600">No runs yet. They appear here once the agent has reported one.</p>
      ) : (
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-neutral-300">
              <th className="py-2">Started (UTC)</th>
              <th>Country</th>
              <th>Trigger</th>
              <th>Status</th>
              <th>Duration</th>
              <th>Channels</th>
              <th>Detected</th>
              <th>Agent</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => {
              const c = { ok: 0, warning: 0, critical: 0, error: 0 };
              for (const x of r.results) c[x.status] += 1;
              return (
                <tr key={r.id} className="border-b border-neutral-100">
                  <td className="py-2">
                    <Link className="underline" href={`/runs/${r.id}`}>
                      {r.startedAt.toISOString().slice(0, 16).replace("T", " ")}
                    </Link>
                  </td>
                  <td>{r.countryCode}</td>
                  <td>{r.trigger}</td>
                  <td>
                    <StatusBadge status={r.status} />
                  </td>
                  <td>{duration(r.startedAt, r.finishedAt)}</td>
                  <td>
                    {c.ok}/{c.warning}/{c.critical}/{c.error}
                  </td>
                  <td>{r.detectedCountry ?? "—"}</td>
                  <td>{r.agentVersion ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <p className="text-xs text-neutral-500">Channels column: ok / warning / critical / error.</p>
    </div>
  );
}
