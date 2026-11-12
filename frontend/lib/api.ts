export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Status =
  | "queued"
  | "processing"
  | "needs_review"
  | "approved"
  | "exported"
  | "rejected"
  | "failed";

export interface LineItem {
  description: string;
  quantity: number | null;
  unit_price: number | null;
  amount: number;
}

export interface Invoice {
  doc_type: "invoice" | "receipt" | "other";
  vendor_name: string;
  vendor_tax_id: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  due_date: string | null;
  currency: string;
  subtotal: number | null;
  tax: number | null;
  total: number;
  line_items: LineItem[];
  category: string;
  field_confidence: Record<string, number>;
}

export interface DocumentSummary {
  id: number;
  filename: string;
  source: string;
  status: Status;
  vendor_name: string | null;
  invoice_date: string | null;
  total: number | null;
  currency: string | null;
  category: string | null;
  confidence: number | null;
  error: string | null;
  created_at: string;
}

export interface Issue {
  id: number;
  rule: string;
  field: string | null;
  message: string;
  severity: "error" | "warning";
}

export interface DocumentDetail extends DocumentSummary {
  mime_type: string;
  extraction: {
    version: number;
    data: Invoice | null;
    confidence: number;
    model: string;
    attempts: number;
    cost_usd: number;
    latency_ms: number;
  } | null;
  approved_data: Invoice | null;
  issues: Issue[];
}

export interface UploadResult {
  id: number | null;
  filename: string;
  status: string;
  duplicate_of: number | null;
  error: string | null;
}

export interface Stats {
  counts: Record<string, number>;
  total_documents: number;
  approved_total: number;
  currencies: Record<string, number>;
  auto_approve_rate: number | null;
  avg_cost_usd: number;
  total_cost_usd: number;
  avg_latency_ms: number;
  spend_by_month: { month: string; total: number }[];
  spend_by_category: { name: string; total: number }[];
  top_vendors: { name: string; total: number }[];
  anomalies: { id: number; vendor: string; total: number; vendor_avg: number }[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ ok: boolean; extractor: string; model: string; queue: string }>("/api/health"),
  categories: () => request<string[]>("/api/categories"),
  list: (status?: string) =>
    request<DocumentSummary[]>(`/api/documents${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  get: (id: number) => request<DocumentDetail>(`/api/documents/${id}`),
  fileUrl: (id: number) => `${API_URL}/api/documents/${id}/file`,
  upload: (files: File[]) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return request<UploadResult[]>("/api/documents", { method: "POST", body: form });
  },
  approve: (id: number, data: Invoice) =>
    request<DocumentDetail>(`/api/documents/${id}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data }),
    }),
  reject: (id: number) => request<DocumentDetail>(`/api/documents/${id}/reject`, { method: "POST" }),
  reprocess: (id: number) => request<DocumentDetail>(`/api/documents/${id}/reprocess`, { method: "POST" }),
  stats: () => request<Stats>("/api/stats"),
  csvUrl: () => `${API_URL}/api/export.csv`,
};

export function money(value: number | null | undefined, currency?: string | null) {
  if (value === null || value === undefined) return "-";
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: currency || "USD" }).format(value);
  } catch {
    return `${currency ?? ""} ${value.toFixed(2)}`;
  }
}
