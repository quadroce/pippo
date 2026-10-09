import { beforeEach, describe, expect, it, vi } from "vitest";

const db = vi.hoisted(() => ({
  agent: { upsert: vi.fn() },
  setting: { findUnique: vi.fn() },
  country: { findUnique: vi.fn() },
  run: { create: vi.fn(), findUnique: vi.fn() },
}));
vi.mock("@/lib/db", () => ({ prisma: db }));
const put = vi.hoisted(() => vi.fn());
vi.mock("@vercel/blob", () => ({ put }));

import { POST as heartbeat } from "@/app/api/agent/heartbeat/route";
import { POST as createRun } from "@/app/api/agent/runs/route";
import { POST as upload } from "@/app/api/agent/upload/route";

const KEY = "test-key";
const url = (p: string) => `http://localhost/api/agent/${p}`;
const json = (p: string, body: unknown, key: string | null = KEY) =>
  new Request(url(p), {
    method: "POST",
    headers: { "content-type": "application/json", ...(key ? { authorization: `Bearer ${key}` } : {}) },
    body: JSON.stringify(body),
  });

beforeEach(() => {
  vi.clearAllMocks();
  process.env.AGENT_API_KEY = KEY;
});

describe("auth", () => {
  it("rejects missing and wrong keys", async () => {
    expect((await heartbeat(json("heartbeat", { agentVersion: "1" }, null))).status).toBe(401);
    expect((await heartbeat(json("heartbeat", { agentVersion: "1" }, "nope"))).status).toBe(401);
    expect(db.agent.upsert).not.toHaveBeenCalled();
  });

  it("returns 503 when the server has no key configured", async () => {
    delete process.env.AGENT_API_KEY;
    expect((await heartbeat(json("heartbeat", { agentVersion: "1" }))).status).toBe(503);
  });
});

describe("heartbeat", () => {
  it("stores the heartbeat and returns the active country", async () => {
    db.setting.findUnique.mockImplementation(async ({ where }: { where: { key: string } }) =>
      where.key === "activeCountry" ? { value: "IT" } : null,
    );
    const res = await heartbeat(json("heartbeat", { agentVersion: "0.1.0", detectedCountry: "it" }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ activeCountry: "IT", pollIntervalSec: 10 });
    expect(db.agent.upsert.mock.calls[0][0].update.detectedCountry).toBe("IT");
  });

  it("rejects an invalid body", async () => {
    expect((await heartbeat(json("heartbeat", { detectedCountry: "ITA" }))).status).toBe(400);
  });
});

describe("runs", () => {
  const body = { countryCode: "IT", trigger: "scheduled", detectedCountry: "IT", agentVersion: "0.1.0" };

  it("creates a running run when countries match", async () => {
    db.country.findUnique.mockResolvedValue({ code: "IT" });
    db.run.create.mockResolvedValue({ id: "11111111-1111-4111-8111-111111111111", status: "running" });
    const res = await createRun(json("runs", body));
    expect(res.status).toBe(201);
    expect(db.run.create.mock.calls[0][0].data.status).toBe("running");
  });

  it("records a blocked run on country mismatch", async () => {
    db.country.findUnique.mockResolvedValue({ code: "IT" });
    db.run.create.mockResolvedValue({ id: "11111111-1111-4111-8111-111111111111", status: "blocked" });
    await createRun(json("runs", { ...body, detectedCountry: "FR" }));
    expect(db.run.create.mock.calls[0][0].data.status).toBe("blocked");
  });

  it("rejects unknown countries", async () => {
    db.country.findUnique.mockResolvedValue(null);
    expect((await createRun(json("runs", body))).status).toBe(422);
  });
});

describe("upload", () => {
  const runId = "11111111-1111-4111-8111-111111111111";
  const req = (qs: string, type = "image/png", bytes = 10) =>
    new Request(`${url("upload")}?${qs}`, {
      method: "POST",
      headers: { "content-type": type, authorization: `Bearer ${KEY}` },
      body: new Uint8Array(bytes),
    });

  it("stores a screenshot privately", async () => {
    db.run.findUnique.mockResolvedValue({ id: runId });
    put.mockResolvedValue({ url: "https://blob/x.png", pathname: "runs/x.png" });
    const res = await upload(req(`runId=${runId}&kind=screenshot&name=a.png`));
    expect(res.status).toBe(201);
    expect(put.mock.calls[0][2].access).toBe("private");
  });

  it("rejects bad content type, bad name and unknown run", async () => {
    expect((await upload(req(`runId=${runId}&kind=raw&name=a.exe`, "application/x-msdownload"))).status).toBe(415);
    expect((await upload(req(`runId=${runId}&kind=raw&name=../a`))).status).toBe(400);
    db.run.findUnique.mockResolvedValue(null);
    expect((await upload(req(`runId=${runId}&kind=screenshot&name=a.png`))).status).toBe(404);
  });
});