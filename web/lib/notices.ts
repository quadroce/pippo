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

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

async function notify(subject: string, text: string): Promise<boolean> {
  try {
    const to = await reportRecipients();
    if (to.length === 0) return false;
    for (const recipient of to) await sendMail({ to: recipient, subject, text, html: `<pre style="font-family:Arial,sans-serif">${esc(text)}</pre>` });
    return true;
  } catch (e) {
    console.error("operational notice failed", e);
    return false;
  }
}

/** docs/04 section 4.3: no scheduled run reached the web app today. Never throws; returns whether it was sent. */
export async function sendNoRunNotice(opts: { country: string; localDate: string; runHour: string }): Promise<boolean> {
  const base = (process.env.AUTH_URL ?? "").replace(/\/$/, "");
  return notify(
    `[Pippo] ${opts.country} — CRITICAL: no scheduled run received today (${opts.localDate})`,
    [
      `No scheduled run for ${opts.country} started today (${opts.localDate}); it was due at ${opts.runHour} local time.`,
      "",
      "Check: is the PC on and not asleep? Is the agent service running (services.msc, Pippo Agent)? Is the VPN connected to the right country?",
      "If needed, start a full-country test from Run test.",
      `${base}/runs`,
    ].join("\n"),
  );
}

/** docs/04 section 4.3: the agent has been silent for more than two hours during the scheduled window. */
export async function sendAgentOfflineNotice(opts: { country: string; localDate: string; lastHeartbeat: Date | null }): Promise<boolean> {
  const base = (process.env.AUTH_URL ?? "").replace(/\/$/, "");
  const last = opts.lastHeartbeat ? `${opts.lastHeartbeat.toISOString().slice(0, 16).replace("T", " ")} UTC` : "never";
  return notify(
    `[Pippo] ${opts.country} — agent offline during the scheduled window (${opts.localDate})`,
    [
      `The agent has not sent a heartbeat for more than 2 hours and today's scheduled run for ${opts.country} has not started. Last heartbeat: ${last}.`,
      "",
      "Check the PC, the Pippo Agent service and the VPN. Common causes: PC asleep, VPN client blocking local traffic, wrong API_BASE_URL.",
      `${base}/`,
    ].join("\n"),
  );
}

/** docs/04 section 4.3: the pages changed and the run was aborted; discovery mode is the way to repair it. Never throws. */
export async function sendSelectorHealthNotice(opts: { runId: string; country: string; message: string }): Promise<boolean> {
  const base = (process.env.AUTH_URL ?? "").replace(/\/$/, "");
  return notify(
    `[Pippo] ${opts.country} — CRITICAL: selector health failed, run aborted`,
    [
      opts.message,
      "",
      "pluto.tv most likely changed its pages. On the agent PC run `python -m pippo discover --country " + opts.country + "`, update agent/pluto_profile.yaml, commit it and restart the service.",
      `${base}/runs/${opts.runId}`,
    ].join("\n"),
  );
}

