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
  headers.set("Content-Type", "application/json");
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
};
