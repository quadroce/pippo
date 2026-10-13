import { beforeEach, describe, expect, it, vi } from "vitest";

const db = vi.hoisted(() => ({
  country: { findUnique: vi.fn() },
  channel: { findMany: vi.fn(), update: vi.fn((arg: unknown) => arg) },
  $transaction: vi.fn(async (ops: unknown[]) => ops),
}));
vi.mock("@/lib/db", () => ({ prisma: db }));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
const requireAdmin = vi.hoisted(() => vi.fn());
vi.mock("@/lib/session", () => ({ requireAdmin }));
const audit = vi.hoisted(() => vi.fn());
vi.mock("@/lib/settings", () => ({ audit }));

import { saveChannelFlags } from "@/app/(app)/settings/channels/actions";

const form = (entries: [string, string][]) => {
  const f = new FormData();
  for (const [k, v] of entries) f.append(k, v);
  return f;
};

beforeEach(() => {
  vi.clearAllMocks();
  requireAdmin.mockResolvedValue({ id: "admin-1", role: "admin" });
  db.country.findUnique.mockResolvedValue({ code: "IT" });
  db.channel.findMany.mockResolvedValue([
    { id: "it-a", isReference: true, subtitleSample: false },
    { id: "it-b", isReference: false, subtitleSample: true },
  ]);
});

describe("saveChannelFlags", () => {
  it("updates every channel of the country in one transaction and audits the changes", async () => {
    const res = await saveChannelFlags(null, form([["country", "it"], ["reference", "it-a"], ["sample", "it-a"]]));
    expect(res).toMatchObject({ ok: true });
    expect(res?.message).toContain("Subtitle sample: 1 channel(s)");
    expect(db.$transaction).toHaveBeenCalledTimes(1);
    const updates = db.channel.update.mock.calls.map((c) => c[0]);
    expect(updates).toEqual([
      { where: { id: "it-a" }, data: { isReference: true, subtitleSample: true } },
      { where: { id: "it-b" }, data: { isReference: false, subtitleSample: false } },
    ]);
    expect(audit).toHaveBeenCalledWith("admin-1", "channelFlags.update", expect.objectContaining({ country: "IT", sampleAdded: ["it-a"], sampleRemoved: ["it-b"] }));
  });

  it("rejects foreign channels and unknown countries without touching anything", async () => {
    expect((await saveChannelFlags(null, form([["country", "IT"], ["sample", "fr-x"]])))?.ok).toBe(false);
    db.country.findUnique.mockResolvedValue(null);
    expect((await saveChannelFlags(null, form([["country", "ZZ"]])))?.message).toBe("Unknown country");
    expect(db.$transaction).not.toHaveBeenCalled();
    expect(audit).not.toHaveBeenCalled();
  });

  it("is admin only", async () => {
    requireAdmin.mockRejectedValue(new Error("redirect"));
    await expect(saveChannelFlags(null, form([["country", "IT"]]))).rejects.toThrow("redirect");
    expect(db.channel.findMany).not.toHaveBeenCalled();
  });
});
