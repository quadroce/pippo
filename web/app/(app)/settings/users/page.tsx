import Link from "next/link";
import { prisma } from "@/lib/db";
import { requireAdmin } from "@/lib/session";
import { changeRole, inviteUser, removeUser } from "./actions";
import { InviteForm, RemoveForm, RoleForm } from "./forms";

export const dynamic = "force-dynamic";

export default async function UsersPage() {
  const me = await requireAdmin();
  const users = await prisma.user.findMany({ orderBy: { email: "asc" } });
  const active = users.filter((u) => u.active);
  const removed = users.filter((u) => !u.active);

  return (
    <div className="space-y-8">
      <div>
        <Link href="/settings" className="text-sm underline">
          ← Settings
        </Link>
        <h1 className="text-2xl font-semibold">Users</h1>
        <p className="text-sm text-neutral-600">
          Only invited emails can sign in (passwordless, with a one-time link). Admins manage settings and users; members can view everything
          and launch tests.
        </p>
      </div>

      <section aria-label="Invite" className="space-y-2">
        <h2 className="text-lg font-medium">Invite a user</h2>
        <InviteForm action={inviteUser} />
      </section>

      <section aria-label="Active users" className="space-y-2">
        <h2 className="text-lg font-medium">Users with access ({active.length})</h2>
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-neutral-300">
              <th className="py-2">Email</th>
              <th>Role</th>
              <th>Last sign-in verified</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {active.map((u) => (
              <tr key={u.id} className="border-b border-neutral-100 align-top">
                <td className="py-2">
                  {u.email}
                  {u.id === me.id ? " (you)" : ""}
                </td>
                <td>
                  <RoleForm userId={u.id} role={u.role} action={changeRole} />
                </td>
                <td>{u.emailVerified ? u.emailVerified.toISOString().slice(0, 10) : "never signed in"}</td>
                <td>{u.id === me.id ? null : <RemoveForm userId={u.id} email={u.email} action={removeUser} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {removed.length > 0 && (
        <section aria-label="Removed users" className="space-y-2">
          <h2 className="text-lg font-medium">Removed ({removed.length})</h2>
          <p className="text-sm text-neutral-600">They keep their history. Invite the same email again to restore access.</p>
          <ul className="text-sm">
            {removed.map((u) => (
              <li key={u.id}>{u.email}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
