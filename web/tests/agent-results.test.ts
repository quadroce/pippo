import { beforeEach, describe, expect, it, vi } from "vitest";

const RUN = "11111111-1111-4111-8111-111111111111";

const db = vi.hoisted(() => {
  const tx = {
    channel: { upsert: vi.fn() },
    channelResult: { create: vi.fn() },
  };
  return {
    tx,
    run: { findUnique: vi.fn(), update: vi.fn() },
    channelResult: { findMany: vi.fn() },
    $transaction: vi.fn(async (fn: (t: typeof tx) => unknown) => fn(tx)),
  };
});
vi.mock("@/lib/db", () => ({ prisma: db }));
const sendDailyReport = vi.hoisted(() => vi.fn());
vi.mock("@/lib/report-data", () => ({ sendDailyReport }));

import { POST as channels } from "@/app/api/agent/runs/[id]/channels/route";
import { POST as images } from "@/app/api/agent/runs/[id]/images/route";
import { POST as finish } from "@/app/api/agent/runs/[id]/finish/route";
import { channelStatus, countStatuses, worstStatus } from "@/lib/results";

const KEY = "test-key";
const call = (handler: typeof channels, body: unknown, id = RUN, key: string | null = KEY) =>
  handler(
    new Request("http://localhost/x", {
      method: "POST",
      headers: { "content-type": "application/json", ...(key ? { authorization: `Bearer ${key}` } : {}) },
      body: JSON.stringify(body),
    }),
    { params: Promise.resolve({ id }) },
  );

beforeEach(() => {
  vi.clearAllMocks();
  process.env.AGENT_API_KEY = KEY;
  db.run.findUnique.mockResolvedValue({ id: RUN, countryCode: "IT", status: "running" });
});

describe("status rules", () => {
  const check = (severity: "info" | "warning" | "critical", passed: boolean) => ({ checkId: "x", severity, passed });
  it("derives channel status from failed checks only", () => {
    expect(channelStatus([check("critical", true), check("info", false)])).toBe("ok");
    expect(channelStatus([check("warning", false)])).toBe("warning");
    expect(channelStatus([check("warning", false), check("critical", false)])).toBe("critical");
    expect(channelStatus([check("critical", false)], "crashed")).toBe("error");
  });
  it("counts and ranks statuses", () => {
    expect(countStatuses(["ok", "ok", "critical"])).toEqual({ ok: 2, warning: 0, critical: 1, error: 0 });
    expect(worstStatus([])).toBe("none");
    expect(worstStatus(["ok", "error", "warning"])).toBe("warning");
    expect(worstStatus(["ok", "critical"])).toBe("critical");
  });
});

describe("POST /runs/:id/channels", () => {
  const body = {
    channel: { slug: "32276", name: "Distretto di Polizia", category: "Series" },
    metrics: { "img.channel_logo_missing": true },
    checks: [{ checkId: "img.channel_logo_missing", severity: "warning", passed: false }],
  };

  it("creates the channel and the result with a derived status", async () => {
    db.tx.channelResult.create.mockResolvedValue({ id: "r1" });
    const res = await call(channels, body);
    expect(res.status).toBe(201);
    expect(await res.json()).toEqual({ id: "r1", channelId: "it-32276", status: "warning" });
    expect(db.tx.channel.upsert.mock.calls[0][0].create.id).toBe("it-32276");
    expect(db.tx.channelResult.create.mock.calls[0][0].data.checks.create).toHaveLength(1);
  });

  it("rejects bad auth, bad id, unknown run, closed run and invalid body", async () => {
    expect((await call(channels, body, RUN, "nope")).status).toBe(401);
    expect((await call(channels, body, "not-a-uuid")).status).toBe(400);
    db.run.findUnique.mockResolvedValueOnce(null);
    expect((await call(channels, body)).status).toBe(404);
    db.run.findUnique.mockResolvedValueOnce({ id: RUN, countryCode: "IT", status: "completed" });
    expect((await call(channels, body)).status).toBe(409);
    expect((await call(channels, { channel: { slug: "../x", name: "n" } })).status).toBe(400);
  });
});

describe("POST /runs/:id/images", () => {
  it("stores the page-level result on the run", async () => {
    const payload = {
      pages: { home: { url: "https://pluto.tv/it/home/", metrics: { "img.total_count": 100 } } },
      checks: [{ checkId: "img.broken_ratio", severity: "info", passed: true, scope: "home" }],
    };
    expect((await call(images as typeof channels, payload)).status).toBe(201);
    expect(db.run.update.mock.calls[0][0].data.images).toEqual(payload);
  });
});

describe("POST /runs/:id/finish", () => {
  it("closes the run and returns status counts", async () => {
    db.channelResult.findMany.mockResolvedValue([{ status: "ok" }, { status: "critical" }, { status: "ok" }]);
    db.run.update.mockResolvedValue({ id: RUN, status: "completed", trigger: "on_demand", log: null });
    const res = await call(finish as typeof channels, {});
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({
      id: RUN,
      status: "completed",
      counts: { ok: 2, warning: 0, critical: 1, error: 0 },
      reportSentTo: 0,
    });
    expect(db.run.update.mock.calls[0][0].data.finishedAt).toBeInstanceOf(Date);
    expect(sendDailyReport).not.toHaveBeenCalled(); // on-demand runs do not send the daily report
  });

  it("sends the daily report for a completed scheduled run", async () => {
    db.channelResult.findMany.mockResolvedValue([]);
    db.run.update.mockResolvedValue({ id: RUN, status: "completed", trigger: "scheduled", log: null });
    sendDailyReport.mockResolvedValue(2);
    const res = await call(finish as typeof channels, {});
    expect((await res.json()).reportSentTo).toBe(2);
    expect(sendDailyReport).toHaveBeenCalledWith(RUN);
  });

  it("still succeeds when the report email fails, and records it in the run log", async () => {
    db.channelResult.findMany.mockResolvedValue([]);
    db.run.update.mockResolvedValueOnce({ id: RUN, status: "completed", trigger: "scheduled", log: null });
    db.run.update.mockResolvedValueOnce({});
    sendDailyReport.mockRejectedValue(new Error("smtp down"));
    const res = await call(finish as typeof channels, {});
    expect(res.status).toBe(200);
    expect(db.run.update.mock.calls[1][0].data.log[0].msg).toContain("smtp down");
  });
});
