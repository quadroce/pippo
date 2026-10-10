"use server";

import { revalidatePath } from "next/cache";
import { prisma } from "@/lib/db";
import { parseJobInput, WINDOWS } from "@/lib/jobs";
import { requireUser } from "@/lib/session";
import { audit } from "@/lib/settings";
import type { FormState } from "../settings/actions";

/** Any signed-in member can launch a test; the job waits in the queue until the agent picks it up. */
export async function createJob(_prev: FormState, formData: FormData): Promise<FormState> {
  const user = await requireUser();

  const country = String(formData.get("country") ?? "").toUpperCase();
  let channelIds: string[] = [];
  try {
    const raw = JSON.parse(String(formData.get("channelIds") ?? "[]"));
    if (Array.isArray(raw)) channelIds = raw.filter((x): x is string => typeof x === "string");
  } catch {
    return { ok: false, message: "Could not read the channel selection" };
  }

  const windowSec = Number(formData.get("windowSec"));
  const known = await prisma.channel.findMany({ where: { countryCode: country }, select: { id: true } });
  const parsed = parseJobInput(
    {
      country,
      mode: String(formData.get("mode") ?? ""),
      channelIds,
      windowSec: (WINDOWS as readonly number[]).includes(windowSec) ? windowSec : 0,
      includeImages: formData.get("includeImages") === "on",
    },
    new Set(known.map((c) => c.id)),
  );
  if (!parsed.ok) return { ok: false, message: parsed.error };

  const countryRow = await prisma.country.findUnique({ where: { code: parsed.countryCode } });
  if (!countryRow?.active) return { ok: false, message: "Pick an active country" };

  const total = parsed.channelIds.length || known.length || null;
  const job = await prisma.job.create({
    data: {
      countryCode: parsed.countryCode,
      channelIds: parsed.channelIds,
      options: { ...parsed.options, total },
      createdBy: user.id,
    },
  });
  await audit(user.id, "job.create", { jobId: job.id, country: parsed.countryCode, channels: parsed.channelIds.length || "all" });
  revalidatePath("/run-test");
  return { ok: true, message: "Test queued. It starts as soon as the agent picks it up." };
}
