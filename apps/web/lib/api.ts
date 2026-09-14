// Клиент API Personal AI Hub.
// Хранит токен в localStorage и оборачивает вызовы к собственному backend.
// Браузер никогда не обращается к внешним AI-провайдерам напрямую.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "pah_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  // Для FormData не задаём Content-Type (браузер добавит boundary сам).
  if (!(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (res.status === 204) return undefined as T;

  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = body?.error ?? {};
    throw new ApiError(
      err.code ?? "UNKNOWN",
      err.message ?? "Ошибка запроса",
      res.status,
    );
  }
  return body as T;
}

export interface User {
  id: string;
  username: string;
  is_admin: boolean;
}

export interface TokenResponse {
  access_token: string;
  user: User;
}

export interface Provider {
  id: string;
  provider_type: string;
  display_name: string;
  base_url: string;
  enabled: boolean;
  priority: number;
  currency: string;
  key_mask: string;
}

export interface Preset {
  provider_type: string;
  label: string;
  base_url: string;
  currency: string;
}

export interface Conversation {
  id: string;
  title: string;
  model_profile_id: string | null;
  system_instruction: string | null;
  archived: boolean;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: string;
  content: string;
  parent_id: string | null;
  status: string;
  model_snapshot: Record<string, unknown>;
  error_code: string | null;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface ModelProfile {
  id: string;
  external_model_id: string;
  display_name: string;
  capabilities: string[];
}

/** URL для EventSource (SSE) — токен передаётся query-параметром. */
export function eventSourceUrl(generationId: string): string {
  const token = getToken();
  return `${API_URL}/api/v1/generations/${generationId}/events?token=${encodeURIComponent(token ?? "")}`;
}

export interface UsageSummary {
  currency: string;
  today_cost: string;
  month_cost: string;
  today_input_tokens: number;
  today_output_tokens: number;
  month_input_tokens: number;
  month_output_tokens: number;
  daily_limit: string | null;
  monthly_limit: string | null;
  daily_remaining: string | null;
  monthly_remaining: string | null;
}

export interface UsageRecord {
  id: string;
  units_json: Record<string, number>;
  cost_amount: string;
  currency: string;
  cost_state: string;
  model_profile_id: string | null;
  occurred_at: string;
}

export interface Budget {
  currency: string;
  daily_limit: string | null;
  monthly_limit: string | null;
}

export interface Job {
  id: string;
  type: string;
  status: string;
  progress: number;
  error_code: string | null;
  error_detail_safe: string | null;
  attempts: number;
  submitted_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface KnowledgeBase {
  id: string;
  name: string;
  embedding_model_profile_id: string | null;
  embedding_version: string;
}

export interface KnowledgeDocument {
  id: string;
  title: string;
  status: string;
  error_code: string | null;
  asset_id: string;
}

export interface KnowledgeBaseDetail extends KnowledgeBase {
  documents: KnowledgeDocument[];
}

export interface Citation {
  chunk_id: string;
  document_id: string;
  document_title: string;
  text: string;
  page: number | null;
  score: number;
}

export interface QueryResult {
  sufficient: boolean;
  citations: Citation[];
}

export interface Asset {
  id: string;
  kind: string;
  status: string;
  original_name: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
}

export interface TableColumn {
  name: string;
  type: string;
}

export interface TablePreview {
  format: string;
  sheets: string[];
  columns: TableColumn[];
  sample_rows: unknown[][];
  row_count: number;
}

export interface TableQueryResult {
  columns: string[];
  rows: unknown[][];
}

export interface Price {
  id: string;
  model_profile_id: string;
  currency: string;
  input_per_million: string;
  output_per_million: string;
  effective_at: string;
}

export const api = {
  login: (username: string, password: string) =>
    request<TokenResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  bootstrap: (username: string, password: string) =>
    request<TokenResponse>("/api/v1/auth/bootstrap", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  me: () => request<User>("/api/v1/auth/me"),
  presets: () => request<Preset[]>("/api/v1/providers/presets"),
  providers: () => request<Provider[]>("/api/v1/providers"),
  createProvider: (input: {
    provider_type: string;
    display_name: string;
    base_url: string;
    api_key: string;
    currency: string;
  }) =>
    request<Provider>("/api/v1/providers", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  deleteProvider: (id: string) =>
    request<void>(`/api/v1/providers/${id}`, { method: "DELETE" }),
  testProvider: (id: string) =>
    request<{ ok: boolean; message: string; model_count: number }>(
      `/api/v1/providers/${id}/test`,
      { method: "POST" },
    ),
  syncModels: (id: string) =>
    request<unknown[]>(`/api/v1/providers/${id}/sync-models`, {
      method: "POST",
    }),
  models: () => request<ModelProfile[]>("/api/v1/models"),
  conversations: () => request<Conversation[]>("/api/v1/conversations"),
  createConversation: (input: { title?: string; model_profile_id?: string }) =>
    request<Conversation>("/api/v1/conversations", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  getConversation: (id: string) =>
    request<ConversationDetail>(`/api/v1/conversations/${id}`),
  sendMessage: (
    conversationId: string,
    content: string,
    modelProfileId?: string,
  ) =>
    request<{ generation_id: string }>(
      `/api/v1/conversations/${conversationId}/messages`,
      {
        method: "POST",
        body: JSON.stringify({
          content,
          model_profile_id: modelProfileId ?? null,
        }),
      },
    ),
  cancelGeneration: (id: string) =>
    request<{ status: string }>(`/api/v1/generations/${id}/cancel`, {
      method: "POST",
    }),
  usageSummary: () => request<UsageSummary>("/api/v1/usage/summary"),
  usageRecords: () => request<UsageRecord[]>("/api/v1/usage/records"),
  getBudget: () => request<Budget>("/api/v1/budgets"),
  updateBudget: (input: {
    daily_limit?: string | null;
    monthly_limit?: string | null;
    currency?: string;
  }) =>
    request<Budget>("/api/v1/budgets", {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  jobs: () => request<Job[]>("/api/v1/jobs"),
  retryJob: (id: string) =>
    request<Job>(`/api/v1/jobs/${id}/retry`, { method: "POST" }),
  cancelJob: (id: string) =>
    request<Job>(`/api/v1/jobs/${id}/cancel`, { method: "POST" }),
  knowledgeBases: () => request<KnowledgeBase[]>("/api/v1/knowledge-bases"),
  createKnowledgeBase: (name: string, embeddingModelProfileId: string) =>
    request<KnowledgeBase>("/api/v1/knowledge-bases", {
      method: "POST",
      body: JSON.stringify({
        name,
        embedding_model_profile_id: embeddingModelProfileId,
      }),
    }),
  getKnowledgeBase: (id: string) =>
    request<KnowledgeBaseDetail>(`/api/v1/knowledge-bases/${id}`),
  uploadDocument: (kbId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ document_id: string; job_id: string }>(
      `/api/v1/knowledge-bases/${kbId}/documents`,
      { method: "POST", body: form },
    );
  },
  queryKnowledgeBase: (kbId: string, text: string, topK = 5) =>
    request<QueryResult>(`/api/v1/knowledge-bases/${kbId}/query`, {
      method: "POST",
      body: JSON.stringify({ text, top_k: topK }),
    }),
  assets: () => request<Asset[]>("/api/v1/assets"),
  uploadAsset: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Asset>("/api/v1/assets/uploads", {
      method: "POST",
      body: form,
    });
  },
  tablePreview: (assetId: string) =>
    request<TablePreview>(`/api/v1/assets/${assetId}/table`),
  tableQuery: (assetId: string, sql: string) =>
    request<TableQueryResult>(`/api/v1/assets/${assetId}/table/query`, {
      method: "POST",
      body: JSON.stringify({ sql }),
    }),
  prices: (modelProfileId: string) =>
    request<Price[]>(
      `/api/v1/prices?model_profile_id=${encodeURIComponent(modelProfileId)}`,
    ),
  createPrice: (input: {
    model_profile_id: string;
    input_per_million: string;
    output_per_million: string;
    currency: string;
  }) =>
    request<Price>("/api/v1/prices", {
      method: "POST",
      body: JSON.stringify(input),
    }),
};
