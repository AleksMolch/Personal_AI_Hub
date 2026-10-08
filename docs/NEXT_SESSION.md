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
make test-unit      # 94 теста (docker)
make test-integration  # 56 тестов (изолированный postgres+valkey)
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

7. ✅ **Live provider certification — закрыто 2026-10-07.** Каркас
   `tests/live/` + `make test-live` (по умолчанию выключен, бюджет-гард
   `LIVE_TEST_BUDGET`, ключи только из `.env`). Сертифицированы
   `api.teamorouter.com/v1` (`deepseek-v4-flash-free`) и официальный DeepSeek
   Platform `api.deepseek.com/v1` (`deepseek-flash`): health, непотоковый чат
   с actual usage, streaming — зелёные; embedding-моделей нет (skip).
   Reasoning-моделям нужен `LIVE_MAX_TOKENS` (по умолчанию 256). Побочно:
   `ProviderConnection.api_key` исключён из repr (pytest печатал фикстуру
   с ключом при падении).

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
   - Тесты: 13 unit (`tests/unit/test_ocr.py`: выбор backend, auto/fallback,
     таймаут, downscale, лимит страниц, разбор изображения, первопричина
     ошибки импорта RapidOCR), 5 integration
     (`test_knowledge_api.py`: синтез без цены пропускается, UsageRecord для
     embed/rag_query_embedding/rag_synthesis, OCR E2E с детерминированным
     fake-backend «скан→RAG», негативный — OCR-ошибка в статусе документа;
      + 2 E2E реального пути poppler→tesseract: blank-скан → EMPTY_DOCUMENT
      и скан с читаемым текстом → «VECTORSEARCH» в чанках).
     Все зелёные: unit 81, integration 45, ruff/mypy чисто.

7a. **Ресурсные измерения RapidOCR (2026-10-05) и полный smoke — закрыты.**
    - Измерено на одноразовых probe-образах (в compose не входят):
      базовый образ 780,2 МБ; минимальный вариант установки
      (`opencv-python-headless` + `rapidocr_onnxruntime --no-deps` +
      `onnxruntime`) — +329,3 МБ; вариант с `libgl1` — +665,3 МБ.
    - A4 300 dpi: Tesseract ~1,0 с/страница и пик ~0,19 ГБ, RapidOCR
      1,3–2,6 с/страница и пик ~0,82 ГБ; idle RAM не растёт (lazy import).
    - Найдено: `rapidocr_onnxruntime` требует `libGL.so.1` (opencv-python).
      Текст ошибки `OCR_UNAVAILABLE` теперь содержит первопричину, в
      README_staff — порядок установки headless-варианта.
    - Полный `make smoke` на Windows (PowerShell-эквивалент) зелёный:
      `/health/ready`, `/version`, `alembic current` = 0007 (head),
      `celery inspect ping` = pong.
    - Оценка «+20–40 МБ» из ADR-0002 не подтвердилась и исправлена.

7b. **Итерация 3: LiteLLM как внешний proxy (ADR-0004) — закрыто.**
    - Измерения: библиотека `litellm==1.104.0` в backend стоила бы +355,3 МБ к
      образу и +178,5 МБ RSS при импорте (5,31 с) в каждом процессе —
      отклонено. Вариант A (внешний proxy `ghcr.io/berriai/litellm:v1.104.0`,
      +383,1 МБ сжатых слоёв) качается только с `--profile litellm`.
    - Реализация: сервис `litellm` в `compose.yaml` (профиль `litellm`, порт
      только на 127.0.0.1), шаблон `infra/litellm/config.yaml` без секретов,
      `make up-litellm` / `make down-litellm`, пресет `litellm_proxy`
      (`http://litellm:4000/v1`) на том же OpenAI-compatible адаптере.
    - Проверено вживую: proxy healthy, `/health/liveliness` → 200,
      `/v1/models` → `litellm-default`; `docker compose config` без профиля
      сервис не показывает.
    - Тесты: unit на пресет/реестр (+ проверка, что `litellm` не установлен в
      backend) и 2 integration — сквозной контур и стабильность кодов
      401/429/5xx. Integration 45→47.

7c. **Итерация 5: LlamaIndex benchmark (ADR-0003) — закрыто (2026-10-07).**
    - Создан `experiments/llamaindex_rag_benchmark/` (dataset 10 документов /
      17 вопросов, benchmark.py, run.sh, README). LlamaIndex
      (`llama-index-core==0.14.25`) ставится только в одноразовый контейнер,
      в зависимости проекта не входит.
    - Результат: recall@k (документ и факт), top-1 и отказ на неотвечаемых
      совпадают с нативным pipeline; MRR у нативного чуть выше (0,9167 против
      0,8988), построение индекса ~14× дольше, Python-аллокации 12,4 МБ против
      0,13 МБ. Dependency не добавляется, переносить нечего.
    - Decision report: `docs/IMPROVEMENTS_ASSESSMENT.md`, раздел 5.
    - В той же сессии исправлены дефекты предыдущей: ingest помечает документ
      failed при сбоях провайдера/разбора (`PROVIDER_ERROR`/`PARSE_FAILED`),
      OCR рендерит только запрошенные страницы (лимит `OCR_MAX_PAGES` больше
      не обходится диапазоном min..max), Base URL OpenRouter в примерах
      LiteLLM. Плюс правки по ревью: цена обязательна для embedding-вызовов
      (PRICE_REQUIRED), ошибки резервирования видны в документе, частично
      выполненный вызов финализируется, actual usage провайдера пишется в
      UsageRecord. Минорный проход по ревью: частичный OCR (OCR_PARTIAL),
      OCR_MAX_PAGES=0=off, пиксельный лимит, answer_skipped_reason,
      streaming-контракт litellm_proxy. Итог: unit 93, integration 56.

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

Текущие проверки зелёные: make test-unit (94), make test-integration (56),
ruff/mypy/tsc/eslint/prettier, make test-e2e (нужен Node 20+). Стек:
api/worker/beat/web + postgres/valkey/qdrant, запускается docker compose
up -d --build. Опционально: make up-litellm (профиль `litellm`, ADR-0004).
Эксперименты (не входят в зависимости): experiments/llamaindex_rag_benchmark.

Release gate закрыт: live provider certification выполнен (пункт 7), все
Итерации 1–5 из IMPROVEMENT_TASKS_FOR_CODING_AI.md закрыты или DEFER.
Твоя задача — подготовка Этапа 2 (Video) по ROADMAP:
1. Итерация 4 (Docling) остаётся DEFER — браться только при появлении
   реальной потребности в сложных PDF.
2. Перед началом Этапа 2 убедиться, что счётчики тестов совпадают с
   фактическими (`make test-unit`, `make test-integration`), и что live-каркас
   (`make test-live`) по-прежнему выключен по умолчанию.

Уже закрыто в конце Итерации 2 (2026-09-21): E2E с реальными бинарниками
poppler→tesseract (blank-скан PDF → EMPTY_DOCUMENT в статусе документа,
иначе были бы сбои связки); счётчик integration 43→44.
Закрыто 2026-10-05:
- ресурсные измерения RapidOCR (+329,3 МБ при headless-установке, libgl1 не
  нужен; документировано в ADR-0002 и README_staff);
- полный smoke (ready/version/alembic 0007 head/worker pong);
- реальный OCR-тест на читаемой странице: фикстура PDF-из-картинки,
  «VECTORSEARCH» доезжает до чанков (integration 44→45);
- Итерация 3: LiteLLM как внешний proxy (ADR-0004), integration 45→47.
Закрыто 2026-10-07:
- исправления предыдущей сессии: ingest помечает документ failed при сбоях
  провайдера/разбора (unit 94, integration 56), OCR рендерит только
  запрошенные страницы, исправлен Base URL OpenRouter в примерах LiteLLM;
- Итерация 5: benchmark `experiments/llamaindex_rag_benchmark/` — dependency
  не добавляется, recall@k совпадает, decision report в assessment;
- Live provider certification: `tests/live/` + `make test-live`, реальный
  `api.teamorouter.com` (`deepseek-v4-flash-free`): 3 passed / 1 skipped
  (embeddings у провайдера нет), бюджет не израсходован.

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
