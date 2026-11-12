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

/**
 * Приводит введённое пользователем число к формату с точкой.
 *
 * Русская локаль использует запятую как десятичный разделитель, поэтому
 * пользователь пишет «0,022». JSON и Decimal ожидают точку — без нормализации
 * запрос отклоняется (422). Пробелы, включая неразрывные, удаляются: их
 * используют как разделители тысяч.
 *
 * @param value Сырое значение из поля ввода.
 * @returns Строка с точкой либо пустая строка, если ввести нечего.
 */
export function normalizeDecimalInput(value: string): string {
  const cleaned = value
    .trim()
    .replace(/\u00a0/g, "")
    .replace(/\s/g, "");
  return cleaned.replace(/,/g, ".");
}

/**
 * Проверяет, что строка — неотрицательное десятичное число.
 *
 * @param value Значение после `normalizeDecimalInput`.
 * @returns true, если значение можно отправить на backend.
 */
export function isValidDecimal(value: string): boolean {
  return /^\d+(\.\d+)?$/.test(value);
}

/**
 * Выполняет fetch и превращает сетевой сбой в понятную ошибку.
 *
 * Без этого браузерный `TypeError: Failed to fetch` доходил до пользователя
 * как есть. Самый частый случай — несовпадение origin (приложение открыто по
 * `127.0.0.1`, а API разрешает `localhost`) или незапущенный API; сообщение
 * должно подсказывать, что проверить, а не показывать техническую строку.
 *
 * @param url Полный адрес запроса.
 * @param init Параметры запроса.
 * @returns Ответ сервера.
 * @throws ApiError С кодом `NETWORK_ERROR`, если запрос не выполнен.
 */
async function safeFetch(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch {
    throw new ApiError(
      "NETWORK_ERROR",
      "Не удалось связаться с API. Проверьте, что стек запущен, и откройте " +
        "приложение по тому же адресу, что указан в APP_BASE_URL " +
        "(localhost или 127.0.0.1 — для браузера это разные адреса).",
      0,
    );
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

  const res = await safeFetch(`${API_URL}${path}`, { ...init, headers });
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

/**
 * Запрашивает бинарный ответ (экспорт файла) с авторизацией.
 *
 * Отдельно от `request`, потому что ответ — не JSON, а файл: читаем его как
 * Blob и сохраняем через временную ссылку. Ошибки backend всё равно приходят
 * в JSON-формате, поэтому при неуспешном статусе разбираем тело как JSON.
 *
 * @param path Путь эндпоинта.
 * @param init Параметры запроса (метод, тело).
 * @returns Объект Blob с содержимым файла.
 * @throws ApiError Если backend вернул ошибку.
 */
async function requestBlob(
  path: string,
  init: RequestInit = {},
): Promise<Blob> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await safeFetch(`${API_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err = body?.error ?? {};
    throw new ApiError(
      err.code ?? "UNKNOWN",
      err.message ?? "Не удалось выполнить экспорт",
      res.status,
    );
  }
  return res.blob();
}

/**
 * Сохраняет Blob как файл, инициируя скачивание в браузере.
 *
 * @param blob Содержимое файла.
 * @param filename Имя файла для пользователя.
 * @returns Ничего; побочный эффект — скачивание файла.
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Освобождаем память: без revoke объект живёт до перезагрузки страницы.
  URL.revokeObjectURL(url);
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
  /** Провайдер объявлен локальным (Ollama/LM Studio) — нужен для local_only. */
  is_local: boolean;
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
  /** Режим защиты диалога (ADR-0007/0008). */
  protection_mode: string;
  /** Ревизия контекста: подготовка с другой ревизией отклоняется. */
  protection_revision: number;
  /** Теги для фильтрации в сайдбаре (ADR-0008). */
  tags: string[];
}

export interface Message {
  id: string;
  conversation_id: string;
  role: string;
  content: string;
  parent_id: string | null;
  status: string;
  model_snapshot: Record<string, unknown>;
  /** Снимок защиты: mode, preparation_id, sanitized, restored. */
  protection?: Record<string, unknown>;
  error_code: string | null;
}

/**
 * Найденная в тексте сущность (без исходного значения).
 *
 * Нужна панели подготовки: пользователь видит, что именно заменено и сколько
 * раз, но исходные значения остаются только в приватном preview.
 */
export interface ProtectionEntity {
  placeholder: string;
  category: string;
  occurrences: number;
}

/**
 * Результат подготовки защищённого запроса.
 *
 * `digest` и `revision` нужно вернуть в commit без изменений: сервер примет
 * только тот preview, который пользователь видел.
 */
export interface ProtectionPreview {
  preparation_id: string;
  mode: string;
  revision: number;
  digest: string;
  private_messages: string[];
  sanitized_messages: string[];
  sanitized_text: string;
  entities: ProtectionEntity[];
  expires_at: string | null;
  note: string;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface ModelProfile {
  id: string;
  external_model_id: string;
  display_name: string;
  capabilities: string[];
  /** Задана ли цена модели: без неё платный вызов не выполняется. */
  has_price: boolean;
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
  /** null — стоимость неизвестна (модель без цены), а не ноль. */
  cost_amount: string | null;
  currency: string;
  cost_state: string;
  model_profile_id: string | null;
  /**
   * Сообщение, к которому относится расход. Позволяет показать стоимость
   * конкретного ответа в чате, а не только суммарные траты.
   */
  message_id: string | null;
  provider_request_id: string | null;
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
  cancel_requested: boolean;
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
  answer: string | null;
  answer_skipped_reason: string | null;
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
  /** Тариф попадания в кэш (cache hit); null — отдельного тарифа нет. */
  cache_read_per_million: string | null;
  /** Тариф записи в кэш (Anthropic-style); null — не применяется. */
  cache_write_per_million: string | null;
  /** Откуда цена: manual | api | url. */
  source: string;
  /** Страница-источник, если цена взята с сайта провайдера. */
  source_url: string | null;
  effective_at: string;
}

/**
 * Кандидат на цену, найденный на странице тарифов провайдера.
 *
 * Значение требует проверки пользователем: провайдеры не дают
 * машинно-читаемого контракта на страницу тарифов.
 */
export interface PriceImportCandidate {
  field:
    | "input_per_million"
    | "output_per_million"
    | "cache_read_per_million"
    | "cache_write_per_million";
  value: string;
  snippet: string;
  confidence: number;
}

export interface PriceImportResult {
  source_url: string;
  candidates: PriceImportCandidate[];
  note: string;
  /** Способ получения значений: static | rendered | llm. */
  method: "static" | "rendered" | "llm";
  /** Модель, которой выполнялся LLM-разбор (только для method="llm"). */
  llm_model: string | null;
}

export interface FxRate {
  id: string;
  from_currency: string;
  to_currency: string;
  rate: string;
  source: string;
  fetched_at: string;
}

export const api = {
  /**
   * Возможности сервера, влияющие на состав элементов интерфейса.
   *
   * Нужны, чтобы не рендерить неработающие переключатели: например, опция
   * веб-поиска показывается только при `web_search: true`.
   *
   * @returns Флаги включённых на сервере возможностей.
   */
  capabilities: () =>
    request<{
      web_search: boolean;
      /** Защищённые режимы (ADR-0007): показывать переключатель только при enabled. */
      protection?: {
        enabled: boolean;
        modes: string[];
        default_mode: string;
        cloud_scan?: boolean;
      };
    }>("/api/v1/capabilities"),
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
  /**
   * Уточняет возможности модели вручную.
   *
   * Нужно, когда провайдер не рекламирует поддержку параметра в `/models`:
   * например, DeepSeek принимает `reasoning_effort`, но не перечисляет его.
   *
   * @param id Идентификатор профиля модели.
   * @param capabilities Полный набор объявляемых возможностей.
   * @returns Обновлённый профиль модели.
   */
  updateModelCapabilities: (id: string, capabilities: string[]) =>
    request<ModelProfile>(`/api/v1/models/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ capabilities }),
    }),
  conversations: (archived = false) =>
    request<Conversation[]>(`/api/v1/conversations?archived=${archived}`),
  createConversation: (input: { title?: string; model_profile_id?: string }) =>
    request<Conversation>("/api/v1/conversations", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  getConversation: (id: string) =>
    request<ConversationDetail>(`/api/v1/conversations/${id}`),
  /** Переименование, теги, архивирование и системная инструкция диалога. */
  updateConversation: (
    id: string,
    patch: {
      title?: string;
      tags?: string[];
      archived?: boolean;
      system_instruction?: string | null;
    },
  ) =>
    request<Conversation>(`/api/v1/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  deleteConversation: (id: string) =>
    request<void>(`/api/v1/conversations/${id}`, { method: "DELETE" }),
  /** Экспорт диалога в markdown или json (скачивание). */
  exportConversation: (id: string, format: "markdown" | "json" = "markdown") =>
    requestBlob(`/api/v1/conversations/${id}/export?fmt=${format}`),
  /** Локальное сканирование текста перед отправкой в облачном режиме. */
  scanProtection: (text: string) =>
    request<{
      categories: { category: string; count: number }[];
      has_secret: boolean;
    }>("/api/v1/protection/scan", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  sendMessage: (
    conversationId: string,
    content: string,
    modelProfileId?: string,
    reasoningDepth?: "low" | "medium" | "high",
    webSearch?: boolean,
    /** Подтверждённая подготовка: обязательна в режиме protected_hybrid. */
    preparationId?: string,
    /** Пользователь подтвердил отправку после предупреждения облака. */
    cloudScanAcknowledged?: boolean,
    /** Температура генерации (0..2). */
    temperature?: number,
    /** Лимит выходных токенов. */
    maxTokens?: number,
  ) =>
    request<{ generation_id: string }>(
      `/api/v1/conversations/${conversationId}/messages`,
      {
        method: "POST",
        body: JSON.stringify({
          content,
          model_profile_id: modelProfileId ?? null,
          reasoning_depth: reasoningDepth ?? null,
          web_search: webSearch ?? false,
          preparation_id: preparationId ?? null,
          cloud_scan_acknowledged: cloudScanAcknowledged ?? false,
          temperature: temperature ?? null,
          max_tokens: maxTokens ?? null,
        }),
      },
    ),
  /** Редактирует сообщение пользователя; сервер обрезает старую ветку после него. */
  editMessage: (conversationId: string, messageId: string, content: string) =>
    request<Message>(
      `/api/v1/conversations/${conversationId}/messages/${messageId}`,
      {
        method: "PATCH",
        body: JSON.stringify({ content }),
      },
    ),
  /** Перегенерирует ответ ассистента для существующего сообщения пользователя. */
  regenerateMessage: (conversationId: string, userMessageId: string) =>
    request<{ generation_id: string }>(
      `/api/v1/conversations/${conversationId}/messages/${userMessageId}/regenerate`,
      { method: "POST", body: JSON.stringify({}) },
    ),
  /** Переключает режим защиты диалога; смена режима увеличивает ревизию. */
  setProtectionMode: (conversationId: string, mode: string) =>
    request<Conversation>(`/api/v1/conversations/${conversationId}`, {
      method: "PATCH",
      body: JSON.stringify({ protection_mode: mode }),
    }),
  /** Готовит sanitized-контекст и показывает preview (ничего не отправляет). */
  prepareProtection: (
    conversationId: string,
    text: string,
    modelProfileId?: string,
  ) =>
    request<ProtectionPreview>(
      `/api/v1/protection/conversations/${conversationId}/prepare`,
      {
        method: "POST",
        body: JSON.stringify({
          text,
          model_profile_id: modelProfileId ?? null,
        }),
      },
    ),
  /** Подтверждает конкретный preview; повторный вызов идемпотентен. */
  commitProtection: (
    conversationId: string,
    body: { preparation_id: string; digest: string; revision: number },
  ) =>
    request<{
      preparation_id: string;
      status: string;
      revision: number;
      sanitized_text: string;
      entities_count: number;
      note: string;
    }>(`/api/v1/protection/conversations/${conversationId}/commit`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
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
  queryKnowledgeBase: (
    kbId: string,
    text: string,
    topK = 5,
    chatModelProfileId?: string,
  ) =>
    request<QueryResult>(`/api/v1/knowledge-bases/${kbId}/query`, {
      method: "POST",
      body: JSON.stringify({
        text,
        top_k: topK,
        chat_model_profile_id: chatModelProfileId ?? null,
      }),
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
  /**
   * Экспорт результата запроса средствами backend.
   *
   * Использует серверный эндпоинт экспорта, а не формирование файла на
   * клиенте: XLSX на клиенте пришлось бы подделывать HTML-таблицей с
   * расширением `.xls`, что не является настоящим XLSX.
   *
   * @param assetId Идентификатор ассета-таблицы.
   * @param sql SQL-запрос (только SELECT).
   * @param format Формат файла: csv или xlsx.
   * @returns Blob с готовым файлом для скачивания.
   */
  tableExport: (assetId: string, sql: string, format: "csv" | "xlsx") =>
    requestBlob(`/api/v1/assets/${assetId}/table/export`, {
      method: "POST",
      body: JSON.stringify({ sql, format }),
    }),
  prices: (modelProfileId: string) =>
    request<Price[]>(
      `/api/v1/prices?model_profile_id=${encodeURIComponent(modelProfileId)}`,
    ),
  /**
   * Разбирает страницу тарифов провайдера и возвращает кандидатов на цены.
   *
   * Ничего не сохраняет: найденные значения пользователь проверяет и вносит
   * вручную, потому что разбор страницы эвристический.
   *
   * @param url Публичный адрес страницы тарифов.
   * @param options Режим разбора и модель для LLM-режима.
   * @returns Кандидаты с фрагментами текста и напоминанием о проверке.
   */
  extractPrices: (
    url: string,
    options: {
      method?: "static" | "llm" | "rendered";
      modelProfileId?: string;
    } = {},
  ) =>
    request<PriceImportResult>("/api/v1/prices/extract", {
      method: "POST",
      body: JSON.stringify({
        url,
        method: options.method ?? "static",
        model_profile_id: options.modelProfileId ?? null,
      }),
    }),
  createPrice: (input: {
    model_profile_id: string;
    input_per_million: string;
    output_per_million: string;
    currency: string;
    /** Тариф попадания в кэш (cache hit). Не задан — вход по обычной цене. */
    cache_read_per_million?: string | null;
    /** Тариф записи в кэш (Anthropic-style). */
    cache_write_per_million?: string | null;
    /** Происхождение цены: manual (по умолчанию) | api | url. */
    source?: string;
    /** Страница-источник, если цена взята с сайта провайдера. */
    source_url?: string | null;
  }) =>
    request<Price>("/api/v1/prices", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  fxRates: () => request<FxRate[]>("/api/v1/fx-rates"),
  createFxRate: (input: {
    from_currency: string;
    to_currency: string;
    rate: string;
  }) =>
    request<FxRate>("/api/v1/fx-rates", {
      method: "POST",
      body: JSON.stringify(input),
    }),
};
