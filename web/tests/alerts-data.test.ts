import { beforeEach, describe, expect, it, vi } from "vitest";

const db = vi.hoisted(() => ({
  alert: { findFirst: vi.fn(), count: vi.fn(), create: vi.fn(), findMany: vi.fn(), updateMany: vi.fn() },
  run: { findUnique: vi.fn() },
  channelResult: { count: vi.fn() },
}));
vi.mock("@/lib/db", () => ({ prisma: db }));
const sendMail = vi.hoisted(() => vi.fn());
vi.mock("@/lib/mail", () => ({ sendMail }));
vi.mock("@/lib/report-data", () => ({ reportRecipients: vi.fn(async () => ["ops@example.com"]) }));

import { acknowledgeGroup, finalizeAlerts, recordCriticalFindings } from "@/lib/alerts-data";

const result = (checks: object[]) => ({
  id: "res-1",
  runId: "run-1",
  channelId: "it-rai-news",
  channel: { name: "Rai News" },
  checks: checks as never,
});
const failed = (checkId: string, severity = "critical") => ({ id: `cr-${checkId}`, checkId, severity, passed: false, value: 1, threshold: 0, detail: null });

beforeEach(() => {
  vi.clearAllMocks();
  process.env.AUTH_URL = "https://pippo.example";
  db.alert.findFirst.mockResolvedValue(null);
  db.alert.count.mockResolvedValue(0);
  sendMail.mockResolvedValue(undefined);
});

describe("recordCriticalFindings", () => {
  it("emails a new critical finding immediately and stores the occurrence as sent", async () => {
    await recordCriticalFindings("IT", new Date(), result([failed("player.start_failed")]));
    expect(sendMail).toHaveBeenCalledTimes(1);
    expect(sendMail.mock.calls[0][0].subject).toBe("[Pippo] IT — CRITICAL: Rai News — Playback did not start");
    const data = db.alert.create.mock.calls[0][0].data;
    expect(data.emailState).toBe("sent");
    expect(data.emailedAt).toBeInstanceOf(Date);
  });

  it("ignores passed checks and non-critical severities", async () => {
    await recordCriticalFindings("IT", new Date(), result([{ ...failed("player.ttff", "warning") }, { ...failed("player.stall_ratio"), passed: true }]));
    expect(db.alert.create).not.toHaveBeenCalled();
    expect(sendMail).not.toHaveBeenCalled();
  });

  it("records but does not email a finding already emailed within 24 h", async () => {
    db.alert.findFirst.mockResolvedValue({ emailedAt: new Date(Date.now() - 3_600_000) });
    await recordCriticalFindings("IT", new Date(), result([failed("player.start_failed")]));
    expect(sendMail).not.toHaveBeenCalled();
    expect(db.alert.create.mock.calls[0][0].data).toMatchObject({ emailState: "deduped", emailedAt: null });
  });

  it("holds findings beyond the per-run cap", async () => {
    db.alert.count.mockResolvedValue(3);
    await recordCriticalFindings("IT", new Date(), result([failed("player.ttff")]));
    expect(sendMail).not.toHaveBeenCalled();
    expect(db.alert.create.mock.calls[0][0].data.emailState).toBe("held");
  });

  it("marks the alert failed when the email cannot be sent, without throwing", async () => {
    sendMail.mockRejectedValue(new Error("smtp down"));
    await expect(recordCriticalFindings("IT", new Date(), result([failed("player.start_failed")]))).resolves.toBeUndefined();
    expect(db.alert.create.mock.calls[0][0].data).toMatchObject({ emailState: "failed", emailedAt: null });
  });
});

describe("finalizeAlerts", () => {
  const alertRow = (n: number, checkId: string, emailState: string) => ({
    id: `a${n}`,
    emailState,
    checkResult: { checkId, value: 12000, threshold: 10000, channelResult: { channel: { name: `Channel ${n}` } } },
  });

  beforeEach(() => {
    db.run.findUnique.mockResolvedValue({ countryCode: "IT", startedAt: new Date() });
  });

  it("sends one country-wide email instead of individual ones when a check fails on over 30% of channels", async () => {
    db.channelResult.count.mockResolvedValue(20);
    db.alert.findMany.mockResolvedValue(Array.from({ length: 8 }, (_, i) => alertRow(i, "player.ttff", i < 3 ? "sent" : "held")));
    const out = await finalizeAlerts("run-1");
    expect(out.countryWide).toEqual(["player.ttff"]);
    expect(sendMail).toHaveBeenCalledTimes(1);
    expect(sendMail.mock.calls[0][0].subject).toBe("[Pippo] IT — CRITICAL: 8 of 20 channels — Time to first frame");
    expect(db.alert.updateMany.mock.calls[0][0].data.emailState).toBe("aggregated");
  });

  it("does not repeat a country-wide email sent in the last 24 h, but still marks the findings as covered", async () => {
    db.channelResult.count.mockResolvedValue(20);
    db.alert.findMany.mockResolvedValue(Array.from({ length: 8 }, (_, i) => alertRow(i, "player.ttff", "held")));
    db.alert.findFirst.mockResolvedValue({ id: "earlier" });
    const out = await finalizeAlerts("run-1");
    expect(out.countryWide).toEqual([]);
    expect(sendMail).not.toHaveBeenCalled();
    expect(db.alert.updateMany.mock.calls[0][0].data).toEqual({ emailState: "aggregated" });
  });

  it("sends held findings of non-aggregated checks as one digest", async () => {
    db.channelResult.count.mockResolvedValue(100);
    db.alert.findMany.mockResolvedValue([alertRow(1, "player.ttff", "held"), alertRow(2, "player.ttff", "held"), alertRow(3, "player.ttff", "sent")]);
    const out = await finalizeAlerts("run-1");
    expect(out).toEqual({ countryWide: [], digested: 2 });
    expect(sendMail.mock.calls[0][0].subject).toContain("2 more critical finding(s)");
    expect(db.alert.updateMany.mock.calls[0][0]).toMatchObject({ where: { id: { in: ["a1", "a2"] } }, data: { emailState: "sent" } });
  });

  it("does nothing for a clean run or an unknown run", async () => {
    db.channelResult.count.mockResolvedValue(50);
    db.alert.findMany.mockResolvedValue([]);
    expect(await finalizeAlerts("run-1")).toEqual({ countryWide: [], digested: 0 });
    db.run.findUnique.mockResolvedValue(null);
    expect(await finalizeAlerts("run-x")).toEqual({ countryWide: [], digested: 0 });
    expect(sendMail).not.toHaveBeenCalled();
  });
});

describe("acknowledgeGroup", () => {
  it("closes every open occurrence of the channel and check and records who", async () => {
    db.alert.updateMany.mockResolvedValue({ count: 4 });
    expect(await acknowledgeGroup("it-rai-news", "player.ttff", "user-1")).toBe(4);
    const arg = db.alert.updateMany.mock.calls[0][0];
    expect(arg.where).toEqual({ status: "open", checkResult: { checkId: "player.ttff", channelResult: { channelId: "it-rai-news" } } });
    expect(arg.data).toMatchObject({ status: "acknowledged", acknowledgedBy: "user-1" });
  });
});
