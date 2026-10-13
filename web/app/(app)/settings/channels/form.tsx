"use client";

import { useActionState, useMemo, useState } from "react";
import type { FormState } from "../actions";

type Row = {
  id: string;
  name: string;
  category: string | null;
  isReference: boolean;
  subtitleSample: boolean;
  subtitles: string;
  sync: string;
};

type Action = (prev: FormState, formData: FormData) => Promise<FormState>;

export function FlagsForm({ action, country, rows, recommendedMax }: { action: Action; country: string; rows: Row[]; recommendedMax: number }) {
  const [state, formAction, pending] = useActionState(action, null);
  const [search, setSearch] = useState("");
  const [sampleCount, setSampleCount] = useState(rows.filter((r) => r.subtitleSample).length);
  const needle = search.trim().toLowerCase();
  const visible = useMemo(() => new Set(rows.filter((r) => !needle || r.name.toLowerCase().includes(needle)).map((r) => r.id)), [rows, needle]);

  return (
    <form action={formAction} className="space-y-3">
      <input type="hidden" name="country" value={country} />
      <div className="flex flex-wrap items-center gap-4">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search channels"
          aria-label="Search channels"
          className="w-64 rounded border border-neutral-300 px-2 py-1 text-sm"
        />
        <p role="status" className={`text-sm ${sampleCount > recommendedMax ? "text-amber-800" : "text-neutral-600"}`}>
          Subtitle sample: {sampleCount} channel(s){sampleCount > recommendedMax ? ` — more than the recommended ${recommendedMax}, the daily run gets longer` : ""}
        </p>
      </div>

      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-neutral-300">
            <th className="py-2">Channel</th>
            <th>Category</th>
            <th>Reference</th>
            <th>Subtitle sample</th>
            <th>Subtitles (last run)</th>
            <th>Sync (last run)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} hidden={!visible.has(r.id)} className="border-b border-neutral-100">
              <td className="py-2">{r.name}</td>
              <td>{r.category ?? "—"}</td>
              <td>
                <input type="checkbox" name="reference" value={r.id} defaultChecked={r.isReference} aria-label={`${r.name}: reference channel`} />
              </td>
              <td>
                <input
                  type="checkbox"
                  name="sample"
                  value={r.id}
                  defaultChecked={r.subtitleSample}
                  aria-label={`${r.name}: subtitle sample`}
                  onChange={(e) => setSampleCount((n) => n + (e.target.checked ? 1 : -1))}
                />
              </td>
              <td>{r.subtitles}</td>
              <td>{r.sync}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <button disabled={pending} className="rounded bg-black px-3 py-1 text-sm text-white disabled:opacity-50">
        Save
      </button>
      {state && (
        <p role={state.ok ? "status" : "alert"} className={`text-sm ${state.ok ? "text-green-800" : "text-red-700"}`}>
          {state.message}
        </p>
      )}
    </form>
  );
}
