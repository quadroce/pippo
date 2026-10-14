"use server";

import { revalidatePath } from "next/cache";
import { prisma } from "@/lib/db";
import { requireAdmin } from "@/lib/session";
import { audit, getStoredThresholds, SETTING_REPORT_RECIPIENTS, SETTING_THRESHOLDS } from "@/lib/settings";
import { parseLatestVersionInput, SETTING_LATEST_AGENT_VERSION } from "@/lib/agent-version";
import { parseRetentionInput } from "@/lib/retention";
import { runCleanup, SETTING_RETENTION } from "@/lib/retention-data";
import { CHECK_CATALOG, parseEmails, parseThresholdInput } from "@/lib/thresholds";

export type FormState = { ok: boolean; message: string } | null;

/** "global" or the code of an existing country (the scope the threshold form is editing). */
async function resolveScope(formData: FormData): Promise<string> {
  const raw = String(formData.get("scope") ?? "global");
  if (raw === "global") return "global";
  const code = raw.toUpperCase();
  const country = /^[A-Z]{2}$/.test(code) ? await prisma.country.findUnique({ where: { code } }) : null;
  return country ? country.code : "invalid";
}

export async function saveThreshold(_prev: FormState, formData: FormData): Promise<FormState> {
  const admin = await requireAdmin();
  const id = String(formData.get("checkId") ?? "");
  const def = CHECK_CATALOG.find((c) => c.id === id);
  if (!def) return { ok: false, message: "Unknown check" };

  const parsed = parseThresholdInput(def.unit, String(formData.get("warn") ?? ""), String(formData.get("critical") ?? ""), def.lowerIsWorse);
  if (!parsed.ok) return { ok: false, message: parsed.error };

  const scope = await resolveScope(formData);
  if (scope === "invalid") return { ok: false, message: "Unknown country" };

  if (scope !== "global") {
    const row = { warn: parsed.value.warn, critical: parsed.value.critical };
    await prisma.thresholdOverride.upsert({
      where: { countryCode_checkId: { countryCode: scope, checkId: id } },
      update: row,
      create: { countryCode: scope, checkId: id, ...row },
    });
    await audit(admin.id, "threshold.update", { scope, checkId: id, to: parsed.value });
    revalidatePath("/settings");
    return { ok: true, message: `Saved for ${scope}. The agent picks it up at its next heartbeat while ${scope} is the active country.` };
  }

  const stored = await getStoredThresholds();
  const next = { ...stored, [id]: parsed.value } as object;
  await prisma.setting.upsert({
    where: { key: SETTING_THRESHOLDS },
    update: { value: next },
    create: { key: SETTING_THRESHOLDS, value: next },
  });
  await audit(admin.id, "threshold.update", { scope: "global", checkId: id, from: stored[id] ?? "default", to: parsed.value });
  revalidatePath("/settings");
  return { ok: true, message: "Saved. The agent picks it up at its next heartbeat." };
}

export async function resetThreshold(_prev: FormState, formData: FormData): Promise<FormState> {
  const admin = await requireAdmin();
  const id = String(formData.get("checkId") ?? "");
  if (!CHECK_CATALOG.some((c) => c.id === id)) return { ok: false, message: "Unknown check" };
  const scope = await resolveScope(formData);
  if (scope === "invalid") return { ok: false, message: "Unknown country" };
  if (scope !== "global") {
    const res = await prisma.thresholdOverride.deleteMany({ where: { countryCode: scope, checkId: id } });
    await audit(admin.id, "threshold.reset", { scope, checkId: id, removed: res.count > 0 });
    revalidatePath("/settings");
    return { ok: true, message: `${scope} follows the global value again.` };
  }
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

export async function saveRetention(_prev: FormState, formData: FormData): Promise<FormState> {
  const admin = await requireAdmin();
  const parsed = parseRetentionInput(String(formData.get("screenshotDays") ?? ""), String(formData.get("metricsDays") ?? ""));
  if (!parsed.ok) return { ok: false, message: parsed.error };
  await prisma.setting.upsert({
    where: { key: SETTING_RETENTION },
    update: { value: parsed.value },
    create: { key: SETTING_RETENTION, value: parsed.value },
  });
  await audit(admin.id, "retention.update", parsed.value);
  revalidatePath("/settings");
  return { ok: true, message: `Saved: screenshots ${parsed.value.screenshotDays} days, metrics ${parsed.value.metricsDays} days. The daily cleanup applies it.` };
}

export async function runCleanupNow(): Promise<FormState> {
  const admin = await requireAdmin();
  const r = await runCleanup();
  await audit(admin.id, "retention.runNow", { runs: r.runs, screenshots: r.screenshots, blobFailures: r.blobFailures });
  revalidatePath("/settings");
  const done = `Deleted ${r.runs} run(s), ${r.screenshots} screenshot(s), ${r.rawBuffers} raw buffer(s), ${r.epgScreenshots} guide picture(s).`;
  if (r.blobFailures) return { ok: false, message: `${done} The file store refused some deletions: the rows were kept and the next run retries them.` };
  return { ok: true, message: r.partial ? `${done} More is waiting: run it again.` : done };
}

export async function saveLatestAgentVersion(_prev: FormState, formData: FormData): Promise<FormState> {
  const admin = await requireAdmin();
  const parsed = parseLatestVersionInput(String(formData.get("version") ?? ""));
  if (!parsed.ok) return { ok: false, message: parsed.error };
  await prisma.setting.upsert({
    where: { key: SETTING_LATEST_AGENT_VERSION },
    update: { value: parsed.value as unknown as object },
    create: { key: SETTING_LATEST_AGENT_VERSION, value: parsed.value as unknown as object },
  });
  await audit(admin.id, "agent.latestVersion", { to: parsed.value });
  revalidatePath("/settings");
  revalidatePath("/");
  return { ok: true, message: parsed.value ? `Agents older than ${parsed.value} will say so in their log and on the Overview.` : "No version announced." };
}

