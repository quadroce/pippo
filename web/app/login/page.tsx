import { redirect } from "next/navigation";
import { auth, signIn } from "@/auth";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  if ((await auth())?.user) redirect("/");
  const { error } = await searchParams;

  async function login(formData: FormData) {
    "use server";
    const email = String(formData.get("email") ?? "").trim().toLowerCase();
    await signIn("nodemailer", { email, redirectTo: "/" });
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center gap-4 p-8">
      <h1 className="text-2xl font-semibold">Sign in to Pippo</h1>
      <form action={login} className="flex flex-col gap-3">
        <label htmlFor="email" className="text-sm font-medium">
          Email
        </label>
        <input
          id="email"
          name="email"
          type="email"
          required
          autoComplete="email"
          className="rounded border border-neutral-300 px-3 py-2"
        />
        <button className="rounded bg-black px-3 py-2 text-white">Send sign-in link</button>
      </form>
      {error && (
        <p role="alert" className="text-sm text-red-700">
          This email is not invited, or the link is no longer valid. Ask an admin for an invitation.
        </p>
      )}
    </main>
  );
}