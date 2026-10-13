"use server";

import { revalidatePath } from "next/cache";
import { planFlagUpdate, savedMessage } from "@/lib/channel-flags";
import { prisma } from "@/lib/db";
import { requireAdmin } from "@/lib/session";
import { audit } from "@/lib/settings";
import type { FormState } from "../actions";

/** Saves the reference and subtitle-sample flags of every channel of one country in one go. */
export async function saveChannelFlags(_prev: FormState, formData: FormData): Promise<FormState> {
  const admin = await requireAdmin();
  const code = String(formData.get("country") ?? "").toUpperCase();
  const country = await prisma.country.findUnique({ where: { code } });
  if (!country) return { ok: false, message: "Unknown country" };

  const channels = await prisma.channel.findMany({
    where: { countryCode: code },
    select: { id: true, isReference: true, subtitleSample: true },
  });
  const plan = planFlagUpdate(channels, {
    referenceIds: formData.getAll("reference").map(String),
    sampleIds: formData.getAll("sample").map(String),
  });
  if (!plan.ok) return { ok: false, message: plan.error };

  const reference = new Set(plan.referenceIds);
  const sample = new Set(plan.sampleIds);
  await prisma.$transaction(
    channels.map((c) =>
      prisma.channel.update({ where: { id: c.id }, data: { isReference: reference.has(c.id), subtitleSample: sample.has(c.id) } }),
    ),
  );
  await audit(admin.id, "channelFlags.update", { country: code, ...plan.changes });
  revalidatePath("/settings/channels");
  return { ok: true, message: savedMessage(plan.changes, sample.size) };
}
