"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BarChartCard } from "@/components/BarChartCard";
import { api, money, reviewHref, type Stats } from "@/lib/api";

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card p-4">
      <div className="text-xs font-medium muted">{label}</div>
      <div className="mt-1 text-2xl font-bold tabular">{value}</div>
      {hint && <div className="mt-1 text-xs faint">{hint}</div>}
    </div>
  );
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monthLabel = (ym: string) => `${MONTHS[Number(ym.slice(5, 7)) - 1]} ${ym.slice(2, 4)}`;

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.stats().then(setStats).catch((e) => setError((e as Error).message));
  }, []);

  if (error) return <div style={{ color: "var(--bad)" }}>Cannot load stats: {error}</div>;
  if (!stats) return <div className="muted">Loading…</div>;

  const currencies = Object.keys(stats.currencies);
  const currency = currencies.length === 1 ? currencies[0] : undefined;
  const fmt = (v: number) =>
    currency ? money(v, currency).replace(/\.00$/, "") : v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  const needsReview = stats.counts["needs_review"] ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-sm muted">Spend and processing metrics from approved documents.</p>
        {currencies.length > 1 && (
          <p className="mt-1 text-xs" style={{ color: "var(--warn)" }}>
            ! Amounts mix {currencies.join(", ")} and are summed without conversion.
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Tile label="Approved spend" value={fmt(stats.approved_total)} hint={currency ?? "mixed currencies"} />
        <Tile label="Documents" value={String(stats.total_documents)} />
        <Tile
          label="Auto-approved"
          value={stats.auto_approve_rate === null ? "-" : `${Math.round(stats.auto_approve_rate * 100)}%`}
          hint="no human review needed"
        />
        <Tile label="Waiting for review" value={String(needsReview)} />
        <Tile label="Avg AI cost / doc" value={`$${stats.avg_cost_usd.toFixed(4)}`} hint={`$${stats.total_cost_usd.toFixed(2)} total`} />
        <Tile label="Avg processing time" value={`${(stats.avg_latency_ms / 1000).toFixed(1)}s`} />
      </div>

      <BarChartCard
        title="Spend by month"
        data={stats.spend_by_month.map((m) => ({ label: monthLabel(m.month), value: m.total }))}
        format={fmt}
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <BarChartCard
          title="Spend by category"
          horizontal
          data={stats.spend_by_category.map((c) => ({ label: c.name, value: c.total }))}
          format={fmt}
        />
        <BarChartCard
          title="Top vendors"
          horizontal
          data={stats.top_vendors.map((v) => ({ label: v.name, value: v.total }))}
          format={fmt}
        />
      </div>

      <div className="card p-4">
        <h2 className="mb-2 font-semibold">Unusual invoices</h2>
        {stats.anomalies.length === 0 ? (
          <p className="text-sm faint">Nothing unusual. Invoices over 2× a vendor&apos;s average show up here.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {stats.anomalies.map((a) => (
              <li key={a.id}>
                <span style={{ color: "var(--warn)" }}>!</span>{" "}
                <Link className="underline" href={reviewHref(a.id)}>
                  #{a.id}
                </Link>{" "}
                {a.vendor}: <b className="tabular">{fmt(a.total)}</b>{" "}
                <span className="muted">vs. usual {fmt(a.vendor_avg)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
