"use server";

import { revalidatePath } from "next/cache";
import { prisma } from "@/lib/db";
import { requireAdmin } from "@/lib/session";
import { audit, getStoredThresholds, SETTING_REPORT_RECIPIENTS, SETTING_THRESHOLDS } from "@/lib/settings";
import { CHECK_CATALOG, parseEmails, parseThresholdInput } from "@/lib/thresholds";

export type FormState = { ok: boolean; message: string } | null;

export async function saveThreshold(_prev: FormState, formData: FormData): Promise<FormState> {
  const admin = await requireAdmin();
  const id = String(formData.get("checkId") ?? "");
  const def = CHECK_CATALOG.find((c) => c.id === id);
  if (!def) return { ok: false, message: "Unknown check" };

  const parsed = parseThresholdInput(def.unit, String(formData.get("warn") ?? ""), String(formData.get("critical") ?? ""));
  if (!parsed.ok) return { ok: false, message: parsed.error };

  const stored = await getStoredThresholds();
  const next = { ...stored, [id]: parsed.value } as object;
  await prisma.setting.upsert({
    where: { key: SETTING_THRESHOLDS },
    update: { value: next },
    create: { key: SETTING_THRESHOLDS, value: next },
  });
  await audit(admin.id, "threshold.update", { checkId: id, from: stored[id] ?? "default", to: parsed.value });
  revalidatePath("/settings");
  return { ok: true, message: "Saved. The agent picks it up at its next heartbeat." };
}

export async function resetThreshold(_prev: FormState, formData: FormData): Promise<FormState> {
  const admin = await requireAdmin();
  const id = String(formData.get("checkId") ?? "");
  if (!CHECK_CATALOG.some((c) => c.id === id)) return { ok: false, message: "Unknown check" };
  const stored = await getStoredThresholds();
  const { [id]: removed, ...rest } = stored;
  await prisma.setting.upsert({
    where: { key: SETTING_THRESHOLDS },
    update: { value: rest as object },
    create: { key: SETTING_THRESHOLDS, value: rest as object },
  });
  await audit(admin.id, "threshold.reset", { checkId: id, removed: removed ?? null });
  revalidatePath("/settings");
  return { ok: true, message: "Reset to the default." };
}

export async function saveActiveCountry(_prev: FormState, formData: FormData): Promise<FormState> {
  const admin = await requireAdmin();
  const code = String(formData.get("country") ?? "").toUpperCase();
  const country = await prisma.country.findUnique({ where: { code } });
  if (!country || !country.active) return { ok: false, message: "Pick an active country" };
  const before = await prisma.setting.findUnique({ where: { key: "activeCountry" } });
  await prisma.setting.upsert({
    where: { key: "activeCountry" },
    update: { value: code },
    create: { key: "activeCountry", value: code },
  });
  await audit(admin.id, "activeCountry.update", { from: before?.value ?? null, to: code });
  revalidatePath("/settings");
  return { ok: true, message: `Active country is now ${code}. Switch your VPN to ${country.name} before the next run.` };
}

export async function saveRecipients(_prev: FormState, formData: FormData): Promise<FormState> {
  const admin = await requireAdmin();
  const parsed = parseEmails(String(formData.get("recipients") ?? ""));
  if (!parsed.ok) return { ok: false, message: parsed.error };
  await prisma.setting.upsert({
    where: { key: SETTING_REPORT_RECIPIENTS },
    update: { value: parsed.emails },
    create: { key: SETTING_REPORT_RECIPIENTS, value: parsed.emails },
  });
  await audit(admin.id, "reportRecipients.update", { to: parsed.emails });
  revalidatePath("/settings");
  return { ok: true, message: parsed.emails.length ? `Saved ${parsed.emails.length} recipient(s).` : "No recipients: the report falls back to ADMIN_EMAIL." };
}
