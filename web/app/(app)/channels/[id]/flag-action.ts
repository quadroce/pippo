"use server";

import { revalidatePath } from "next/cache";
import { prisma } from "@/lib/db";
import { requireAdmin } from "@/lib/session";
import { audit } from "@/lib/settings";

const FLAGS = ["isReference", "subtitleSample"] as const;

/** Admin shortcut on the channel page: switch one flag of one channel. */
export async function setChannelFlag(formData: FormData): Promise<void> {
  const admin = await requireAdmin();
  const id = String(formData.get("channelId") ?? "");
  const flag = String(formData.get("flag") ?? "") as (typeof FLAGS)[number];
  if (!FLAGS.includes(flag)) return;
  const value = formData.get("value") === "true";
  const channel = await prisma.channel.findUnique({ where: { id }, select: { id: true, [flag]: true } });
  if (!channel) return;
  await prisma.channel.update({ where: { id }, data: { [flag]: value } });
  await audit(admin.id, "channelFlag.update", { channelId: id, flag, from: (channel as Record<string, unknown>)[flag], to: value });
  revalidatePath(`/channels/${id}`);
  revalidatePath("/settings/channels");
}
