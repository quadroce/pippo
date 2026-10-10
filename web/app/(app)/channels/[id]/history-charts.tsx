"use client";

import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export type Point = {
  label: string;
  ttff: number | null; // seconds
  stall: number | null; // percent
  black: number | null; // seconds
  frozen: number | null;
  silence: number | null;
};

function Chart({ title, data, lines, unit }: { title: string; data: Point[]; lines: { key: keyof Point; name: string; color: string }[]; unit: string }) {
  const has = data.some((p) => lines.some((l) => p[l.key] !== null));
  return (
    <figure className="rounded border border-neutral-200 p-3">
      <figcaption className="mb-2 text-sm font-medium">
        {title} ({unit})
      </figcaption>
      {has ? (
        <div style={{ width: "100%", height: 200 }} role="img" aria-label={`${title} over the last runs`}>
          <ResponsiveContainer>
            <LineChart data={data} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} width={40} />
              <Tooltip />
              {lines.length > 1 && <Legend />}
              {lines.map((l) => (
                <Line key={l.key} type="monotone" dataKey={l.key} name={l.name} stroke={l.color} dot={{ r: 2 }} connectNulls />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="text-sm text-neutral-600">No measurements yet.</p>
      )}
    </figure>
  );
}

export function HistoryCharts({ data }: { data: Point[] }) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Chart title="Time to first frame" unit="s" data={data} lines={[{ key: "ttff", name: "TTFF", color: "#2563eb" }]} />
      <Chart title="Stall ratio" unit="%" data={data} lines={[{ key: "stall", name: "Stall", color: "#d97706" }]} />
      <Chart
        title="Black, frozen and silent time"
        unit="s"
        data={data}
        lines={[
          { key: "black", name: "Black", color: "#111827" },
          { key: "frozen", name: "Frozen", color: "#0891b2" },
          { key: "silence", name: "Silence", color: "#7c3aed" },
        ]}
      />
    </div>
  );
}
