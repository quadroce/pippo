import { beforeEach, describe, expect, it, vi } from "vitest";

const db = vi.hoisted(() => ({
  country: { findUnique: vi.fn() },
  thresholdOverride: { upsert: vi.fn(), deleteMany: vi.fn() },
  setting: { findUnique: vi.fn(), upsert: vi.fn() },
}));
vi.mock("@/lib/db", () => ({ prisma: db }));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
const requireAdmin = vi.hoisted(() => vi.fn());
vi.mock("@/lib/session", () => ({ requireAdmin }));
const audit = vi.hoisted(() => vi.fn());
vi.mock("@/lib/settings", async () => ({
  audit,
  SETTING_THRESHOLDS: "thresholds.global",
  SETTING_REPORT_RECIPIENTS: "email.reportRecipients",
  getStoredThresholds: vi.fn(async () => ({})),
}));

import { resetThreshold, saveThreshold } from "@/app/(app)/settings/actions";

const form = (entries: Record<string, string>) => {
  const f = new FormData();
  for (const [k, v] of Object.entries(entries)) f.append(k, v);
  return f;
};

beforeEach(() => {
  vi.clearAllMocks();
  requireAdmin.mockResolvedValue({ id: "admin-1", role: "admin" });
  db.country.findUnique.mockImplementation(async ({ where }: { where: { code: string } }) => (where.code === "IT" ? { code: "IT" } : null));
});

describe("country threshold overrides", () => {
  it("saves an override for the country, not the global value", async () => {
    const res = await saveThreshold(null, form({ checkId: "player.ttff", warn: "8000", critical: "", scope: "it" }));
    expect(res?.ok).toBe(true);
    expect(db.thresholdOverride.upsert).toHaveBeenCalledWith({
      where: { countryCode_checkId: { countryCode: "IT", checkId: "player.ttff" } },
      update: { warn: 8000, critical: null },
      create: { countryCode: "IT", checkId: "player.ttff", warn: 8000, critical: null },
    });
    expect(db.setting.upsert).not.toHaveBeenCalled();
    expect(audit).toHaveBeenCalledWith("admin-1", "threshold.update", expect.objectContaining({ scope: "IT", checkId: "player.ttff" }));
  });

  it("still saves the global value when the scope is global or missing", async () => {
    await saveThreshold(null, form({ checkId: "player.ttff", warn: "5000", critical: "9000", scope: "global" }));
    expect(db.setting.upsert).toHaveBeenCalledTimes(1);
    expect(db.thresholdOverride.upsert).not.toHaveBeenCalled();
    await saveThreshold(null, form({ checkId: "player.ttff", warn: "5000", critical: "9000" }));
    expect(db.setting.upsert).toHaveBeenCalledTimes(2);
  });

  it("rejects unknown countries and invalid values before writing", async () => {
    expect((await saveThreshold(null, form({ checkId: "player.ttff", warn: "1", critical: "", scope: "ZZ" })))?.message).toBe("Unknown country");
    expect((await saveThreshold(null, form({ checkId: "player.ttff", warn: "9", critical: "3", scope: "IT" })))?.ok).toBe(false);
    expect((await saveThreshold(null, form({ checkId: "nope", warn: "1", critical: "", scope: "IT" })))?.message).toBe("Unknown check");
    expect(db.thresholdOverride.upsert).not.toHaveBeenCalled();
  });

  it("resetting a country override removes its row so the country follows the global value", async () => {
    db.thresholdOverride.deleteMany.mockResolvedValue({ count: 1 });
    const res = await resetThreshold(null, form({ checkId: "player.ttff", scope: "IT" }));
    expect(res?.message).toContain("global value");
    expect(db.thresholdOverride.deleteMany).toHaveBeenCalledWith({ where: { countryCode: "IT", checkId: "player.ttff" } });
    expect(db.setting.upsert).not.toHaveBeenCalled();
  });

  it("is admin only", async () => {
    requireAdmin.mockRejectedValue(new Error("redirect"));
    await expect(saveThreshold(null, form({ checkId: "player.ttff", warn: "1", critical: "", scope: "IT" }))).rejects.toThrow("redirect");
    expect(db.thresholdOverride.upsert).not.toHaveBeenCalled();
  });
});
