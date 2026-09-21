# Передача проекта следующей сессии

## Назначение и функции
Файл для восстановления контекста новой сессией ИИ-разработчика. Содержит:
1) что уже реализовано, 2) что осталось, 3) готовый промпт для запуска.

## 1. Что реализовано (Этап 1 — полностью, 8 срезов)

**Репозиторий и запуск.** Монорепозиторий (`apps/web`, `apps/api`, `apps/worker`,
`packages/core`, `infra`, `tests`, `docs`). Запуск одной командой: `make bootstrap`
(создаёт `.env` со случайными секретами + сборка) → `make up`. Docker Compose:
web (Next.js), api (FastAPI), worker (Celery), beat (Celery beat), PostgreSQL,
Valkey, Qdrant — все с healthcheck. Миграции Alembic автоматически идемпотентно.
Structured JSON-логи с redaction секретов. CI: ruff, mypy, pytest, tsc, eslint,
secret scan (gitleaks).

**Авторизация.** Bootstrap первого администратора, вход, JWT (Argon2id пароли).
Шифрование API-ключей провайдеров мастер-ключом (Fernet), в UI только маска.

**Провайдеры и модели.** OpenRouter/RouterAI/Selectel/OpenAI-compatible через
единый адаптер. CRUD, test connection, sync-models, каталог моделей. Нормализация
ошибок 401/402/403/404/429/5xx в стабильный формат.

**Чат.** Диалоги, потоковый SSE, отмена, экспорт MD/JSON, восстановление после
рестарта. Буфер событий — in-memory (однопроцессный).

**Расходы/бюджеты.** UsageRecord, PriceSnapshot, FxRate, Budget, CostReservation.
Decimal-расчёты, резервирование до вызова, settlement после, estimated vs actual,
дневной/месячный hard limit (402 BUDGET_EXCEEDED), Celery beat reconciliation.

**Jobs/Assets.** BlobStore (local) с sha256 и лимитом, Job state machine, Celery
run_job + heartbeat, retry/cancel, reconciliation «мёртвых» задач.

**Документы/RAG.** Парсеры TXT/MD/PDF(pypdf)/DOCX(python-docx) + OCR сканов
(tesseract+poppler), чанкинг с overlap, embeddings, Qdrant (коллекция на версию
модели), KnowledgeBase/Document/Chunk, query с цитатами + LLM-синтез ответа.

**Таблицы.** CSV/XLSX schema preview, DuckDB read-only sandbox (SELECT-only,
`enable_external_access=false`), экспорт CSV/XLSX.

**Релиз.** README/README_staff/THIRD_PARTY_NOTICES/LICENSE, backup/restore drill,
нагрузочный smoke, E2E Playwright (smoke вход+навигация).

### Команды
```bash
make bootstrap      # окружение + .env + сборка
make up             # запуск стека
make down           # остановка
make lint typecheck # ruff/mypy + tsc/eslint
make test-unit      # 80 тестов (docker)
make test-integration  # 44 теста (изолированный postgres+valkey)
make test-e2e       # Playwright (нужен запущенный стек + admin/supersecret123)
make smoke          # smoke поднятого экземпляра
make backup         # архив в backups/
```

## 2. Что ещё предстоит (известные пробелы)

Приоритет (security/cost correctness → infra → UX). Пункты 1–2 и 4–5 закрыты,
а также исправлены два найденных при проверке бага (см. ниже).

1. ✅ **Конкурентность бюджета** — `SELECT ... FOR UPDATE` + тест (0adf138).

2. ✅ **Эндпоинты FxRate** — `GET/POST /api/v1/fx-rates` + поле в UI (6e634f5).

3. ✅ **Импорт цен из API провайдера** — `sync-models` подтягивает pricing
   (OpenRouter-style `pricing.prompt`/`completion`), создаёт `PriceSnapshot`
   (source="api"); ручная цена имеет приоритет, повторный sync идемпотентен.

4. ✅ **Cooperative cancel для running-задач** — флаг `cancel_requested` (a683c56).

5. ✅ **JSON-логи Celery** — worker/beat в едином JSON-формате (ff0ee18).

   Дополнительно закрыто в текущей сессии:
   - Worker: NullPool для asyncpg — устранён `RuntimeError: attached to a
     different loop` (каждая задача запускалась через `asyncio.run`, а пул
     переиспользовал loop-bound соединения). + регрессионный тест.
   - beat логирует `"service": "beat"` (раньше «worker»).
   - `make lint`: убран сломанный `--entrypoint ruff`, добавлен `apps/worker`.

6. ✅ **Windows clean install** — проверен на Windows + Docker Desktop 29.8
   (сборка, healthy, миграции head, worker, bootstrap admin, smoke-
   эквивалент PowerShell, unit 69/integration 39, ruff/mypy/eslint/tsc/
   prettier). Найденные и исправленные регрессии: CRLF-файлы ломали `prettier
   --check` (общий `.gitattributes` `* text=auto eol=lf`); на хосте нет Git Bash
   (system32 bash не работает), поэтому infra-scripts пришлось проверять
   PowerShell-эквивалентом; host-E2E невозможен при Node 18 (Playwright требует
   20+). Подробности: `docs/WINDOWS_HANDOFF.md`.

7. **Live provider certification** — отдельные тесты реальных API с бюджетом
   (`RUN_LIVE_TESTS=1`, по умолчанию выключены).

7.5. ✅ **Улучшения (IMPROVEMENT_TASKS_FOR_CODING_AI.md) — Итерация 1
   (assessment) и Итерация 2 ЗАВЕРШЕНЫ 2026-09-21.** Созданы
   `docs/IMPROVEMENTS_ASSESSMENT.md`, ADR `0002-add-rapidocr`,
   `0003-add-llamaindex-targeted`. Решения: LiteLLM=DEFER, RapidOCR=GO,
   MarkItDown=DEFER, Docling=DEFER, LlamaIndex=PROTOTYPE ONLY.
   Итерация 2 закрыла оба приоритетных пункта:

   - **Billing gap закрыт.** `apps/api/app/billing.py`: `finalize_generation`
     принимает `message_id: None`; добавлены `embedding_units`,
     `reserve_external_call`, `settle_external_call`, `cancel_external_call`.
     Worker `ingest.py`: эмбеддинги документов резервируются до вызова
     провайдера, фиксируются в UsageRecord (operation="embedding"); при ошибке
     резерв освобождается. `knowledge.py`: embedding RAG-запроса
     (operation="rag_query_embedding") и LLM-синтез
     (operation="rag_synthesis") — тот же контур; **без цены модели синтез
     не вызывается** (answer=None), чтобы платный вызов не уходил мимо
     бюджета.
   - **RapidOCR внедрён (ADR-0002).** `packages/core/personal_hub/ocr.py`:
     `OcrBackend` protocol, `TesseractOcrBackend`, `RapidOcrBackend` (lazy
     import, НЕ в базовых зависимостях), `get_ocr_backend()` с режимом
     `auto` + fallback, `recognize_image` (single worker, per-page timeout),
     `ocr_pdf_pages` (`OCR_MAX_PAGES`, рендер pdf2image). Настройки в
     `config.py`: `OCR_BACKEND/OCR_LANGUAGES/OCR_MAX_PAGES/OCR_MAX_IMAGE_SIDE/
     OCR_PAGE_TIMEOUT_SECONDS`. Ошибки OCR перестали проглатываться
     (`parsing.py`): raise `OcrError`, в worker ловятся → документ
     `status=failed, error_code=OCR_*`. Поддержаны изображения
     (PNG/JPG/TIFF/WEBP/BMP) как документы; UI accept обновлён.
   - Тесты: 11 unit (`tests/unit/test_ocr.py`: выбор backend, auto/fallback,
     таймаут, downscale, лимит страниц, разбор изображения), 4 integration
     (`test_knowledge_api.py`: синтез без цены пропускается, UsageRecord для
     embed/rag_query_embedding/rag_synthesis, OCR E2E с детерминированным
     fake-backend «скан→RAG», негативный — OCR-ошибка в статусе документа;
      + E2E реального пути poppler→tesseract (blank-скан → EMPTY_DOCUMENT).
     Все зелёные: unit 80, integration 44, ruff/mypy чисто.

8. **Этап 2 «Video»** — НЕ начинать до закрытия пунктов 1–2 (release gate).
   Далее: исследование контрактов Veo/Seedance/Kling/Sora, ADR на каждый адаптер,
   sanitized fixtures, async-generation adapters, webhook/polling, галерея, FFmpeg.

## 3. Промпт для запуска следующей сессии

Скопируйте целиком:

```
Ты продолжаешь разработку self-hosted AI-платформы Personal AI Hub (Этап 1).
Репозиторий на ветке main (актуальный коммит). Перед работой прочитай в порядке:
AGENTS.md, 00_START_HERE.md, SPECIFICATION.md, ARCHITECTURE.md, ROADMAP.md,
TESTING.md, docs/IMPLEMENTATION_STATUS.md, docs/adr/0001-monorepo-and-stack.md,
README_staff.md, AI_MAINTENANCE.md.

Уже реализовано (Этап 1 полностью): запуск одной командой (make bootstrap/up),
авторизация (bootstrap admin + JWT), провайдеры (OpenRouter/RouterAI/Selectel/
OpenAI-compatible + presets + sync-models), потоковый чат с отменой и экспортом,
расходы и бюджеты (UsageRecord/PriceSnapshot/FxRate/Budget/CostReservation,
hard limit до отправки провайдера, estimated vs actual), Jobs/Assets (BlobStore,
state machine, Celery, heartbeat, retry/cancel, reconciliation), RAG (парсеры +
OCR, чанкинг, embeddings, Qdrant, query с цитатами + LLM-синтез), таблицы
(CSV/XLSX + DuckDB read-only sandbox), релиз (README/LICENSE/notices, backup/
restore, E2E Playwright).

Текущие проверки зелёные: make test-unit (80), make test-integration (43),
ruff/mypy/tsc/eslint/prettier, make test-e2e (нужен Node 20+). Стек:
api/worker/beat/web + postgres/valkey/qdrant, запускается docker compose
up -d --build.

Твоя задача — Итерация 3 улучшений (см. IMPROVEMENT_TASKS_FOR_CODING_AI.md,
docs/IMPROVEMENTS_ASSESSMENT.md и ADR 0002/0003):
1. Документировать прирост размера образа и RAM при включённом RapidOCR
   (ADR-0002, задача remaining).
2. Оценить следующего кандидата: MarkItDown или Docling (см.
   IMPROVEMENT_TASKS_FOR_CODING_AI.md § «Итерация 3»), создать ADR, начать
   прототип при решении GO.
3. Прогнать live-тесты (`RUN_LIVE_TESTS=1`) с реальным API-ключом при
   наличии бюджета (live provider certification, пункт 7).

Уже закрыто в конце Итерации 2 (2026-09-21): E2E с реальными бинарниками
poppler→tesseract (blank-скан PDF → EMPTY_DOCUMENT в статусе документа,
иначе были бы сбои связки); счётчик integration 43→44.

Обязательно (AGENTS.md): тест/критерий до кода, unit + integration + негативный
тест, Decimal для денег, budget блокирует ДО провайдера, estimated не выдавать за
actual. Стиль: docstring на русском в начале файла, ruff/mypy чисто, стабильный
формат ошибок. Работай вертикальными срезами, в конце — make lint, make typecheck,
make test-unit, make test-integration, make up + smoke, обнови
docs/IMPLEMENTATION_STATUS.md. Этап 2 (Video) не трогать.
```

## Краткая шпаргалка по архитектуре
- `packages/core/personal_hub` — доменный пакет (models, providers, blobstore,
  vectorstore, jobs, costs, tables, parsing, chunking, knowledge, security, queue).
- `apps/api/app` — FastAPI: `main.py`, `api/*` (роутеры), `billing.py`,
  `job_service.py`, `chat_worker.py`, `generation_manager.py`, `deps.py`, `schemas.py`.
- `apps/worker` — Celery: `celery_app.py`, `tasks/*` (jobs, ingest, maintenance, system).
- Общий backend-образ (api+worker+beat) собирается из `apps/api/Dockerfile`; PYTHONPATH=/app.
- Миграции применяет только api (entrypoint.sh); worker/beat — нет.
- Тесты: unit (без инфраструктуры), integration (изолированные postgres+valkey,
  memory vector store, mock HTTP-провайдер из tests/conftest.py).
