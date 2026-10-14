import { beforeEach, describe, expect, it, vi } from "vitest";

const order: string[] = [];
const db = vi.hoisted(() => ({
  setting: { findUnique: vi.fn(), upsert: vi.fn() },
  job: { updateMany: vi.fn(), deleteMany: vi.fn() },
  screenshot: { findMany: vi.fn(), deleteMany: vi.fn() },
  channelResult: { findMany: vi.fn(), updateMany: vi.fn() },
  epgResult: { findMany: vi.fn(), updateMany: vi.fn() },
  run: { findMany: vi.fn(), deleteMany: vi.fn() },
  session: { deleteMany: vi.fn() },
  verificationToken: { deleteMany: vi.fn() },
}));
vi.mock("@/lib/db", () => ({ prisma: db }));
const del = vi.hoisted(() => vi.fn());
vi.mock("@vercel/blob", () => ({ del }));

import { runCleanup } from "@/lib/retention-data";

const NOW = new Date("2026-10-31T12:00:00Z");

beforeEach(() => {
  vi.clearAllMocks();
  order.length = 0;
  process.env.BLOB_READ_WRITE_TOKEN = "token";
  db.setting.findUnique.mockResolvedValue(null); // defaults: 30 and 90 days
  db.job.updateMany.mockResolvedValue({ count: 0 });
  db.job.deleteMany.mockResolvedValue({ count: 0 });
  db.screenshot.findMany.mockResolvedValue([]);
  db.channelResult.findMany.mockResolvedValue([]);
  db.epgResult.findMany.mockResolvedValue([]);
  db.run.findMany.mockResolvedValue([]);
  db.session.deleteMany.mockResolvedValue({ count: 0 });
  db.verificationToken.deleteMany.mockResolvedValue({ count: 0 });
  del.mockImplementation(async () => { order.push("del"); });
  db.screenshot.deleteMany.mockImplementation(async (a: { where: { id: { in: string[] } } }) => { order.push("rows"); return { count: a.where.id.in.length }; });
  db.run.deleteMany.mockImplementation(async (a: { where: { id: { in: string[] } } }) => { order.push("runs"); return { count: a.where.id.in.length }; });
});

describe("runCleanup", () => {
  it("is a quiet no-op when there is nothing old, and records the result", async () => {
    const r = await runCleanup(NOW);
    expect(r).toMatchObject({ screenshots: 0, runs: 0, blobFailures: 0, partial: false });
    expect(del).not.toHaveBeenCalled();
    expect(db.setting.upsert.mock.calls[0][0].where.key).toBe("retention.lastRun");
  });

  it("uses the cutoffs from the settings and deletes the files before their rows", async () => {
    db.setting.findUnique.mockResolvedValue({ value: { screenshotDays: 10, metricsDays: 40 } });
    db.screenshot.findMany.mockResolvedValueOnce([{ id: "s1", blobUrl: "https://b/1.png" }, { id: "s2", blobUrl: "https://b/2.png" }]).mockResolvedValue([]);
    const r = await runCleanup(NOW);
    expect(db.screenshot.findMany.mock.calls[0][0].where.channelResult.measuredAt.lt.toISOString()).toBe("2026-10-21T12:00:00.000Z");
    expect(del).toHaveBeenCalledWith(["https://b/1.png", "https://b/2.png"]);
    expect(order).toEqual(["del", "rows"]);
    expect(r.screenshots).toBe(2);
  });

  it("keeps the rows when the file store refuses, so nothing is orphaned and the next run retries", async () => {
    del.mockRejectedValue(new Error("store down"));
    db.screenshot.findMany.mockResolvedValue([{ id: "s1", blobUrl: "https://b/1.png" }]);
    const r = await runCleanup(NOW);
    expect(r.blobFailures).toBeGreaterThan(0);
    expect(db.screenshot.deleteMany).not.toHaveBeenCalled();
  });

  it("clears raw buffer and guide picture links after deleting the files", async () => {
    db.channelResult.findMany.mockResolvedValueOnce([{ id: "c1", rawBufferUrl: "https://b/raw.gz" }]).mockResolvedValue([]);
    db.epgResult.findMany.mockResolvedValueOnce([{ id: "e1", screenshotUrl: "https://b/epg.png" }]).mockResolvedValue([]);
    db.channelResult.updateMany.mockResolvedValue({ count: 1 });
    db.epgResult.updateMany.mockResolvedValue({ count: 1 });
    const r = await runCleanup(NOW);
    expect(db.channelResult.updateMany).toHaveBeenCalledWith({ where: { id: { in: ["c1"] } }, data: { rawBufferUrl: null } });
    expect(db.epgResult.updateMany).toHaveBeenCalledWith({ where: { id: { in: ["e1"] } }, data: { screenshotUrl: null } });
    expect([r.rawBuffers, r.epgScreenshots]).toEqual([1, 1]);
  });

  it("deletes old runs together with every file they still hold, files first", async () => {
    db.run.findMany.mockResolvedValueOnce([{ id: "r1" }, { id: "r2" }]).mockResolvedValue([]);
    db.screenshot.findMany.mockImplementation(async (a: { where: { channelResult?: { runId?: unknown } } }) =>
      a.where.channelResult?.runId ? [{ blobUrl: "https://b/s.png" }] : [],
    );
    db.channelResult.findMany.mockImplementation(async (a: { where: { runId?: unknown } }) => (a.where.runId ? [{ rawBufferUrl: "https://b/raw.gz" }] : []));
    db.epgResult.findMany.mockImplementation(async (a: { where: { runId?: unknown } }) => (a.where.runId ? [{ screenshotUrl: "https://b/epg.png" }] : []));
    const r = await runCleanup(NOW);
    expect(del).toHaveBeenCalledWith(["https://b/s.png", "https://b/raw.gz", "https://b/epg.png"]);
    expect(order.indexOf("del")).toBeLessThan(order.indexOf("runs"));
    expect(r.runs).toBe(2);
    expect(db.run.findMany.mock.calls[0][0].where.startedAt.lt.toISOString()).toBe("2026-08-02T12:00:00.000Z");
  });

  it("stops at the batch limit and says more is waiting", async () => {
    db.screenshot.findMany.mockResolvedValue([{ id: "s1", blobUrl: "https://b/1.png" }]);
    const r = await runCleanup(NOW, { maxBatches: 3 });
    expect(r.screenshots).toBe(3);
    expect(r.partial).toBe(true);
  });

  it("skips file deletion without a Blob token (local development) but still removes the rows", async () => {
    delete process.env.BLOB_READ_WRITE_TOKEN;
    db.screenshot.findMany.mockResolvedValueOnce([{ id: "s1", blobUrl: "https://b/1.png" }]).mockResolvedValue([]);
    const r = await runCleanup(NOW);
    expect(del).not.toHaveBeenCalled();
    expect(r.screenshots).toBe(1);
  });

  it("expires stale pending jobs and removes expired sessions and tokens", async () => {
    db.job.updateMany.mockResolvedValue({ count: 2 });
    db.session.deleteMany.mockResolvedValue({ count: 3 });
    db.verificationToken.deleteMany.mockResolvedValue({ count: 4 });
    const r = await runCleanup(NOW);
    expect([r.expiredJobs, r.sessions, r.tokens]).toEqual([2, 3, 4]);
    expect(db.job.updateMany.mock.calls[0][0].where.createdAt.lt.toISOString()).toBe("2026-10-31T06:00:00.000Z");
  });
});
