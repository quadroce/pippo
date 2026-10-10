import { prisma } from "@/lib/db";
import { sendMail } from "@/lib/mail";
import {
  countryWideChecks,
  countryWideEmail,
  decideEmail,
  digestEmail,
  individualAlertEmail,
  type FindingForEmail,
} from "@/lib/alerts";
import { reportRecipients } from "@/lib/report-data";

const baseUrl = () => (process.env.AUTH_URL ?? "").replace(/\/$/, "");

type ResultWithChecks = {
  id: string;
  runId: string;
  channelId: string;
  channel: { name: string };
  checks: { id: string; checkId: string; severity: string; passed: boolean; value: number | null; threshold: number | null; detail: string | null }[];
};

async function send(subject: string, text: string, html: string): Promise<boolean> {
  try {
    const to = await reportRecipients();
    if (to.length === 0) return false;
    for (const recipient of to) await sendMail({ to: recipient, subject, text, html });
    return true;
  } catch (e) {
    console.error("alert email failed", e);
    return false;
  }
}

/**
 * Called after every channel result is stored. Records one alert occurrence per failed critical
 * check and emails the first ones immediately (dedup and per-run cap in alerts.ts).
 */
export async function recordCriticalFindings(countryCode: string, runAt: Date, result: ResultWithChecks): Promise<void> {
  const now = new Date();
  for (const c of result.checks) {
    if (c.passed || c.severity !== "critical") continue;

    const [last, sentThisRun] = await Promise.all([
      prisma.alert.findFirst({
        where: { emailedAt: { not: null }, checkResult: { checkId: c.checkId, channelResult: { channelId: result.channelId } } },
        orderBy: { emailedAt: "desc" },
        select: { emailedAt: true },
      }),
      prisma.alert.count({
        where: { emailState: "sent", checkResult: { checkId: c.checkId, channelResult: { runId: result.runId } } },
      }),
    ]);

    const decision = decideEmail({ lastEmailedAt: last?.emailedAt ?? null, now, sentThisRunForCheck: sentThisRun });
    let state = decision === "send" ? "sent" : decision === "hold" ? "held" : "deduped";
    let emailedAt: Date | null = null;

    if (decision === "send") {
      const mail = individualAlertEmail({
        country: countryCode,
        finding: { checkId: c.checkId, channelName: result.channel.name, value: c.value, threshold: c.threshold, detail: c.detail },
        runAt,
        channelUrl: `${baseUrl()}/channels/${result.channelId}`,
        alertsUrl: `${baseUrl()}/alerts`,
      });
      if (await send(mail.subject, mail.text, mail.html)) emailedAt = now;
      else state = "failed";
    }
    await prisma.alert.create({ data: { checkResultId: c.id, emailState: state, emailedAt } });
  }
}

/**
 * Called when a run is closed. Replaces held findings with one country-wide email when a check
 * failed on a large share of the channels, otherwise sends them as a single digest.
 */
export async function finalizeAlerts(runId: string): Promise<{ countryWide: string[]; digested: number }> {
  const run = await prisma.run.findUnique({ where: { id: runId }, select: { countryCode: true, startedAt: true } });
  if (!run) return { countryWide: [], digested: 0 };

  const [total, alerts] = await Promise.all([
    prisma.channelResult.count({ where: { runId } }),
    prisma.alert.findMany({
      where: { checkResult: { channelResult: { runId } } },
      include: { checkResult: { include: { channelResult: { include: { channel: true } } } } },
    }),
  ]);

  const failing = new Map<string, string[]>();
  for (const a of alerts) {
    const list = failing.get(a.checkResult.checkId) ?? [];
    list.push(a.checkResult.channelResult.channel.name);
    failing.set(a.checkResult.checkId, list);
  }

  const wide = countryWideChecks(failing, total);
  const dayAgo = new Date(Date.now() - 24 * 3_600_000);
  const sentWide: string[] = [];

  for (const checkId of wide) {
    const already = await prisma.alert.findFirst({
      where: {
        emailState: "aggregated",
        createdAt: { gt: dayAgo },
        checkResult: { checkId, channelResult: { run: { countryCode: run.countryCode } } },
      },
    });
    let emailedAt: Date | null = null;
    if (!already) {
      const mail = countryWideEmail({
        country: run.countryCode,
        checkId,
        channels: failing.get(checkId) ?? [],
        total,
        runUrl: `${baseUrl()}/runs/${runId}`,
      });
      if (await send(mail.subject, mail.text, mail.html)) {
        emailedAt = new Date();
        sentWide.push(checkId);
      }
    }
    // Individual held or deduplicated findings of this check are covered by the country-wide notice.
    await prisma.alert.updateMany({
      where: { checkResult: { checkId, channelResult: { runId } }, emailState: { in: ["held", "deduped"] } },
      data: { emailState: "aggregated", ...(emailedAt ? { emailedAt } : {}) },
    });
  }

  const held = alerts.filter((a) => a.emailState === "held" && !wide.includes(a.checkResult.checkId));
  let digested = 0;
  if (held.length > 0) {
    const findings: FindingForEmail[] = held.map((a) => ({
      checkId: a.checkResult.checkId,
      channelName: a.checkResult.channelResult.channel.name,
      value: a.checkResult.value,
      threshold: a.checkResult.threshold,
    }));
    const mail = digestEmail({ country: run.countryCode, findings, runUrl: `${baseUrl()}/runs/${runId}`, alertsUrl: `${baseUrl()}/alerts` });
    const ok = await send(mail.subject, mail.text, mail.html);
    await prisma.alert.updateMany({
      where: { id: { in: held.map((a) => a.id) } },
      data: { emailState: ok ? "sent" : "failed", ...(ok ? { emailedAt: new Date() } : {}) },
    });
    if (ok) digested = held.length;
  }
  return { countryWide: sentWide, digested };
}

/** Acknowledges every open occurrence of one (channel, check) pair. Returns how many were closed. */
export async function acknowledgeGroup(channelId: string, checkId: string, userId: string): Promise<number> {
  const res = await prisma.alert.updateMany({
    where: { status: "open", checkResult: { checkId, channelResult: { channelId } } },
    data: { status: "acknowledged", acknowledgedAt: new Date(), acknowledgedBy: userId },
  });
  return res.count;
}
