"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ConfidenceBar, StatusBadge } from "@/components/StatusBadge";
import { api, DEMO, money, REPO_URL, type DocumentSummary, type UploadResult } from "@/lib/api";

const FILTERS = [
  { label: "All", value: "" },
  { label: "Needs review", value: "needs_review" },
  { label: "Processing", value: "queued,processing" },
  { label: "Approved", value: "approved,exported" },
  { label: "Failed", value: "failed" },
  { label: "Rejected", value: "rejected" },
];

export default function InboxPage() {
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [lastUpload, setLastUpload] = useState<UploadResult[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [health, setHealth] = useState<{ extractor: string; model: string; queue: string } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setDocs(await api.list(filter || undefined));
      setError(null);
    } catch (e) {
      setError(`Cannot reach the API (${(e as Error).message}). Is the backend running on port 8000?`);
    }
  }, [filter]);

  useEffect(() => {
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  async function upload(files: FileList | File[] | null) {
    if (!files || files.length === 0) return;
    setUploading(true);
    try {
      setLastUpload(await api.upload(Array.from(files)));
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  const reviewCount = docs.filter((d) => d.status === "needs_review").length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Inbox</h1>
          <p className="muted text-sm">
            Upload invoices or receipts. Clean documents are approved automatically; anything uncertain waits for you.
          </p>
        </div>
        {health && (
          <span className="text-xs faint">
            Extractor: <b>{health.model}</b> · Queue: {health.queue}
          </span>
        )}
      </div>

      {DEMO ? (
        <div className="card p-6 text-center text-sm">
          <div className="font-semibold">Uploads are turned off in this live demo</div>
          <div className="muted mt-1">
            Open any invoice below to see what the AI extracted, or check the ones flagged for review.{" "}
            To run it on your own invoices,{" "}
            <a className="underline" href={REPO_URL} target="_blank" rel="noreferrer">
              clone the repo
            </a>
            .
          </div>
        </div>
      ) : (
      <div
        className="card flex cursor-pointer flex-col items-center justify-center gap-2 border-dashed p-8 text-center"
        style={{ borderStyle: "dashed", borderWidth: 2, borderColor: dragOver ? "var(--accent)" : "var(--border)" }}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          upload(e.dataTransfer.files);
        }}
      >
        <div className="text-3xl" aria-hidden>
          ⇪
        </div>
        <div className="font-semibold">{uploading ? "Uploading…" : "Drop invoices here or click to browse"}</div>
        <div className="text-xs faint">PDF, PNG, JPG or WEBP · up to 20 MB each</div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.png,.jpg,.jpeg,.webp"
          className="hidden"
          onChange={(e) => upload(e.target.files)}
        />
      </div>
      )}

      {lastUpload.some((u) => u.status !== "queued") && (
        <div className="card p-3 text-sm space-y-1">
          {lastUpload
            .filter((u) => u.status !== "queued")
            .map((u, i) => (
              <div key={i}>
                <b>{u.filename}</b>:{" "}
                {u.status === "duplicate" ? (
                  <>
                    already uploaded as <Link className="underline" href={`/review/${u.duplicate_of}`}>#{u.duplicate_of}</Link>
                  </>
                ) : (
                  <span style={{ color: "var(--bad)" }}>{u.error ?? u.status}</span>
                )}
              </div>
            ))}
        </div>
      )}

      {error && (
        <div className="rounded-lg p-3 text-sm" style={{ background: "var(--bad-bg)", color: "var(--bad)" }}>
          {error}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            className="btn"
            style={filter === f.value ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}
            onClick={() => setFilter(f.value)}
          >
            {f.label}
            {f.value === "needs_review" && filter === "" && reviewCount > 0 && (
              <span className="rounded-full px-1.5 text-xs" style={{ background: "var(--warn-bg)", color: "var(--warn)" }}>
                {reviewCount}
              </span>
            )}
          </button>
        ))}
        <a className="btn ml-auto" href={api.csvUrl()}>
          Export CSV
        </a>
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left faint" style={{ borderBottom: "1px solid var(--border)" }}>
              <th className="px-4 py-3 font-medium">#</th>
              <th className="px-4 py-3 font-medium">File</th>
              <th className="px-4 py-3 font-medium">Vendor</th>
              <th className="px-4 py-3 font-medium">Date</th>
              <th className="px-4 py-3 font-medium text-right">Total</th>
              <th className="px-4 py-3 font-medium">Category</th>
              <th className="px-4 py-3 font-medium">Confidence</th>
              <th className="px-4 py-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {docs.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-10 text-center faint">
                  No documents yet. Upload one above, or run <code>python scripts/make_samples.py</code> for demo files.
                </td>
              </tr>
            )}
            {docs.map((d) => (
              <tr key={d.id} className="hover:brightness-95" style={{ borderTop: "1px solid var(--border)" }}>
                <td className="px-4 py-3 faint tabular">{d.id}</td>
                <td className="px-4 py-3">
                  <Link href={`/review/${d.id}`} className="font-medium hover:underline">
                    {d.filename}
                  </Link>
                  <div className="text-xs faint">{d.source}</div>
                </td>
                <td className="px-4 py-3">{d.vendor_name ?? <span className="faint">-</span>}</td>
                <td className="px-4 py-3 tabular">{d.invoice_date ?? <span className="faint">-</span>}</td>
                <td className="px-4 py-3 text-right tabular">{money(d.total, d.currency)}</td>
                <td className="px-4 py-3">{d.category ?? <span className="faint">-</span>}</td>
                <td className="px-4 py-3">
                  <ConfidenceBar value={d.confidence} />
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={d.status} />
                  {d.error && (
                    <div className="mt-1 max-w-56 truncate text-xs" style={{ color: "var(--bad)" }} title={d.error}>
                      {d.error}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
