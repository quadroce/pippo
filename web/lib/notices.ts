import { sendMail } from "@/lib/mail";
import { reportRecipients } from "@/lib/report-data";

/** Operational notice (docs/04 §4.3): the country pre-check failed and the run was blocked. Never throws. */
export async function sendBlockedNotice(opts: {
  runId: string;
  selected: string;
  detected: string | null;
}): Promise<void> {
  try {
    const to = await reportRecipients();
    if (to.length === 0) return;
    const base = (process.env.AUTH_URL ?? "").replace(/\/$/, "");
    const detected = opts.detected ?? "unknown";
    const text = [
      `The scheduled or on-demand run for ${opts.selected} was blocked by the country pre-check.`,
      `Selected country: ${opts.selected}`,
      `Detected country: ${detected}`,
      "",
      "Check that the VPN is connected to the right country and that the active country in Settings matches.",
      `${base}/runs/${opts.runId}`,
    ].join("\n");
    for (const recipient of to) {
      await sendMail({
        to: recipient,
        subject: `[Pippo] ${opts.selected} — Run blocked: country mismatch (detected ${detected})`,
        text,
        html: `<pre style="font-family:Arial,sans-serif">${text.replace(/&/g, "&amp;").replace(/</g, "&lt;")}</pre>`,
      });
    }
  } catch (e) {
    console.error("blocked notice failed", e);
  }
}
