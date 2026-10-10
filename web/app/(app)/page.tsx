import Link from "next/link";
import { prisma } from "@/lib/db";
import { asImagesSummary, getActiveCountry, latestCompletedRun, statusCountsForRun } from "@/lib/queries";
import { worstStatus, type ResultStatus } from "@/lib/results";
import { StatusBadge } from "./status-badge";

export const dynamic = "force-dynamic";

export default async function Overview() {
  const [countries, active, agent] = await Promise.all([
    prisma.country.findMany({ where: { active: true }, orderBy: { code: "asc" } }),
    getActiveCountry(),
    prisma.agent.findUnique({ where: { id: "default" } }),
  ]);

  const cards = await Promise.all(
    countries.map(async (c) => {
      const run = await latestCompletedRun(c.code);
      const counts = run ? await statusCountsForRun(run.id) : null;
      const present = counts ? (Object.keys(counts) as ResultStatus[]).filter((s) => counts[s] > 0) : [];
      return { country: c, run, counts, status: run ? worstStatus(present) : "none" };
    }),
  );

  const heartbeatAgeMin = agent ? Math.round((Date.now() - agent.lastHeartbeatAt.getTime()) / 60000) : null;
  const online = heartbeatAgeMin !== null && heartbeatAgeMin < 5;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Overview</h1>

      <section aria-label="Agent" className="rounded border border-neutral-200 p-4 text-sm">
        <h2 className="mb-1 font-medium">Agent</h2>
        {agent ? (
          <p>
            {online ? "Online" : "Offline"} — last heartbeat {heartbeatAgeMin} min ago, detected country{" "}
            {agent.detectedCountry ?? "unknown"}, version {agent.currentVersion ?? "?"}. Active country: {active ?? "not set"}.
          </p>
        ) : (
          <p>No heartbeat received yet. Start the agent and check its API key.</p>
        )}
      </section>

      <section aria-label="Countries" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map(({ country, run, counts, status }) => {
          const images = asImagesSummary(run?.images);
          const broken = images
            ? Object.entries(images.pages).map(([name, p]) => `${name} ${(Number(p.metrics["img.broken_ratio"] ?? 0) * 100).toFixed(1)}%`)
            : [];
          return (
            <Link
              key={country.code}
              href={`/channels?country=${country.code}`}
              className="rounded border border-neutral-200 p-4 hover:bg-neutral-50"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium">
                  {country.code} · {country.name}
                  {country.code === active ? " (active)" : ""}
                </span>
                <StatusBadge status={status} />
              </div>
              {run && counts ? (
                <div className="mt-2 text-sm text-neutral-700">
                  <p>Last run {run.startedAt.toISOString().slice(0, 16).replace("T", " ")} UTC</p>
                  <p>
                    {counts.ok} ok · {counts.warning} warning · {counts.critical} critical · {counts.error} error
                  </p>
                  {broken.length > 0 && <p>Broken images: {broken.join(", ")}</p>}
                </div>
              ) : (
                <p className="mt-2 text-sm text-neutral-600">
                  No run yet — set it as active country and switch your VPN.
                </p>
              )}
            </Link>
          );
        })}
      </section>
    </div>
  );
}
