"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useMemo, useState } from "react";
import type { FormState } from "../settings/actions";

type Action = (prev: FormState, formData: FormData) => Promise<FormState>;
type Country = { code: string; name: string };
type Channel = { id: string; name: string; countryCode: string };

/** Re-reads the server data every few seconds while a job is queued or running. */
export function AutoRefresh({ active, everyMs = 4000 }: { active: boolean; everyMs?: number }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => router.refresh(), everyMs);
    return () => clearInterval(t);
  }, [active, everyMs, router]);
  return null;
}

export function RunTestForm(props: {
  action: Action;
  countries: Country[];
  channels: Channel[];
  defaultCountry: string;
  agentCountry: string | null;
}) {
  const [state, formAction, pending] = useActionState(props.action, null);
  const [country, setCountry] = useState(props.defaultCountry);
  const [mode, setMode] = useState<"all" | "selected">("selected");
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const list = useMemo(
    () => props.channels.filter((c) => c.countryCode === country && c.name.toLowerCase().includes(search.trim().toLowerCase())),
    [props.channels, country, search],
  );
  const mismatch = props.agentCountry && props.agentCountry !== country;
  const field = "rounded border border-neutral-300 px-2 py-1 text-sm";

  function toggle(id: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <form action={formAction} className="space-y-4">
      <input type="hidden" name="channelIds" value={JSON.stringify(mode === "selected" ? [...picked] : [])} />

      <label className="block text-sm">
        Country{" "}
        <select
          name="country"
          value={country}
          onChange={(e) => {
            setCountry(e.target.value);
            setPicked(new Set());
          }}
          className={field}
        >
          {props.countries.map((c) => (
            <option key={c.code} value={c.code}>
              {c.code} · {c.name}
            </option>
          ))}
        </select>
      </label>
      {mismatch && (
        <p role="note" className="text-sm text-amber-800">
          The agent currently detects {props.agentCountry}, not {country}. The run will be blocked by the country pre-check unless the VPN is switched.
        </p>
      )}

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Channels</legend>
        <label className="mr-4 text-sm">
          <input type="radio" name="mode" value="selected" checked={mode === "selected"} onChange={() => setMode("selected")} /> Selected channels
        </label>
        <label className="text-sm">
          <input type="radio" name="mode" value="all" checked={mode === "all"} onChange={() => setMode("all")} /> Entire country
        </label>
        {mode === "selected" &&
          (props.channels.some((c) => c.countryCode === country) ? (
            <div className="space-y-2">
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search channels"
                aria-label="Search channels"
                className={`${field} w-64`}
              />
              <p className="text-xs text-neutral-600">{picked.size} selected</p>
              <ul className="max-h-64 overflow-auto rounded border border-neutral-200 p-2 text-sm">
                {list.map((c) => (
                  <li key={c.id}>
                    <label>
                      <input type="checkbox" checked={picked.has(c.id)} onChange={() => toggle(c.id)} /> {c.name}
                    </label>
                  </li>
                ))}
                {list.length === 0 && <li className="text-neutral-600">No channel matches.</li>}
              </ul>
            </div>
          ) : (
            <p className="text-sm text-neutral-600">No channels known for this country yet: run the entire country once first.</p>
          ))}
      </fieldset>

      <label className="block text-sm">
        Observation window{" "}
        <select name="windowSec" defaultValue="60" className={field}>
          <option value="30">30 s</option>
          <option value="60">60 s</option>
          <option value="120">120 s</option>
        </select>
      </label>
      <label className="block text-sm">
        <input type="checkbox" name="includeImages" /> Also run the images checks (home and EPG pages; adds a few minutes)
      </label>

      <button disabled={pending} className="rounded bg-black px-3 py-1 text-sm text-white disabled:opacity-50">
        Start test
      </button>
      {state && (
        <p role={state.ok ? "status" : "alert"} className={`text-sm ${state.ok ? "text-green-800" : "text-red-700"}`}>
          {state.message}
        </p>
      )}
    </form>
  );
}
