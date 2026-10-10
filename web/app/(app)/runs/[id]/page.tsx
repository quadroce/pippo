import { notFound } from "next/navigation";
import { prisma } from "@/lib/db";
import { asImagesSummary } from "@/lib/queries";
import { StatusBadge } from "../../status-badge";

export const dynamic = "force-dynamic";

const pct = (v: unknown) => `${(Number(v ?? 0) * 100).toFixed(1)}%`;

export default async function RunDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();
  const run = await prisma.run.findUnique({
    where: { id },
    include: {
      results: { include: { channel: true, checks: true }, orderBy: { channel: { name: "asc" } } },
    },
  });
  if (!run) notFound();
  const images = asImagesSummary(run.images);
  const log = Array.isArray(run.log) ? (run.log as { level: string; msg: string }[]) : [];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">
        Run {run.countryCode} · {run.startedAt.toISOString().slice(0, 16).replace("T", " ")} UTC
      </h1>
      <p className="text-sm">
        <StatusBadge status={run.status} /> trigger {run.trigger}, detected country {run.detectedCountry ?? "unknown"}, agent{" "}
        {run.agentVersion ?? "?"}
      </p>

      <section aria-label="Images">
        <h2 className="mb-2 text-lg font-medium">Images</h2>
        {images ? (
          <>
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-neutral-300">
                  <th className="py-2">Page</th>
                  <th>Images</th>
                  <th>Broken</th>
                  <th>Placeholders</th>
                  <th>Aspect issues</th>
                  <th>Lazy-load max (s)</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(images.pages).map(([name, p]) => (
                  <tr key={name} className="border-b border-neutral-100">
                    <td className="py-2">
                      {name}
                      {p.loadError ? ` (load error: ${p.loadError})` : ""}
                    </td>
                    <td>{String(p.metrics["img.total_count"] ?? 0)}</td>
                    <td>{pct(p.metrics["img.broken_ratio"])}</td>
                    <td>{pct(p.metrics["img.placeholder_ratio"])}</td>
                    <td>{String(p.metrics["img.aspect_mismatch"] ?? 0)}</td>
                    <td>{String(p.metrics["img.lazy_load_timeout"] ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ul className="mt-3 space-y-1 text-sm">
              {images.checks
                .filter((c) => !c.passed)
                .map((c, i) => (
                  <li key={i}>
                    <StatusBadge status={c.severity} /> {c.scope} {c.checkId}: {c.value} above {c.threshold}
                    {c.detail ? ` — ${c.detail}` : ""}
                  </li>
                ))}
            </ul>
          </>
        ) : (
          <p className="text-sm text-neutral-600">No images result uploaded for this run.</p>
        )}
      </section>

      <section aria-label="Channels">
        <h2 className="mb-2 text-lg font-medium">Channels ({run.results.length})</h2>
        {run.results.length === 0 ? (
          <p className="text-sm text-neutral-600">No channel results.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-neutral-300">
                <th className="py-2">Channel</th>
                <th>Status</th>
                <th>Failed checks</th>
              </tr>
            </thead>
            <tbody>
              {run.results.map((r) => (
                <tr key={r.id} className="border-b border-neutral-100">
                  <td className="py-2">{r.channel.name}</td>
                  <td>
                    <StatusBadge status={r.status} />
                  </td>
                  <td>
                    {r.checks
                      .filter((c) => !c.passed)
                      .map((c) => c.checkId)
                      .join(", ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {log.length > 0 && (
        <section aria-label="Run log">
          <h2 className="mb-2 text-lg font-medium">Run log</h2>
          <ul className="space-y-1 text-sm">
            {log.map((l, i) => (
              <li key={i}>
                [{l.level}] {l.msg}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
