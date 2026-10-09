import { signOut } from "@/auth";
import { requireUser } from "@/lib/session";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const user = await requireUser();

  async function logout() {
    "use server";
    await signOut({ redirectTo: "/login" });
  }

  return (
    <div className="min-h-screen">
      <header className="flex items-center justify-between border-b border-neutral-200 px-6 py-3">
        <span className="font-semibold">Pippo</span>
        <form action={logout} className="flex items-center gap-3 text-sm">
          <span>
            {user.email} ({user.role})
          </span>
          <button className="underline">Sign out</button>
        </form>
      </header>
      <main className="p-6">{children}</main>
    </div>
  );
}