"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ConfidenceBar, StatusBadge } from "@/components/StatusBadge";
import { api, money, type DocumentDetail, type Invoice, type LineItem } from "@/lib/api";

const num = (v: string): number | null => (v.trim() === "" ? null : Number(v));

export default function ReviewPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useRouter();
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [form, setForm] = useState<Invoice | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await api.get(id);
      setDoc(d);
      setForm((prev) => prev ?? d.approved_data ?? d.extraction?.data ?? null);
      return d;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, [id]);

  useEffect(() => {
    load();
    api.categories().then(setCategories).catch(() => {});
  }, [load]);

  // Poll while the document is being processed
  useEffect(() => {
    if (!doc || !["queued", "processing"].includes(doc.status)) return;
    const t = setInterval(async () => {
      const d = await load();
      if (d && !["queued", "processing"].includes(d.status)) setForm(d.approved_data ?? d.extraction?.data ?? null);
    }, 2000);
    return () => clearInterval(t);
  }, [doc, load]);

  const flagged = useMemo(() => new Set(doc?.issues.map((i) => i.field).filter(Boolean) as string[]), [doc]);

  const math = useMemo(() => {
    if (!form) return null;
    const items = form.line_items.reduce((s, li) => s + (Number(li.amount) || 0), 0);
    const expectedTotal = (form.subtotal ?? items) + (form.tax ?? 0);
    return { items, expectedTotal, ok: Math.abs(expectedTotal - form.total) < 0.02 };
  }, [form]);

  function set<K extends keyof Invoice>(key: K, value: Invoice[K]) {
    setForm((f) => (f ? { ...f, [key]: value } : f));
  }
  function setItem(i: number, patch: Partial<LineItem>) {
    setForm((f) => (f ? { ...f, line_items: f.line_items.map((li, j) => (j === i ? { ...li, ...patch } : li)) } : f));
  }

  async function act(fn: () => Promise<unknown>, next?: string) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      if (next) router.push(next);
      else {
        setForm(null);
        await load();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function approve() {
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      await api.approve(id, form);
      // Go to the next document waiting for review, if any
      const queue = await api.list("needs_review");
      const next = queue.find((d) => d.id !== id);
      router.push(next ? `/review/${next.id}` : "/");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") approve();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!doc) return <div className="muted">{error ?? "Loading…"}</div>;

  const isPdf = doc.mime_type === "application/pdf";
  const processing = ["queued", "processing"].includes(doc.status);
  const cls = (field: string) => `input ${flagged.has(field) ? "flagged" : ""}`;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/" className="muted text-sm hover:underline">
          ← Inbox
        </Link>
        <h1 className="text-xl font-bold">
          #{doc.id} · {doc.filename}
        </h1>
        <StatusBadge status={doc.status} />
        {doc.extraction && (
          <span className="text-xs faint tabular">
            {doc.extraction.model} · {doc.extraction.attempts} pass{doc.extraction.attempts > 1 ? "es" : ""} ·{" "}
            {(doc.extraction.latency_ms / 1000).toFixed(1)}s · ${doc.extraction.cost_usd.toFixed(4)}
          </span>
        )}
      </div>

      {error && (
        <div className="rounded-lg p-3 text-sm" style={{ background: "var(--bad-bg)", color: "var(--bad)" }}>
          {error}
        </div>
      )}
      {doc.error && (
        <div className="rounded-lg p-3 text-sm" style={{ background: "var(--bad-bg)", color: "var(--bad)" }}>
          {doc.error}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card overflow-hidden lg:sticky lg:top-4 lg:self-start" style={{ height: "80vh" }}>
          {isPdf ? (
            <iframe src={api.fileUrl(id)} className="h-full w-full" title="Document" />
          ) : (
            <div className="h-full overflow-auto p-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={api.fileUrl(id)} alt="Uploaded document" className="w-full" />
            </div>
          )}
        </div>

        <div className="space-y-4">
          {processing && <div className="card p-6 text-center muted">The AI agent is reading this document…</div>}

          {doc.issues.length > 0 && (
            <div className="card p-4 space-y-2">
              <div className="font-semibold">Checks that need attention</div>
              {doc.issues.map((i) => (
                <div key={i.id} className="flex gap-2 text-sm">
                  <span
                    className="rounded px-1.5 text-xs font-semibold uppercase"
                    style={
                      i.severity === "error"
                        ? { background: "var(--bad-bg)", color: "var(--bad)" }
                        : { background: "var(--warn-bg)", color: "var(--warn)" }
                    }
                  >
                    {i.severity}
                  </span>
                  <span>{i.message}</span>
                </div>
              ))}
            </div>
          )}

          {form && (
            <div className="card p-4 space-y-4">
              <div className="flex items-center justify-between">
                <div className="font-semibold">Extracted data</div>
                <ConfidenceBar value={doc.confidence} />
              </div>

              <div className="grid grid-cols-2 gap-3 text-sm">
                <label className="col-span-2 space-y-1">
                  <span className="muted">Vendor</span>
                  <input className={cls("vendor_name")} value={form.vendor_name} onChange={(e) => set("vendor_name", e.target.value)} />
                </label>
                <label className="space-y-1">
                  <span className="muted">Invoice #</span>
                  <input className={cls("invoice_number")} value={form.invoice_number ?? ""} onChange={(e) => set("invoice_number", e.target.value || null)} />
                </label>
                <label className="space-y-1">
                  <span className="muted">Type</span>
                  <select className="input" value={form.doc_type} onChange={(e) => set("doc_type", e.target.value as Invoice["doc_type"])}>
                    <option value="invoice">Invoice</option>
                    <option value="receipt">Receipt</option>
                    <option value="other">Other</option>
                  </select>
                </label>
                <label className="space-y-1">
                  <span className="muted">Invoice date</span>
                  <input type="date" className={cls("invoice_date")} value={form.invoice_date ?? ""} onChange={(e) => set("invoice_date", e.target.value || null)} />
                </label>
                <label className="space-y-1">
                  <span className="muted">Due date</span>
                  <input type="date" className={cls("due_date")} value={form.due_date ?? ""} onChange={(e) => set("due_date", e.target.value || null)} />
                </label>
                <label className="space-y-1">
                  <span className="muted">Currency</span>
                  <input className={cls("currency")} maxLength={3} value={form.currency} onChange={(e) => set("currency", e.target.value.toUpperCase())} />
                </label>
                <label className="space-y-1">
                  <span className="muted">Category</span>
                  <select className="input" value={form.category} onChange={(e) => set("category", e.target.value)}>
                    {categories.map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                </label>
                <label className="col-span-2 space-y-1">
                  <span className="muted">Vendor tax ID</span>
                  <input className="input" value={form.vendor_tax_id ?? ""} onChange={(e) => set("vendor_tax_id", e.target.value || null)} />
                </label>
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between text-sm">
                  <span className="font-semibold">Line items</span>
                  <button
                    className="btn"
                    onClick={() => set("line_items", [...form.line_items, { description: "", quantity: null, unit_price: null, amount: 0 }])}
                  >
                    + Add line
                  </button>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="faint text-left">
                        <th className="pb-1 font-medium">Description</th>
                        <th className="pb-1 font-medium w-16">Qty</th>
                        <th className="pb-1 font-medium w-24">Unit</th>
                        <th className="pb-1 font-medium w-28">Amount</th>
                        <th className="w-8" />
                      </tr>
                    </thead>
                    <tbody>
                      {form.line_items.map((li, i) => (
                        <tr key={i}>
                          <td className="pr-1 py-0.5">
                            <input className={cls("line_items")} value={li.description} onChange={(e) => setItem(i, { description: e.target.value })} />
                          </td>
                          <td className="pr-1">
                            <input className="input tabular" value={li.quantity ?? ""} onChange={(e) => setItem(i, { quantity: num(e.target.value) })} />
                          </td>
                          <td className="pr-1">
                            <input className="input tabular" value={li.unit_price ?? ""} onChange={(e) => setItem(i, { unit_price: num(e.target.value) })} />
                          </td>
                          <td className="pr-1">
                            <input className={`${cls("line_items")} tabular`} value={li.amount} onChange={(e) => setItem(i, { amount: Number(e.target.value) || 0 })} />
                          </td>
                          <td>
                            <button
                              className="faint px-2"
                              aria-label="Remove line"
                              onClick={() => set("line_items", form.line_items.filter((_, j) => j !== i))}
                            >
                              ×
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3 text-sm">
                <label className="space-y-1">
                  <span className="muted">Subtotal</span>
                  <input className={`${cls("subtotal")} tabular`} value={form.subtotal ?? ""} onChange={(e) => set("subtotal", num(e.target.value))} />
                </label>
                <label className="space-y-1">
                  <span className="muted">Tax</span>
                  <input className={`${cls("tax")} tabular`} value={form.tax ?? ""} onChange={(e) => set("tax", num(e.target.value))} />
                </label>
                <label className="space-y-1">
                  <span className="muted">Total</span>
                  <input className={`${cls("total")} tabular font-semibold`} value={form.total} onChange={(e) => set("total", Number(e.target.value) || 0)} />
                </label>
              </div>

              {math && (
                <div className="text-xs tabular" style={{ color: math.ok ? "var(--good)" : "var(--bad)" }}>
                  {math.ok ? "✓" : "!"} Line items {money(math.items, form.currency)} · expected total{" "}
                  {money(math.expectedTotal, form.currency)}
                  {!math.ok && ` (entered ${money(form.total, form.currency)})`}
                </div>
              )}

              <div className="flex flex-wrap gap-2 pt-2">
                <button className="btn btn-primary" disabled={busy || processing} onClick={approve} title="Ctrl+Enter">
                  ✓ Approve {doc.status === "needs_review" ? "& next" : ""}
                </button>
                <button className="btn" disabled={busy || processing} onClick={() => act(() => api.reprocess(id))}>
                  ↻ Re-run AI
                </button>
                <button className="btn btn-danger ml-auto" disabled={busy} onClick={() => act(() => api.reject(id), "/")}>
                  Reject
                </button>
              </div>
            </div>
          )}

          {!form && !processing && doc.status === "failed" && (
            <div className="card p-4">
              <button className="btn" disabled={busy} onClick={() => act(() => api.reprocess(id))}>
                ↻ Try again
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
