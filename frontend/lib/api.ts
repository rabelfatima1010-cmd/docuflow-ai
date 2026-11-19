// Empty = same origin (the backend serves this site). `npm run dev` sets it via .env.development.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

export const reviewHref = (id: number) => `/review/?id=${id}`;

// ---------- access code (public hosting: needed for uploads and review actions) ----------

const CODE_KEY = "docuflow.accessCode";

export function getAccessCode(): string {
  try {
    return localStorage.getItem(CODE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setAccessCode(code: string) {
  try {
    if (code) localStorage.setItem(CODE_KEY, code);
    else localStorage.removeItem(CODE_KEY);
  } catch {}
}

export interface Health {
  ok: boolean;
  extractor: string;
  model: string;
  queue: string;
  access_code_required?: boolean;
  remaining_today?: { site: number | null; visitor: number | null };
  max_pdf_pages?: number;
}
/** Hosted read-only demo: data comes from a static snapshot in /public/demo (scripts/export_demo.py). */
export const DEMO = process.env.NEXT_PUBLIC_DEMO_MODE === "1";
export const REPO_URL = "https://github.com/rabelfatima1010-cmd/docuflow-ai";

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
  const headers = new Headers(init?.headers);
  const code = getAccessCode();
  if (init?.method && init.method !== "GET" && code) headers.set("X-Access-Code", code);
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

// ---------- demo mode (static snapshot; review actions are simulated in memory) ----------

const demoOverrides = new Map<number, Partial<DocumentDetail>>();

async function demoJson<T>(file: string): Promise<T> {
  const res = await fetch(`/demo/${file}`, { cache: "force-cache" });
  if (!res.ok) throw new Error("Document not found in this demo");
  return res.json() as Promise<T>;
}

const demoApi = {
  health: () => demoJson<Health>("health.json"),
  checkAccessCode: async (_code: string) => false,
  categories: () => demoJson<string[]>("categories.json"),
  list: async (status?: string) => {
    const docs = (await demoJson<DocumentSummary[]>("documents.json")).map((d) => ({ ...d, ...demoOverrides.get(d.id) }));
    return status ? docs.filter((d) => status.split(",").includes(d.status)) : docs;
  },
  get: async (id: number) => ({ ...(await demoJson<DocumentDetail>(`documents/${id}.json`)), ...demoOverrides.get(id) }),
  fileUrl: (id: number) => `/demo/files/${id}.png`,
  upload: async (_files: File[]): Promise<UploadResult[]> => {
    throw new Error("Uploads are turned off in the live demo. Clone the repo to try your own invoices.");
  },
  approve: async (id: number, data: Invoice) => {
    demoOverrides.set(id, { status: "approved", approved_data: data, issues: [], vendor_name: data.vendor_name, total: data.total });
    return demoApi.get(id);
  },
  reject: async (id: number) => {
    demoOverrides.set(id, { status: "rejected" });
    return demoApi.get(id);
  },
  reprocess: async (_id: number): Promise<DocumentDetail> => {
    throw new Error("Re-running the AI is turned off in the live demo.");
  },
  stats: () => demoJson<Stats>("stats.json"),
  csvUrl: () => "/demo/export.csv",
};

const liveApi = {
  health: () => request<Health>("/api/health"),
  /** True when the server accepts this code. */
  checkAccessCode: async (code: string) => {
    const res = await fetch(`${API_URL}/api/access-code/check`, { method: "POST", headers: { "X-Access-Code": code } });
    return res.ok;
  },
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

export const api = DEMO ? demoApi : liveApi;

export function money(value: number | null | undefined, currency?: string | null) {
  if (value === null || value === undefined) return "-";
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: currency || "USD" }).format(value);
  } catch {
    return `${currency ?? ""} ${value.toFixed(2)}`;
  }
}
