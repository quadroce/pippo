import { prisma } from "@/lib/db";
import { getActiveCountry } from "@/lib/queries";
import { requireAdmin } from "@/lib/session";
import { getGlobalThresholds, getStoredThresholds, SETTING_REPORT_RECIPIENTS } from "@/lib/settings";
import { CHECK_CATALOG, toDisplay, type Unit } from "@/lib/thresholds";
import { resetThreshold, saveActiveCountry, saveRecipients, saveThreshold } from "./actions";
import { SimpleForm, ThresholdRow } from "./forms";

export const dynamic = "force-dynamic";

const UNIT_LABEL: Record<Unit, string> = { ratio: "%", seconds: "s", count: "count" };

export default async function SettingsPage() {
  await requireAdmin();
  const [countries, active, effective, stored, recipientsSetting, audit] = await Promise.all([
    prisma.country.findMany({ where: { active: true }, orderBy: { code: "asc" } }),
    getActiveCountry(),
    getGlobalThresholds(),
    getStoredThresholds(),
    prisma.setting.findUnique({ where: { key: SETTING_REPORT_RECIPIENTS } }),
    prisma.auditLog.findMany({ orderBy: { createdAt: "desc" }, take: 20 }),
  ]);
  const recipients = Array.isArray(recipientsSetting?.value) ? (recipientsSetting.value as string[]) : [];

  return (
    <div className="space-y-10">
      <h1 className="text-2xl font-semibold">Settings</h1>

      <section aria-label="Active country" className="space-y-2">
        <h2 className="text-lg font-medium">Active country</h2>
        <p className="text-sm text-neutral-600">The country the agent measures next. Switch your VPN to match before the run.</p>
        <SimpleForm action={saveActiveCountry} button="Save">
          <label className="text-sm">
            Country{" "}
            <select name="country" defaultValue={active ?? ""} className="rounded border border-neutral-300 px-2 py-1">
              {countries.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.code} · {c.name}
                </option>
              ))}
            </select>
          </label>
        </SimpleForm>
      </section>

      <section aria-label="Thresholds" className="space-y-2">
        <h2 className="text-lg font-medium">Thresholds (global)</h2>
        <p className="text-sm text-neutral-600">
          A check fails at warning level above the first value and at critical level above the second. Leave a field empty to disable that
          level. Per-country overrides come later.
        </p>
        <table className="w-full text-left text-sm">
          <tbody>
            {CHECK_CATALOG.map((c) => {
              const e = effective[c.id];
              const d = c.defaults;
              return (
                <ThresholdRow
                  key={c.id}
                  checkId={c.id}
                  name={c.name}
                  description={c.description}
                  unitLabel={UNIT_LABEL[c.unit]}
                  warn={toDisplay(c.unit, e.warn)}
                  critical={toDisplay(c.unit, e.critical)}
                  isDefault={!(c.id in stored)}
                  defaultText={`warning ${toDisplay(c.unit, d.warn) || "off"}, critical ${toDisplay(c.unit, d.critical) || "off"} ${UNIT_LABEL[c.unit]}`}
                  save={saveThreshold}
                  reset={resetThreshold}
                />
              );
            })}
          </tbody>
        </table>
      </section>

      <section aria-label="Email" className="space-y-2">
        <h2 className="text-lg font-medium">Daily report recipients</h2>
        <p className="text-sm text-neutral-600">One address per line or separated by commas. Empty means the admin address is used.</p>
        <SimpleForm action={saveRecipients} button="Save">
          <textarea
            name="recipients"
            defaultValue={recipients.join("\n")}
            rows={4}
            aria-label="Recipients"
            className="w-full max-w-md rounded border border-neutral-300 px-2 py-1 text-sm"
          />
        </SimpleForm>
      </section>

      <section aria-label="Audit log" className="space-y-2">
        <h2 className="text-lg font-medium">Recent changes</h2>
        {audit.length === 0 ? (
          <p className="text-sm text-neutral-600">No changes yet.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {audit.map((a) => (
              <li key={a.id}>
                {a.createdAt.toISOString().slice(0, 16).replace("T", " ")} UTC — {a.action} <code className="text-xs">{JSON.stringify(a.detail)}</code>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
