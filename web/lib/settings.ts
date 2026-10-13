import { prisma } from "@/lib/db";
import { effectiveThresholds, layerThresholds, type StoredThresholds } from "@/lib/thresholds";

export const SETTING_THRESHOLDS = "thresholds.global";
export const SETTING_REPORT_RECIPIENTS = "email.reportRecipients";

export async function getGlobalThresholds(): Promise<StoredThresholds> {
  const s = await prisma.setting.findUnique({ where: { key: SETTING_THRESHOLDS } });
  return effectiveThresholds(s?.value);
}

/** What the agent grades with in a country: defaults, then global overrides, then the country's own. */
export async function getEffectiveThresholds(countryCode: string | null): Promise<StoredThresholds> {
  const s = await prisma.setting.findUnique({ where: { key: SETTING_THRESHOLDS } });
  if (!countryCode) return effectiveThresholds(s?.value);
  const rows = await prisma.thresholdOverride.findMany({ where: { countryCode }, select: { checkId: true, warn: true, critical: true } });
  return layerThresholds(s?.value, rows);
}

export async function getStoredThresholds(): Promise<Record<string, unknown>> {
  const s = await prisma.setting.findUnique({ where: { key: SETTING_THRESHOLDS } });
  return s?.value && typeof s.value === "object" ? (s.value as Record<string, unknown>) : {};
}

export async function audit(userId: string | null, action: string, detail: object) {
  await prisma.auditLog.create({ data: { userId, action, detail } });
}
