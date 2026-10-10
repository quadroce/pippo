"use server";

import { redirect } from "next/navigation";
import { prisma } from "@/lib/db";
import { requireUser } from "@/lib/session";
import { audit } from "@/lib/settings";

/** Queues a 60 s test on this channel (no images) and sends the user to the progress page. */
export async function runTestOnChannel(formData: FormData): Promise<void> {
  const user = await requireUser();
  const channelId = String(formData.get("channelId") ?? "");
  const channel = await prisma.channel.findUnique({ where: { id: channelId } });
  if (!channel) return;
  const country = await prisma.country.findUnique({ where: { code: channel.countryCode } });
  if (!country?.active) return;

  const job = await prisma.job.create({
    data: {
      countryCode: channel.countryCode,
      channelIds: [channel.id],
      options: { windowSec: 60, includeImages: false, total: 1 },
      createdBy: user.id,
    },
  });
  await audit(user.id, "job.create", { jobId: job.id, country: channel.countryCode, channels: 1, from: "channel page" });
  redirect("/run-test");
}
