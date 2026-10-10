import NextAuth from "next-auth";
import Nodemailer from "next-auth/providers/nodemailer";
import { PrismaAdapter } from "@auth/prisma-adapter";
import { prisma } from "@/lib/db";
import { sendMail } from "@/lib/mail";

export const { handlers, auth, signIn, signOut } = NextAuth({
  adapter: PrismaAdapter(prisma),
  session: { strategy: "database" },
  pages: { signIn: "/login", verifyRequest: "/login/check" },
  providers: [
    Nodemailer({
      // Real delivery is handled by sendMail(); this only satisfies the provider config.
      server: "smtp://localhost",
      from: process.env.EMAIL_FROM,
      async sendVerificationRequest({ identifier, url }) {
        await sendMail({
          to: identifier,
          subject: "[Pippo] Sign in to Pippo",
          text: `Sign in to Pippo:\n${url}\n\nThe link expires in 24 hours. If you did not request it, ignore this email.`,
          html: `<p>Sign in to Pippo:</p><p><a href="${url}">Sign in</a></p><p>The link expires in 24 hours. If you did not request it, ignore this email.</p>`,
        });
      },
    }),
  ],
  callbacks: {
    // Only invited, still active users (rows in User created by the seed or by an admin) may sign in.
    async signIn({ user }) {
      if (!user.email) return false;
      const existing = await prisma.user.findUnique({ where: { email: user.email.toLowerCase() } });
      return Boolean(existing?.active);
    },
    async session({ session, user }) {
      session.user.id = user.id;
      session.user.role = (user as { role?: "admin" | "member" }).role ?? "member";
      return session;
    },
  },
});