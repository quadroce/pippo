import { del } from "@vercel/blob";
import { prisma } from "@/lib/db";
import { JOB_TTL_HOURS } from "@/lib/jobs";
import { effectiveRetention, retentionCutoffs, type Retention } from "@/lib/retention";

export const SETTING_RETENTION = "retention";
export const SETTING_RETENTION_LAST = "retention.lastRun";

export type CleanupResult = {
  at: string;
  screenshots: number;
  rawBuffers: number;
  epgScreenshots: number;
  runs: number;
  jobs: number;
  expiredJobs: number;
  sessions: number;
  tokens: number;
  blobFailures: number;
  partial: boolean; // stopped at the batch limit: more is waiting for the next run
};

export async function getRetention(): Promise<Retention> {
  const s = await prisma.setting.findUnique({ where: { key: SETTING_RETENTION } });
  return effectiveRetention(s?.value && typeof s.value === "object" ? (s.value as Record<string, unknown>) : null);
}

/**
 * Deletes blobs. Without a Blob token (local development) there is nothing to delete and the rows may go.
 * Returns false when the store refused, so the caller keeps the rows and retries next time instead of
 * orphaning the files.
 */
async function deleteBlobs(urls: string[]): Promise<boolean> {
  const list = [...new Set(urls.filter(Boolean))];
  if (list.length === 0) return true;
  if (!process.env.BLOB_READ_WRITE_TOKEN) return true;
  try {
    await del(list);
    return true;
  } catch (e) {
    console.error("blob deletion failed", e);
    return false;
  }
}

/**
 * Applies the retention policy in bounded batches (serverless time limits): evidence first (screenshots,
 * raw buffers, guide pictures older than the screenshot retention), then whole runs older than the metrics
 * retention together with any blob they still hold, then housekeeping. Files are deleted before their rows.
 */
export async function runCleanup(now: Date = new Date(), opts: { batch?: number; maxBatches?: number } = {}): Promise<CleanupResult> {
  const batch = opts.batch ?? 50;
  const maxBatches = opts.maxBatches ?? 20;
  const { screenshotCutoff, metricsCutoff } = retentionCutoffs(now, await getRetention());
  const r: CleanupResult = { at: now.toISOString(), screenshots: 0, rawBuffers: 0, epgScreenshots: 0, runs: 0, jobs: 0, expiredJobs: 0, sessions: 0, tokens: 0, blobFailures: 0, partial: false };

  r.expiredJobs = (
    await prisma.job.updateMany({
      where: { status: "pending", createdAt: { lt: new Date(now.getTime() - JOB_TTL_HOURS * 3_600_000) } },
      data: { status: "expired" },
    })
  ).count;

  for (let i = 0; i < maxBatches; i++) {
    const shots = await prisma.screenshot.findMany({
      where: { channelResult: { measuredAt: { lt: screenshotCutoff } } },
      take: batch,
      select: { id: true, blobUrl: true },
    });
    if (shots.length === 0) break;
    if (!(await deleteBlobs(shots.map((s) => s.blobUrl)))) { r.blobFailures++; break; }
    r.screenshots += (await prisma.screenshot.deleteMany({ where: { id: { in: shots.map((s) => s.id) } } })).count;
    if (i === maxBatches - 1) r.partial = true;
  }

  for (let i = 0; i < maxBatches; i++) {
    const raws = await prisma.channelResult.findMany({
      where: { rawBufferUrl: { not: null }, measuredAt: { lt: screenshotCutoff } },
      take: batch,
      select: { id: true, rawBufferUrl: true },
    });
    if (raws.length === 0) break;
    if (!(await deleteBlobs(raws.map((x) => x.rawBufferUrl as string)))) { r.blobFailures++; break; }
    r.rawBuffers += (await prisma.channelResult.updateMany({ where: { id: { in: raws.map((x) => x.id) } }, data: { rawBufferUrl: null } })).count;
    if (i === maxBatches - 1) r.partial = true;
  }

  for (let i = 0; i < maxBatches; i++) {
    const epgs = await prisma.epgResult.findMany({
      where: { screenshotUrl: { not: null }, run: { startedAt: { lt: screenshotCutoff } } },
      take: batch,
      select: { id: true, screenshotUrl: true },
    });
    if (epgs.length === 0) break;
    if (!(await deleteBlobs(epgs.map((x) => x.screenshotUrl as string)))) { r.blobFailures++; break; }
    r.epgScreenshots += (await prisma.epgResult.updateMany({ where: { id: { in: epgs.map((x) => x.id) } }, data: { screenshotUrl: null } })).count;
    if (i === maxBatches - 1) r.partial = true;
  }

  for (let i = 0; i < maxBatches; i++) {
    const runs = await prisma.run.findMany({ where: { startedAt: { lt: metricsCutoff } }, take: 20, select: { id: true } });
    if (runs.length === 0) break;
    const ids = runs.map((x) => x.id);
    const [shots, results, epgs] = await Promise.all([
      prisma.screenshot.findMany({ where: { channelResult: { runId: { in: ids } } }, select: { blobUrl: true } }),
      prisma.channelResult.findMany({ where: { runId: { in: ids }, rawBufferUrl: { not: null } }, select: { rawBufferUrl: true } }),
      prisma.epgResult.findMany({ where: { runId: { in: ids }, screenshotUrl: { not: null } }, select: { screenshotUrl: true } }),
    ]);
    const urls = [...shots.map((s) => s.blobUrl), ...results.map((x) => x.rawBufferUrl as string), ...epgs.map((x) => x.screenshotUrl as string)];
    if (!(await deleteBlobs(urls))) { r.blobFailures++; break; }
    r.runs += (await prisma.run.deleteMany({ where: { id: { in: ids } } })).count; // results, checks, alerts, EPG results cascade
    if (i === maxBatches - 1) r.partial = true;
  }

  r.jobs = (await prisma.job.deleteMany({ where: { createdAt: { lt: metricsCutoff }, status: { in: ["done", "expired"] }, run: { is: null } } })).count;
  r.sessions = (await prisma.session.deleteMany({ where: { expires: { lt: now } } })).count;
  r.tokens = (await prisma.verificationToken.deleteMany({ where: { expires: { lt: now } } })).count;

  await prisma.setting.upsert({
    where: { key: SETTING_RETENTION_LAST },
    update: { value: r as unknown as object },
    create: { key: SETTING_RETENTION_LAST, value: r as unknown as object },
  });
  return r;
}
