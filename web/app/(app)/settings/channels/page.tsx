import Link from "next/link";
import { RECOMMENDED_SAMPLE_MAX } from "@/lib/channel-flags";
import { prisma } from "@/lib/db";
import { getActiveCountry } from "@/lib/queries";
import { requireAdmin } from "@/lib/session";
import { subtitleState } from "@/lib/subtitles-view";
import { saveChannelFlags } from "./actions";
import { FlagsForm } from "./form";

export const dynamic = "force-dynamic";

const metricNum = (m: unknown, key: string): number | null => {
  if (!m || typeof m !== "object") return null;
  const v = (m as Record<string, unknown>)[key];
  return typeof v === "number" ? v : null;
};
const metricStr = (m: unknown, key: string): string | null => {
  if (!m || typeof m !== "object") return null;
  const v = (m as Record<string, unknown>)[key];
  return typeof v === "string" ? v : null;
};

/** What the last run learned about syncing this channel, to help choose where it can be measured. */
function syncSummary(metrics: unknown): string {
  const offset = metricNum(metrics, "sub.sync_offset_signed");
  if (offset !== null) return `${offset > 0 ? "+" : ""}${offset.toFixed(1)} s (${metricStr(metrics, "sub.sync_mode") ?? "?"})`;
  const note = metricStr(metrics, "sub.sync_note");
  if (note) return note.length > 70 ? note.slice(0, 67) + "…" : note;
  return "not measured";
}

export default async function ChannelFlagsPage({ searchParams }: { searchParams: Promise<{ country?: string }> }) {
  await requireAdmin();
  const sp = await searchParams;
  const countries = await prisma.country.findMany({ where: { active: true }, orderBy: { code: "asc" }, select: { code: true, name: true } });
  const code = (sp.country && /^[A-Za-z]{2}$/.test(sp.country) ? sp.country : await getActiveCountry())?.toUpperCase() ?? countries[0]?.code;

  const channels = code ? await prisma.channel.findMany({ where: { countryCode: code }, orderBy: { name: "asc" } }) : [];
  const latest = code
    ? await prisma.channelResult.findMany({
        where: { channel: { countryCode: code } },
        orderBy: { measuredAt: "desc" },
        distinct: ["channelId"],
        select: { channelId: true, metrics: true },
      })
    : [];
  const byChannel = new Map(latest.map((r) => [r.channelId, r.metrics]));

  const rows = channels.map((c) => ({
    id: c.id,
    name: c.name,
    category: c.category,
    isReference: c.isReference,
    subtitleSample: c.subtitleSample,
    subtitles: subtitleState(byChannel.get(c.id))?.label ?? "—",
    sync: syncSummary(byChannel.get(c.id)),
  }));

  return (
    <div className="space-y-6">
      <div>
        <Link href="/settings" className="text-sm underline">
          ← Settings
        </Link>
        <h1 className="text-2xl font-semibold">Channel flags</h1>
        <p className="mt-1 max-w-3xl text-sm text-neutral-600">
          <strong>Reference</strong> channels are the ones that matter most per country. <strong>Subtitle sample</strong> channels get their subtitle
          sync measured: the agent records their audio and transcribes it with Whisper on its own PC, so keep it to about {RECOMMENDED_SAMPLE_MAX} channels.
          Sync can only be measured where the spoken language and the subtitle language are the same and real cues arrive: look at the last-run
          columns before choosing. Live-news channels show a steady delay of several seconds that is normal for live captioning.
        </p>
      </div>

      <form method="get" className="flex items-center gap-2 text-sm">
        <label>
          Country{" "}
          <select name="country" defaultValue={code} className="rounded border border-neutral-300 px-2 py-1">
            {countries.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} · {c.name}
              </option>
            ))}
          </select>
        </label>
        <button className="rounded bg-black px-3 py-1 text-white">Show</button>
      </form>

      {!code || channels.length === 0 ? (
        <p className="text-neutral-600">No channels known for {code ?? "any country"} yet: they appear after the first full measurement.</p>
      ) : (
        <FlagsForm key={code} action={saveChannelFlags} country={code} rows={rows} recommendedMax={RECOMMENDED_SAMPLE_MAX} />
      )}
    </div>
  );
}
