import { prisma } from "@/lib/db";
import { sendMail } from "@/lib/mail";
import { buildReport, type Issue, type ReportInput } from "@/lib/report";
import { asImagesSummary } from "@/lib/queries";
import { countStatuses, type ResultStatus } from "@/lib/results";

/** Recipients of the daily report: Setting "email.reportRecipients" (string[]), else ADMIN_EMAIL. */
export async function reportRecipients(): Promise<string[]> {
  const s = await prisma.setting.findUnique({ where: { key: "email.reportRecipients" } });
  const fromSetting = Array.isArray(s?.value) ? (s.value as unknown[]).filter((x): x is string => typeof x === "string") : [];
  if (fromSetting.length) return fromSetting;
  return process.env.ADMIN_EMAIL ? [process.env.ADMIN_EMAIL] : [];
}

export async function loadReportInput(runId: string): Promise<ReportInput | null> {
  const run = await prisma.run.findUnique({
    where: { id: runId },
    include: { country: true, results: { include: { channel: true, checks: true } } },
  });
  if (!run) return null;

  const counts = countStatuses(run.results.map((r) => r.status as ResultStatus));
  const images = asImagesSummary(run.images);

  const issues: Issue[] = [];
  for (const r of run.results) {
    for (const c of r.checks) {
      if (c.passed || c.severity === "info") continue;
      issues.push({ severity: c.severity, scope: r.channel.name, checkId: c.checkId, value: c.value, threshold: c.threshold, detail: c.detail });
    }
  }
  for (const c of images?.checks ?? []) {
    if (c.passed || c.severity === "info") continue;
    issues.push({
      severity: c.severity as "critical" | "warning",
      scope: c.scope ?? "page",
      checkId: c.checkId,
      value: c.value ?? null,
      threshold: c.threshold ?? null,
      detail: c.detail,
    });
  }

  const previous = await prisma.run.findFirst({
    where: { countryCode: run.countryCode, status: "completed", startedAt: { lt: run.startedAt } },
    orderBy: { startedAt: "desc" },
    include: { results: { select: { channelId: true, status: true } } },
  });
  const prevStatus = new Map(previous?.results.map((r) => [r.channelId, r.status]) ?? []);
  const becameCritical: string[] = [];
  const recovered: string[] = [];
  if (previous) {
    for (const r of run.results) {
      const before = prevStatus.get(r.channelId);
      if (r.status === "critical" && before !== "critical") becameCritical.push(r.channel.name);
      if (before === "critical" && r.status !== "critical") recovered.push(r.channel.name);
    }
  }

  const base = (process.env.AUTH_URL ?? "").replace(/\/$/, "");
  return {
    countryCode: run.countryCode,
    countryName: run.country.name,
    startedAt: run.startedAt,
    finishedAt: run.finishedAt,
    counts,
    images: Object.entries(images?.pages ?? {}).map(([page, p]) => {
      const total = Number(p.metrics["img.total_count"] ?? 0);
      return {
        page,
        total,
        broken: Math.round(Number(p.metrics["img.broken_ratio"] ?? 0) * total),
        placeholder: Math.round(Number(p.metrics["img.placeholder_ratio"] ?? 0) * total),
      };
    }),
    issues,
    becameCritical: becameCritical.sort(),
    recovered: recovered.sort(),
    dashboardUrl: `${base}/runs/${run.id}`,
  };
}

/** Builds and sends the daily report. Returns how many recipients it was sent to (0 = none configured). */
export async function sendDailyReport(runId: string): Promise<number> {
  const [input, to] = await Promise.all([loadReportInput(runId), reportRecipients()]);
  if (!input || to.length === 0) return 0;
  const { subject, html, text } = buildReport(input);
  for (const recipient of to) await sendMail({ to: recipient, subject, html, text });
  return to.length;
}
