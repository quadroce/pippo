"use server";

import { revalidatePath } from "next/cache";
import { prisma } from "@/lib/db";
import { sendMail } from "@/lib/mail";
import { requireAdmin } from "@/lib/session";
import { audit } from "@/lib/settings";
import { canChangeRole, canRemove, invitationEmail, parseInvite, type UserRow } from "@/lib/users";
import type { FormState } from "../actions";

async function allUsers(): Promise<UserRow[]> {
  const rows = await prisma.user.findMany({ select: { id: true, email: true, role: true, active: true } });
  return rows as UserRow[];
}

export async function inviteUser(_prev: FormState, formData: FormData): Promise<FormState> {
  const admin = await requireAdmin();
  const parsed = parseInvite(String(formData.get("email") ?? ""), String(formData.get("role") ?? ""));
  if (!parsed.ok) return { ok: false, message: parsed.error };

  const existing = await prisma.user.findUnique({ where: { email: parsed.email } });
  if (existing?.active) return { ok: false, message: "This email already has access" };

  // A removed user is restored with the new role; history (jobs, acknowledged alerts) stays attached.
  await prisma.user.upsert({
    where: { email: parsed.email },
    update: { active: true, role: parsed.role },
    create: { email: parsed.email, role: parsed.role },
  });
  await audit(admin.id, existing ? "user.restore" : "user.invite", { email: parsed.email, role: parsed.role });
  revalidatePath("/settings/users");

  const base = (process.env.AUTH_URL ?? "").replace(/\/$/, "");
  try {
    const mail = invitationEmail({ loginUrl: `${base}/login`, role: parsed.role, invitedBy: admin.email ?? "An admin" });
    await sendMail({ to: parsed.email, ...mail });
    return { ok: true, message: `Invitation sent to ${parsed.email}.` };
  } catch (e) {
    console.error("invitation email failed", e);
    return { ok: true, message: `${parsed.email} now has access, but the invitation email failed. Tell them to sign in at ${base}/login.` };
  }
}

export async function changeRole(_prev: FormState, formData: FormData): Promise<FormState> {
  const admin = await requireAdmin();
  const id = String(formData.get("userId") ?? "");
  const role = String(formData.get("role") ?? "");
  if (role !== "admin" && role !== "member") return { ok: false, message: "Pick a role" };

  const verdict = canChangeRole(await allUsers(), id, role);
  if (!verdict.ok) return { ok: false, message: verdict.error };
  const before = await prisma.user.findUnique({ where: { id }, select: { email: true, role: true } });
  await prisma.user.update({ where: { id }, data: { role } });
  await audit(admin.id, "user.role", { email: before?.email, from: before?.role, to: role });
  revalidatePath("/settings/users");
  return { ok: true, message: "Role updated." };
}

/** Removes access: the user keeps their history but can no longer sign in, and their sessions end now. */
export async function removeUser(_prev: FormState, formData: FormData): Promise<FormState> {
  const admin = await requireAdmin();
  const id = String(formData.get("userId") ?? "");
  const verdict = canRemove(await allUsers(), id, admin.id);
  if (!verdict.ok) return { ok: false, message: verdict.error };

  const user = await prisma.user.findUnique({ where: { id }, select: { email: true } });
  await prisma.$transaction([
    prisma.user.update({ where: { id }, data: { active: false } }),
    prisma.session.deleteMany({ where: { userId: id } }),
  ]);
  await audit(admin.id, "user.remove", { email: user?.email });
  revalidatePath("/settings/users");
  return { ok: true, message: "Access removed." };
}
