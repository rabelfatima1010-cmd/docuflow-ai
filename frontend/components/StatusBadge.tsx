import type { Status } from "@/lib/api";

const STYLES: Record<Status, { label: string; fg: string; bg: string; icon: string }> = {
  queued: { label: "Queued", fg: "var(--text-2)", bg: "var(--surface-2)", icon: "○" },
  processing: { label: "Processing", fg: "var(--info)", bg: "var(--info-bg)", icon: "◔" },
  needs_review: { label: "Needs review", fg: "var(--warn)", bg: "var(--warn-bg)", icon: "!" },
  approved: { label: "Approved", fg: "var(--good)", bg: "var(--good-bg)", icon: "✓" },
  exported: { label: "Exported", fg: "var(--good)", bg: "var(--good-bg)", icon: "↗" },
  rejected: { label: "Rejected", fg: "var(--text-3)", bg: "var(--surface-2)", icon: "×" },
  failed: { label: "Failed", fg: "var(--bad)", bg: "var(--bad-bg)", icon: "×" },
};

export function StatusBadge({ status }: { status: Status }) {
  const s = STYLES[status] ?? STYLES.queued;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap"
      style={{ color: s.fg, background: s.bg }}
    >
      <span aria-hidden>{s.icon}</span>
      {s.label}
    </span>
  );
}

export function ConfidenceBar({ value }: { value: number | null }) {
  if (value === null) return <span className="faint">-</span>;
  const pct = Math.round(value * 100);
  const color = value >= 0.9 ? "var(--good)" : value >= 0.6 ? "var(--warn)" : "var(--bad)";
  return (
    <span className="inline-flex items-center gap-2 tabular" title={`${pct}% confidence`}>
      <span className="h-1.5 w-14 overflow-hidden rounded-full" style={{ background: "var(--surface-2)" }}>
        <span className="block h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      </span>
      <span className="text-xs muted">{pct}%</span>
    </span>
  );
}
