import Link from "next/link";
import { prisma } from "@/lib/db";
import { getActiveCountry, latestCompletedRun } from "@/lib/queries";
import { StatusBadge } from "../status-badge";

export const dynamic = "force-dynamic";

export default async function ChannelsPage({ searchParams }: { searchParams: Promise<{ country?: string }> }) {
  const { country: requested } = await searchParams;
  const code = (requested && /^[A-Za-z]{2}$/.test(requested) ? requested : await getActiveCountry())?.toUpperCase();
  const run = code ? await latestCompletedRun(code) : null;

  const results = run
    ? await prisma.channelResult.findMany({
        where: { runId: run.id },
        include: { channel: true, checks: true },
        orderBy: { channel: { name: "asc" } },
      })
    : [];

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Channels{code ? ` · ${code}` : ""}</h1>
      {!run ? (
        <p className="text-neutral-600">
          No completed run for {code ?? "any country"} yet — set it as active country and switch your VPN.
        </p>
      ) : (
        <>
          <p className="text-sm text-neutral-600">
            From the <Link className="underline" href={`/runs/${run.id}`}>latest completed run</Link> (
            {run.startedAt.toISOString().slice(0, 16).replace("T", " ")} UTC). Player columns arrive with Phase 2.
          </p>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-neutral-300">
                <th className="py-2">Name</th>
                <th>Category</th>
                <th>Status</th>
                <th>Images</th>
                <th>Last measured</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => {
                const imgFailed = r.checks.filter((c) => c.checkId.startsWith("img.") && !c.passed);
                return (
                  <tr key={r.id} className="border-b border-neutral-100">
                    <td className="py-2">{r.channel.name}</td>
                    <td>{r.channel.category ?? "—"}</td>
                    <td>
                      <StatusBadge status={r.status} />
                    </td>
                    <td>{imgFailed.length === 0 ? "OK" : imgFailed.map((c) => c.checkId).join(", ")}</td>
                    <td>{r.measuredAt.toISOString().slice(0, 16).replace("T", " ")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
