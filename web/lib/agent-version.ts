/** Agent version handling for the Settings field and the Overview hint. Pure, unit-tested. */

export const SETTING_LATEST_AGENT_VERSION = "agent.latestVersion";

export function parseVersion(text: string): [number, number, number] | null {
  const m = /^\s*v?(\d+)\.(\d+)\.(\d+)\s*$/.exec(text);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}

export function isOlder(current: string | null | undefined, latest: string | null | undefined): boolean {
  const a = current ? parseVersion(current) : null;
  const b = latest ? parseVersion(latest) : null;
  if (!a || !b) return false;
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] < b[i];
  return false;
}

/** Empty clears the setting; anything else must look like 1.2.3. */
export function parseLatestVersionInput(raw: string): { ok: true; value: string | null } | { ok: false; error: string } {
  const s = raw.trim();
  if (s === "") return { ok: true, value: null };
  const v = parseVersion(s);
  return v ? { ok: true, value: v.join(".") } : { ok: false, error: "Enter a version such as 0.2.0, or leave it empty" };
}
