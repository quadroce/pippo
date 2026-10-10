"use server";

import { revalidatePath } from "next/cache";
import { acknowledgeGroup } from "@/lib/alerts-data";
import { requireUser } from "@/lib/session";
import { audit } from "@/lib/settings";

/** Any signed-in member can acknowledge. Acknowledging does not stop future alerts if the problem persists. */
export async function acknowledgeAlert(formData: FormData): Promise<void> {
  const user = await requireUser();
  const channelId = String(formData.get("channelId") ?? "");
  const checkId = String(formData.get("checkId") ?? "");
  if (!/^[\w.-]{1,120}$/.test(channelId) || !/^[\w.]{1,80}$/.test(checkId)) return;
  const closed = await acknowledgeGroup(channelId, checkId, user.id);
  if (closed > 0) await audit(user.id, "alert.acknowledge", { channelId, checkId, occurrences: closed });
  revalidatePath("/alerts");
}
