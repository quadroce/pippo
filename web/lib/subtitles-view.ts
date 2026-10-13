/** Human wording for the agent's `sub.state` metric (see agent/pippo/probes/subtitles.py). */
const LABELS: Record<string, { label: string; hint: string }> = {
  no_subtitles: { label: "None declared", hint: "The channel declares no subtitle track." },
  not_enabled: { label: "Not tested", hint: "The subtitle menu could not be driven, so nothing was judged." },
  ok: { label: "Working", hint: "Cues arrived after the track was switched on." },
  placeholder_only: { label: "Track without content", hint: "A track is declared but the CDN serves only its placeholder: there are no subtitles for this programme." },
  loaded_empty: { label: "No cues yet", hint: "Real subtitle data arrived but held no cue in the observation window." },
  not_loaded: { label: "Failed to load", hint: "The track was switched on and no usable subtitle data arrived." },
};

export function subtitleState(metrics: unknown): { label: string; hint: string } | null {
  if (!metrics || typeof metrics !== "object") return null;
  const s = (metrics as Record<string, unknown>)["sub.state"];
  return typeof s === "string" ? (LABELS[s] ?? { label: s, hint: "" }) : null;
}
