import nodemailer from "nodemailer";

export const smtpConfigured = () =>
  Boolean(process.env.GMAIL_USER && process.env.GMAIL_APP_PASSWORD);

function transport() {
  return nodemailer.createTransport({
    host: "smtp.gmail.com",
    port: 465,
    secure: true,
    auth: { user: process.env.GMAIL_USER, pass: process.env.GMAIL_APP_PASSWORD },
  });
}

type Mail = { to: string; subject: string; text: string; html: string };

/**
 * Sends through Gmail SMTP when configured. Without SMTP credentials (local
 * development, or before the App Password is set) the message is printed to the
 * server console instead, so sign-in links stay usable.
 */
export async function sendMail(mail: Mail) {
  if (!smtpConfigured()) {
    if (process.env.NODE_ENV === "production") {
      throw new Error("SMTP is not configured (GMAIL_USER / GMAIL_APP_PASSWORD)");
    }
    console.log(`\n[mail:console] to=${mail.to}\nsubject=${mail.subject}\n${mail.text}\n`);
    return;
  }
  const from = process.env.EMAIL_FROM ?? process.env.GMAIL_USER;
  await transport().sendMail({ from, ...mail });
}