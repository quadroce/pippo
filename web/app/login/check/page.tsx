export default function CheckEmailPage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center gap-3 p-8">
      <h1 className="text-2xl font-semibold">Check your email</h1>
      <p className="text-neutral-600">
        If the address is invited, a sign-in link is on its way. The link expires in 24 hours.
      </p>
    </main>
  );
}