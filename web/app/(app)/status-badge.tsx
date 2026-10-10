const STYLES: Record<string, string> = {
  ok: "bg-green-100 text-green-900",
  warning: "bg-amber-100 text-amber-900",
  critical: "bg-red-100 text-red-900",
  error: "bg-neutral-200 text-neutral-800",
  none: "bg-neutral-100 text-neutral-600",
  running: "bg-blue-100 text-blue-900",
  completed: "bg-green-100 text-green-900",
  blocked: "bg-red-100 text-red-900",
  failed: "bg-red-100 text-red-900",
};

const LABELS: Record<string, string> = { none: "No data" };

/** Status is always shown as a text label, never by color alone. */
export function StatusBadge({ status }: { status: string }) {
  const label = LABELS[status] ?? status.charAt(0).toUpperCase() + status.slice(1);
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${STYLES[status] ?? STYLES.none}`}>{label}</span>
  );
}
