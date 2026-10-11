import { beforeEach, describe, expect, it, vi } from "vitest";

const RUN = "11111111-1111-4111-8111-111111111111";
const db = vi.hoisted(() => ({
  run: { findUnique: vi.fn() },
  epgResult: { findFirst: vi.fn(), upsert: vi.fn() },
  setting: { findUnique: vi.fn() },
}));
vi.mock("@/lib/db", () => ({ prisma: db }));

import { POST as epg } from "@/app/api/agent/runs/[id]/epg/route";
import { channelCountDropCheck } from "@/lib/epg";

const KEY = "test-key";
const post = (body: unknown, key: string | null = KEY) =>
  epg(
    new Request("http://localhost/x", {
      method: "POST",
      headers: { "content-type": "application/json", ...(key ? { authorization: `Bearer ${key}` } : {}) },
      body: JSON.stringify(body),
    }),
    { params: Promise.resolve({ id: RUN }) },
  );

const payload = (count: number) => ({
  metrics: { "epg.channel_count": count, "epg.coverage_hours": 12 },
  checks: [{ checkId: "epg.coverage_hours", severity: "info", passed: true, value: 12, threshold: 6 }],
  issues: [{ channel: "Rai News", type: "gap", from: 1, to: 2, detail: "90 s" }],
});

beforeEach(() => {
  vi.clearAllMocks();
  process.env.AGENT_API_KEY = KEY;
  db.run.findUnique.mockResolvedValue({ id: RUN, countryCode: "IT", status: "running", startedAt: new Date() });
  db.setting.findUnique.mockResolvedValue(null);
  db.epgResult.findFirst.mockResolvedValue(null);
});

describe("channelCountDropCheck", () => {
  it("flags a drop above the share and ignores small or missing baselines", () => {
    expect(channelCountDropCheck(100, 85, 0.1)).toMatchObject({ severity: "critical", passed: false, value: 0.15 });
    expect(channelCountDropCheck(100, 91, 0.1)).toMatchObject({ severity: "info", passed: true });
    expect(channelCountDropCheck(100, 130, 0.1)).toMatchObject({ passed: true, value: 0 }); // growth is not a drop
    expect(channelCountDropCheck(5, 0, 0.1)).toBeNull(); // too few channels to compare
    expect(channelCountDropCheck(null, 100, 0.1)).toBeNull();
  });
});

describe("POST /runs/:id/epg", () => {
  it("stores the result and adds the count-drop check against the previous run", async () => {
    db.epgResult.findFirst.mockResolvedValue({ metrics: { "epg.channel_count": 127 } });
    const res = await post(payload(100));
    expect(res.status).toBe(201);
    const data = db.epgResult.upsert.mock.calls[0][0].create;
    expect(data.runId).toBe(RUN);
    const drop = data.checks.find((c: { checkId: string }) => c.checkId === "epg.channel_count_drop");
    expect(drop).toMatchObject({ severity: "critical", passed: false });
  });

  it("stores the result unchanged when there is no previous run", async () => {
    await post(payload(100));
    expect(db.epgResult.upsert.mock.calls[0][0].create.checks).toHaveLength(1);
  });

  it("uses the critical share from the global thresholds", async () => {
    db.epgResult.findFirst.mockResolvedValue({ metrics: { "epg.channel_count": 127 } });
    db.setting.findUnique.mockResolvedValue({ value: { "epg.channel_count_drop": { warn: null, critical: 0.5 } } });
    await post(payload(100));
    const drop = db.epgResult.upsert.mock.calls[0][0].create.checks.find((c: { checkId: string }) => c.checkId === "epg.channel_count_drop");
    expect(drop.passed).toBe(true);
  });

  it("requires the key, a running run and a valid body", async () => {
    expect((await post(payload(1), "nope")).status).toBe(401);
    db.run.findUnique.mockResolvedValueOnce({ id: RUN, countryCode: "IT", status: "completed", startedAt: new Date() });
    expect((await post(payload(1))).status).toBe(409);
    expect((await post({ metrics: {} })).status).toBe(400);
  });
});
