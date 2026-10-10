/** Rules for user management (docs/04-WEB-APP-SPEC.md §1, §3.8). Pure, so they can be unit-tested. */

export type Role = "admin" | "member";
export type UserRow = { id: string; email: string; role: Role; active: boolean };

export type Verdict = { ok: true } | { ok: false; error: string };

const activeAdmins = (users: UserRow[]) => users.filter((u) => u.active && u.role === "admin");

/** The system must always keep at least one active admin. */
export function canChangeRole(users: UserRow[], targetId: string, newRole: Role): Verdict {
  const target = users.find((u) => u.id === targetId);
  if (!target) return { ok: false, error: "User not found" };
  if (!target.active) return { ok: false, error: "This user has been removed; invite them again first" };
  if (target.role === newRole) return { ok: true };
  if (target.role === "admin" && newRole !== "admin" && activeAdmins(users).length <= 1) {
    return { ok: false, error: "Cannot demote the last admin" };
  }
  return { ok: true };
}

export function canRemove(users: UserRow[], targetId: string, actingUserId: string): Verdict {
  const target = users.find((u) => u.id === targetId);
  if (!target) return { ok: false, error: "User not found" };
  if (target.id === actingUserId) return { ok: false, error: "You cannot remove yourself" };
  if (target.role === "admin" && target.active && activeAdmins(users).length <= 1) {
    return { ok: false, error: "Cannot remove the last admin" };
  }
  return { ok: true };
}

export function parseInvite(emailRaw: string, roleRaw: string): { ok: true; email: string; role: Role } | { ok: false; error: string } {
  const email = emailRaw.trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return { ok: false, error: "Enter a valid email address" };
  if (roleRaw !== "admin" && roleRaw !== "member") return { ok: false, error: "Pick a role" };
  return { ok: true, email, role: roleRaw };
}

export function invitationEmail(opts: { loginUrl: string; role: Role; invitedBy: string }) {
  const text = [
    `${opts.invitedBy} invited you to Pippo as ${opts.role}.`,
    "",
    "Pippo monitors the quality of the Pluto TV web player.",
    `To sign in, open ${opts.loginUrl} and enter this email address: you will receive a one-time sign-in link.`,
  ].join("\n");
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const html = `<p>${esc(opts.invitedBy)} invited you to Pippo as <strong>${opts.role}</strong>.</p>
<p>Pippo monitors the quality of the Pluto TV web player.</p>
<p><a href="${esc(opts.loginUrl)}">Open Pippo</a> and enter this email address to receive a one-time sign-in link.</p>`;
  return { subject: "[Pippo] You have been invited to Pippo", text, html };
}
