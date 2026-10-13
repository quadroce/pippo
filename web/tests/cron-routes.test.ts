import { beforeEach, describe, expect, it, vi } from "vitest";

const db = vi.hoisted(() => ({
  setting: { findUnique: vi.fn(), upsert: vi.fn() },
  country: { findUnique: vi.fn() },
  run: { findFirst: vi.fn() },
  agent: { findUnique: vi.fn() },
}));
vi.mock("@/lib/db", () => ({ prisma: db }));
const runCleanup = vi.hoisted(() => vi.fn());
vi.mock("@/lib/retention-data", () => ({ runCleanup }));
const notices = vi.hoisted(() => ({ sendNoRunNotice: vi.fn(), sendAgentOfflineNotice: vi.fn() }));
vi.mock("@/lib/notices", () => notices);

import { GET as cleanup } from "@/app/api/cron/cleanup/route";
import { GET as health } from "@/app/api/cron/health/route";

const SECRET = "cron-secret";
const call = (handler: typeof cleanup, secret: string | null = SECRET) =>
  handler(new Request("http://localhost/api/cron/x", { headers: secret ? { authorization: `Bearer ${secret}` } : {} }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
  process.env.CRON_SECRET = SECRET;
});

describe("cron authentication", () => {
  it("refuses a missing or wrong secret and reports a server without one", async () => {
    expect((await call(cleanup, null)).status).toBe(401);
    expect((await call(cleanup, "nope")).status).toBe(401);
    expect((await call(health, "nope")).status).toBe(401);
    delete process.env.CRON_SECRET;
    expect((await call(cleanup)).status).toBe(503);
    expect(runCleanup).not.toHaveBeenCalled();
  });
});

describe("GET /api/cron/cleanup", () => {
  it("runs the cleanup and returns its summary", async () => {
    runCleanup.mockResolvedValue({ runs: 3, screenshots: 10, partial: false });
    const res = await call(cleanup);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ runs: 3, screenshots: 10, partial: false });
  });
});

describe("GET /api/cron/health", () => {
  const rome = { code: "IT", timezone: "Europe/Rome", runHour: "06:00" };

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-11T09:00:00Z")); // 11:00 in Rome, five hours after the scheduled time
    db.setting.findUnique.mockImplementation(async ({ where }: { where: { key: string } }) => (where.key === "activeCountry" ? { value: "IT" } : null));
    db.country.findUnique.mockResolvedValue(rome);
    db.agent.findUnique.mockResolvedValue({ lastHeartbeatAt: new Date("2026-10-11T08:55:00Z") });
    db.run.findFirst.mockResolvedValue({ startedAt: new Date("2026-10-10T04:00:00Z") });
    notices.sendNoRunNotice.mockResolvedValue(true);
    notices.sendAgentOfflineNotice.mockResolvedValue(true);
  });

  it("sends the no-run notice once for the day and remembers it", async () => {
    const body = await (await call(health)).json();
    expect(body).toMatchObject({ checked: true, country: "IT", noRunToday: true, sent: { noRun: true } });
    expect(notices.sendNoRunNotice).toHaveBeenCalledWith({ country: "IT", localDate: "2026-10-11", runHour: "06:00" });
    expect(db.setting.upsert.mock.calls[0][0].update.value).toEqual({ IT: "2026-10-11" });
  });

  it("does not send it twice on the same local day", async () => {
    db.setting.findUnique.mockImplementation(async ({ where }: { where: { key: string } }) =>
      where.key === "activeCountry" ? { value: "IT" } : where.key === "notice.noRun" ? { value: { IT: "2026-10-11" } } : null,
    );
    const body = await (await call(health)).json();
    expect(body.noRunToday).toBe(true);
    expect(notices.sendNoRunNotice).not.toHaveBeenCalled();
  });

  it("stays quiet when today's run started, even if it failed", async () => {
    db.run.findFirst.mockResolvedValue({ startedAt: new Date("2026-10-11T04:02:00Z") });
    const body = await (await call(health)).json();
    expect(body).toMatchObject({ noRunToday: false, agentOffline: false });
    expect(notices.sendNoRunNotice).not.toHaveBeenCalled();
  });

  it("does not mark the day as notified when the email could not be sent, so it is retried", async () => {
    notices.sendNoRunNotice.mockResolvedValue(false);
    const body = await (await call(health)).json();
    expect(body.sent.noRun).toBe(false);
    expect(db.setting.upsert).not.toHaveBeenCalled();
  });

  it("reports the agent offline inside the scheduled window", async () => {
    vi.setSystemTime(new Date("2026-10-11T05:00:00Z")); // 07:00 in Rome
    db.agent.findUnique.mockResolvedValue({ lastHeartbeatAt: new Date("2026-10-11T00:30:00Z") });
    db.run.findFirst.mockResolvedValue(null);
    const body = await (await call(health)).json();
    expect(body).toMatchObject({ agentOffline: true, noRunToday: false });
    expect(notices.sendAgentOfflineNotice).toHaveBeenCalledTimes(1);
  });

  it("skips quietly when no country is active", async () => {
    db.setting.findUnique.mockResolvedValue(null);
    expect(await (await call(health)).json()).toEqual({ checked: false, reason: "no active country" });
  });
});
