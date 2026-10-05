# Руководство сопровождения Personal AI Hub

> Это обязательный шаблон для команды поддержки. Coding-агент заполняет фактические имена сервисов, команды, схемы и runbooks по мере реализации.

## Назначение и функции документа
Документ объясняет внутреннюю архитектуру, эксплуатацию, диагностику, миграции, backup/restore, инциденты, тесты и добавление провайдеров. Он не заменяет пользовательский README.

## Карта сервисов
| Сервис | Назначение | Порт (хост) | Health | Образ/версия |
| --- | --- | --- | --- | --- |
| `web` | Next.js UI, не владеет ключами | 3000 | `/api/health` | node:22-alpine, Next 16 |
| `api` | FastAPI: auth, providers, conversations, budgets, jobs, RAG | 8000 | `/api/v1/health/ready` | python:3.12-slim |
| `worker` | Celery: document ingest/embedding; Этап 2 — media | — | `celery inspect ping` | тот же backend-образ |
| `postgres` | источник истины | 5432 (внутр.) | `pg_isready` | postgres:16-alpine |
| `valkey` | broker, cache, locks с TTL | 6379 (внутр.) | `valkey-cli ping` | valkey/valkey:8-alpine |
| `qdrant` | embeddings | 6333 (внутр.) | `/readyz` | qdrant/qdrant:v1.15.4 |

Тома: `pgdata`, `valkeydata`, `qdrantdata`, `assets` (BlobStore, `/data/assets`).

Зависимости: `api` зависит от postgres/valkey/qdrant (healthy); `web` — от `api`;
`worker` — от postgres/valkey/qdrant. Миграции применяет только `api` (entrypoint).

## Потоки данных
### Chat
UI → API → budget reservation → provider adapter → SSE → message/usage persistence → reservation settlement.

Пояснение: reservation создается до внешнего вызова, чтобы параллельные запросы не обходили лимит. Финальный usage корректирует оценку.

### Document ingest
Upload → Asset → Job → parser → chunks → embeddings → Qdrant → Document ready.

Пояснение: PostgreSQL хранит статусы и provenance, Qdrant не является источником истины. Job должна быть возобновляемой/идемпотентной.

### Video — Этап 2
Request → price confirmation → reservation → submit → external id → webhook/poll → secure download → Asset → FFmpeg child job → gallery.

Пояснение: timeout после submit не означает, что задача не создана; она требует reconciliation, а не немедленного retry.

## Диагностические команды
```bash
make status
make health
make logs SERVICE=api
make logs SERVICE=worker
make doctor
```

Пояснение блока: `status/health` показывают состояние; адресный `logs` уменьшает шум; `doctor` собирает версии, свободное место и redacted конфигурацию. Команда doctor никогда не выводит ключи.

## Runbook: API не ready
1. Проверить PostgreSQL и миграции.
2. Проверить master key: изменение ключа делает сохраненные credentials нечитаемыми.
3. Проверить dependency health.
4. Найти request id/correlation id.
5. Не удалять volumes как «исправление».

## Runbook: worker/jobs
- Сравнить heartbeat и lock TTL.
- Проверить broker connectivity и очередь.
- Stale running job переводится recovery process в retryable/failed по политике типа.
- Для платной video job не использовать manual retry до reconciliation external id.

## Runbook: расходы
- Проверить cost state, price snapshot, валюту и fx rate.
- Сравнить provider request id с внешним кабинетом.
- Не менять старые usage records при обновлении прайса.
- Исправление выполняется reconciliation record/audit, а не silent overwrite.

## OCR и распознавание документов
Общий интерфейс — `OcrBackend` (`packages/core/personal_hub/ocr.py`). Выбор
backend и лимиты задаются переменными окружения:

| Переменная | Назначение | По умолчанию |
| --- | --- | --- |
| `OCR_BACKEND` | `tesseract` \| `rapidocr` \| `auto` (RapidOCR при доступности, иначе Tesseract) | `tesseract` |
| `OCR_LANGUAGES` | языки tesseract через запятую | `rus,eng` |
| `OCR_MAX_PAGES` | максимум страниц OCR на документ | `40` |
| `OCR_MAX_IMAGE_SIDE` | препроцессинг: сторона изображения не более лимита | `3500` |
| `OCR_PAGE_TIMEOUT_SECONDS` | таймаут распознавания страницы | `30.0` |

Пояснения:
- RapidOCR (`rapidocr_onnxruntime`) **не входит** в базовые зависимости и ставится
  отдельно — lazy import, idle память не растёт. `OCR_BACKEND=tesseract` —
  полный rollback (ADR-0002).
- **Установка RapidOCR требует headless-OpenCV.** Пакет `rapidocr_onnxruntime`
  тянет `opencv-python`, которому нужен `libGL.so.1`; в `python:3.12-slim`
  его нет, и backend падает на импорте. Рабочий вариант (в порядке установки):
  ```bash
  pip install opencv-python-headless==4.11.0.86
  pip install --no-deps rapidocr_onnxruntime==1.4.4
  pip install onnxruntime==1.30.0 pyclipper==1.3.0.post6 Shapely==2.1.1 tqdm==4.67.1
  ```
  Если добавить `libgl1` в образ вместо headless-варианта, прирост образа
  вырастет примерно с +329 МБ до +665 МБ.
- Измеренные характеристики RapidOCR (A4 300 dpi, синтетическая страница):
  ~1,3–2,6 с на страницу и пик RAM ~0,8 ГБ против ~1,0 с и ~0,19 ГБ у
  Tesseract; качество распознавания этими числами не измеряется. Включать
  RapidOCR стоит точечно под сложные сканы, а не как замену Tesseract.
- Ошибки OCR не проглатываются: `OcrError` с кодами `OCR_UNAVAILABLE` /
  `OCR_FAILED` / `OCR_TIMEOUT` виден в статусе документа и job (`make logs
  SERVICE=worker`). В тексте ошибки `OCR_UNAVAILABLE` есть первопричина
  импорта (например, отсутствие `libGL.so.1`).
- OCR применяется к страницам PDF без текстового слоя и к загруженным
  изображениям (PNG/JPG/TIFF/WEBP/BMP).
- Интеграционные OCR-тесты используют детерминированный fake-backend, чтобы не
  зависеть от системного tesseract; живой путь проверяется вручную через
  загрузку скан-PDF.

## Миграции
```bash
make backup
make migrate-check
make migrate
make smoke
```

Пояснение блока: backup обязателен; check проверяет направление/совместимость; migrate применяет Alembic; smoke подтверждает пользовательский путь. Downgrade допустим только если миграция явно reversible и протестирована.

## Backup/restore
Перечислить фактический состав backup: PostgreSQL, Qdrant snapshot, blobs, manifest, app version. Valkey не обязателен. Restore проверять на отдельном volume до замены рабочего окружения.

```bash
make backup
make restore-verify FILE=/path/to/backup
make restore FILE=/path/to/backup
```

Пояснение блока: `restore-verify` валидирует checksum/version без изменения production; `restore` требует подтверждение и останавливает writes.

## Обновление
- Прочитать release notes и migrations.
- Создать backup.
- Обновить на staging/test profile.
- Запустить весь бесплатный test suite и smoke.
- Обновить production.
- Наблюдать errors/latency/jobs минимум один цикл.

## Логи и метрики
Обязательные поля: timestamp UTC, level, service, version, request_id, job_id, provider_type, error_code; запрещены secret, Authorization, полный приватный prompt/document. Метрики: request latency/errors, provider errors, queue depth, stale jobs, usage/cost, disk, Qdrant, backup age.

## Добавление LLM-провайдера
1. Проверить, нельзя ли использовать generic OpenAI-compatible adapter.
2. Добавить adapter только при реальном отличии контракта.
3. Реализовать capability mapping и error normalization.
4. Добавить sanitized contract fixtures.
5. Unit + integration + opt-in live test.
6. Обновить preset, notices и пользовательский README.

## Добавление video-провайдера — Этап 2
1. Зафиксировать официальную документацию/версию/ToS в ADR.
2. Реализовать submit/status/cancel/webhook только по реальному API.
3. Описать billing units и max-cost estimate.
4. Протестировать idempotency/unknown timeout/expired URL.
5. Провести live certification с минимальным бюджетом.

## Инциденты
Severity:
- SEV1: утечка ключей/данных, неконтролируемые списания, потеря данных.
- SEV2: недоступен основной пользовательский сценарий, массово stuck jobs.
- SEV3: отдельный provider/format не работает.

Для SEV1: остановить внешние вызовы, отозвать ключи, сохранить логи без секретов, оценить затраты/данные, выпустить postmortem.

## Definition of support handoff
Новый сотрудник/ИИ должен за 30 минут найти: topology, health, logs, migrations, backup, provider adapter, cost logic и known issues. Если не может — документ недостаточен и должен быть обновлен.
