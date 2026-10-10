import Link from "next/link";
import { prisma } from "@/lib/db";
import { getActiveCountry } from "@/lib/queries";
import { describeJob, isExpired } from "@/lib/jobs";
import { StatusBadge } from "../status-badge";
import { createJob } from "./actions";
import { AutoRefresh, RunTestForm } from "./client";

export const dynamic = "force-dynamic";

export default async function RunTestPage() {
  const [countries, channels, active, agent, jobs] = await Promise.all([
    prisma.country.findMany({ where: { active: true }, orderBy: { code: "asc" }, select: { code: true, name: true } }),
    prisma.channel.findMany({ orderBy: { name: "asc" }, select: { id: true, name: true, countryCode: true } }),
    getActiveCountry(),
    prisma.agent.findUnique({ where: { id: "default" } }),
    prisma.job.findMany({
      orderBy: { createdAt: "desc" },
      take: 10,
      include: { run: { include: { _count: { select: { results: true } } } }, user: { select: { email: true } } },
    }),
  ]);

  const online = !!agent && Date.now() - agent.lastHeartbeatAt.getTime() < 5 * 60_000;
  const now = new Date();
  // A pending job past its TTL is shown as expired even before the next agent poll writes it.
  const views = jobs.map((j) => {
    const status = j.status === "pending" && isExpired(j.createdAt, now) ? "expired" : j.status;
    const total = (j.options as { total?: number | null } | null)?.total ?? null;
    return {
      job: j,
      status,
      text: describeJob({ status, runStatus: j.run?.status ?? null, done: j.run?._count.results ?? 0, total }, online),
    };
  });
  const anyActive = views.some((v) => v.status === "pending" || v.status === "running");

  return (
    <div className="space-y-8">
      <AutoRefresh active={anyActive} />
      <div>
        <h1 className="text-2xl font-semibold">Run test</h1>
        <p className="text-sm text-neutral-600">
          Agent: {online ? "online" : "offline"}
          {agent?.detectedCountry ? `, detected country ${agent.detectedCountry}` : ""}. A queued test waits up to 6 hours for the agent.
        </p>
      </div>

      <RunTestForm
        action={createJob}
        countries={countries}
        channels={channels}
        defaultCountry={active ?? countries[0]?.code ?? "IT"}
        agentCountry={agent?.detectedCountry ?? null}
      />

      <section aria-label="Recent tests" className="space-y-2">
        <h2 className="text-lg font-medium">Recent tests</h2>
        {views.length === 0 ? (
          <p className="text-sm text-neutral-600">No tests yet.</p>
        ) : (
          <ul className="space-y-3 text-sm">
            {views.map(({ job, status, text }) => (
              <li key={job.id} className="rounded border border-neutral-200 p-3">
                <div className="flex items-center gap-2">
                  <StatusBadge status={status === "done" ? (job.run?.status ?? "completed") : status} />
                  <span className="font-medium">{job.countryCode}</span>
                  <span>{Array.isArray(job.channelIds) && job.channelIds.length > 0 ? `${job.channelIds.length} channel(s)` : "entire country"}</span>
                  <span className="text-neutral-500">
                    by {job.user.email} · {job.createdAt.toISOString().slice(0, 16).replace("T", " ")} UTC
                  </span>
                </div>
                <p className="mt-1">{text}</p>
                {job.run && (
                  <p className="mt-1">
                    <Link className="underline" href={`/runs/${job.run.id}`}>
                      Open the run
                    </Link>
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
