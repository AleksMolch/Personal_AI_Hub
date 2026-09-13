# Архитектура и контракты

## Назначение и функции
Документ задает устойчивое ядро, модель данных, API и точки расширения. Главная цель — добавить видео на втором этапе новыми адаптерами и UI-модулями, не переписывая чат, расходы, jobs и storage.

## Технологический стек
- Frontend: Next.js + React + TypeScript strict, TanStack Query, доступная component library.
- Backend: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, httpx.
- Worker: Celery с Valkey broker; тот же доменный пакет, отдельный процесс.
- Data: PostgreSQL, Qdrant, Valkey.
- Blob storage: интерфейс `BlobStore`; локальный filesystem по умолчанию, S3-compatible адаптер опционально.
- Document tools: MarkItDown/специализированные permissive parsers, DuckDB, OCR профиль.
- Tests: pytest, Vitest, Playwright, Testcontainers или Compose test profile.

Конкретные версии выбираются на дату реализации, проверяются по официальным release notes и фиксируются lock-файлами.

## Компоненты
```text
Browser
  │ HTTPS/SSE
  ▼
Web (Next.js) ─────► API (FastAPI) ─────► Provider adapters ─► External APIs
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
         PostgreSQL    Valkey       Qdrant
              │           │
              ▼           ▼
          BlobStore ◄── Worker/Celery
```

API владеет транзакциями и секретами. Worker выполняет импорт, OCR, embeddings и позднее video jobs. Provider adapters изолируют внешние контракты.

## Доменная модель

### ProviderCredential
`id, user_id, provider_type, display_name, base_url, encrypted_secret, enabled, priority, currency, created_at, updated_at`.

Ключ не возвращается API после сохранения. `provider_type` выбирает адаптер, но OpenAI-compatible base URL остается конфигурируемым.

### ModelProfile
`id, provider_id, external_model_id, display_name, capabilities[], context_limit, output_limit, enabled, metadata_json`.

Capabilities — данные, а не условные ветки UI. Зарезервированы `video_text`, `video_image`, `video_edit`.

### Conversation / Message
Conversation хранит настройки по умолчанию. Message хранит role, content blocks, status, parent id для ветвления, provider/model snapshot. Контент проектируется блоками `text`, `citation`, `asset_ref`, `tool_call`, чтобы позднее добавить media result.

### Job
`id, user_id, type, status, progress, provider_id?, model_profile_id?, external_job_id?, idempotency_key, input_json, output_json, error_code, error_detail_safe, submitted_at, started_at, finished_at, heartbeat_at, attempts`.

Типы Этапа 1: document_ingest, document_delete, embedding, export. Типы Этапа 2: video_generate, video_download, video_process. Статусная машина проверяется централизованно.

### Asset
`id, user_id, kind, status, blob_key, original_name, mime_type, size_bytes, sha256, width?, height?, duration_ms?, metadata_json, created_at`.

`kind`: document, image, video, thumbnail, export. URL не хранится как вечный источник истины; он строится BlobStore/endpoint.

### UsageRecord
`id, user_id, provider_id, model_profile_id, job_id?, message_id?, units_json, cost_amount NUMERIC, currency, cost_state, price_snapshot_id, fx_rate_id?, provider_request_id, occurred_at`.

`cost_state`: estimated, actual, reconciled, unknown. Это предотвращает выдачу оценки за факт.

### PriceSnapshot / FxRate
Хранят историю цен и валютных курсов. Обновление цены не изменяет старые UsageRecord.

### KnowledgeBase / Document / Chunk
KnowledgeBase имеет embedding profile/version. Chunk содержит текст, location metadata и vector id. PostgreSQL хранит метаданные, Qdrant — вектор и фильтруемый payload.

## Интерфейсы расширения

```python
class ProviderAdapter(Protocol):
    provider_type: str
    async def health(self, credential) -> HealthResult: ...
    async def list_models(self, credential) -> list[RemoteModel]: ...
    def capabilities(self, model: ModelProfile) -> set[Capability]: ...

class ChatProvider(ProviderAdapter, Protocol):
    async def stream_chat(self, request) -> AsyncIterator[ChatEvent]: ...

class EmbeddingProvider(ProviderAdapter, Protocol):
    async def embed(self, request) -> EmbeddingResult: ...

class AsyncGenerationProvider(ProviderAdapter, Protocol):
    async def submit(self, request, idempotency_key: str) -> Submission: ...
    async def get_status(self, external_job_id: str) -> RemoteJobStatus: ...
    async def cancel(self, external_job_id: str) -> CancelResult: ...
    def verify_webhook(self, headers, body: bytes) -> WebhookEvent: ...
```

Блок показывает разделение способностей. На Этапе 1 реализуются Chat/Embedding. На Этапе 2 — AsyncGeneration, не меняя Provider registry.

```python
class BlobStore(Protocol):
    async def put(self, stream, metadata) -> StoredBlob: ...
    async def open(self, key: str) -> AsyncIterator[bytes]: ...
    async def delete(self, key: str) -> None: ...
    async def signed_url(self, key: str, ttl_seconds: int) -> str: ...
```

BlobStore отделяет локальный диск от S3. В public/local режиме download должен идти через авторизованный API, если bucket не публичный.

## API v1

### System
- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`
- `GET /api/v1/version`

### Providers/models
- `GET/POST /api/v1/providers`
- `GET/PATCH/DELETE /api/v1/providers/{id}`
- `POST /api/v1/providers/{id}/test`
- `POST /api/v1/providers/{id}/sync-models`
- `GET /api/v1/models?capability=chat`

### Conversations
- `GET/POST /api/v1/conversations`
- `GET/PATCH/DELETE /api/v1/conversations/{id}`
- `POST /api/v1/conversations/{id}/messages` — создает generation id.
- `GET /api/v1/generations/{id}/events` — SSE.
- `POST /api/v1/generations/{id}/cancel`
- `POST /api/v1/conversations/{id}/export`

### Assets/jobs/knowledge
- `POST /api/v1/assets/uploads` — multipart/streaming upload.
- `GET/DELETE /api/v1/assets/{id}`
- `GET /api/v1/jobs`, `GET /api/v1/jobs/{id}`
- `POST /api/v1/jobs/{id}/retry`, `POST /api/v1/jobs/{id}/cancel`
- `GET/POST /api/v1/knowledge-bases`
- `POST /api/v1/knowledge-bases/{id}/documents`
- `POST /api/v1/knowledge-bases/{id}/query`

### Usage/budget
- `GET /api/v1/usage/summary`
- `GET /api/v1/usage/records`
- `GET/PUT /api/v1/budgets`
- `GET/POST /api/v1/prices`

### Этап 2
- `POST /api/v1/video/generations`
- `GET /api/v1/video/generations/{job_id}`
- `POST /api/v1/video/generations/{job_id}/cancel`
- `POST /api/v1/webhooks/{provider_type}`
- `GET /api/v1/video/gallery`

## Стабильный формат ошибки
```json
{
  "error": {
    "code": "PROVIDER_RATE_LIMITED",
    "message": "Провайдер временно ограничил частоту запросов.",
    "request_id": "...",
    "retryable": true,
    "details": {}
  }
}
```

Пояснение: UI зависит от `code`, а не от текста стороннего провайдера. `details` очищается от секретов.

## SSE события
`generation.started`, `content.delta`, `citation`, `usage`, `generation.completed`, `generation.failed`, `heartbeat`. Каждое событие имеет schema version и generation id.

## Конфигурация
`.env` содержит только bootstrap/secrets: database URL, master encryption key, bind mode. Провайдеры настраиваются UI и БД. Должен поддерживаться env-only режим для CI/быстрого старта.

## Решения, предотвращающие переделку на Этапе 2
1. Jobs и assets используются уже для документов.
2. Content blocks поддерживают asset references.
3. Usage units — JSON + нормализованная стоимость, поэтому можно учитывать секунды/генерации.
4. Capability registry управляет UI.
5. BlobStore существует до видео.
6. Worker и cancellation/retry существуют до видео.
7. Provider-specific параметры валидируются JSON Schema адаптера, а не добавляются колонками.
