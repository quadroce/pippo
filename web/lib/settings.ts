import { prisma } from "@/lib/db";
import { effectiveThresholds, type StoredThresholds } from "@/lib/thresholds";

export const SETTING_THRESHOLDS = "thresholds.global";
export const SETTING_REPORT_RECIPIENTS = "email.reportRecipients";

export async function getGlobalThresholds(): Promise<StoredThresholds> {
  const s = await prisma.setting.findUnique({ where: { key: SETTING_THRESHOLDS } });
  return effectiveThresholds(s?.value);
}

export async function getStoredThresholds(): Promise<Record<string, unknown>> {
  const s = await prisma.setting.findUnique({ where: { key: SETTING_THRESHOLDS } });
  return s?.value && typeof s.value === "object" ? (s.value as Record<string, unknown>) : {};
}

export async function audit(userId: string | null, action: string, detail: object) {
  await prisma.auditLog.create({ data: { userId, action, detail } });
}
