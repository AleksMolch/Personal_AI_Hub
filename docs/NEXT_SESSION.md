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
make test-unit      # 66 тестов (docker)
make test-integration  # 37 тестов (изолированный postgres+valkey)
make test-e2e       # Playwright (нужен запущенный стек + admin/supersecret123)
make smoke          # smoke поднятого экземпляра
make backup         # архив в backups/
```

## 2. Что ещё предстоит (известные пробелы)

Приоритет (security/cost correctness → infra → UX). Пункты 1–2 и 4–5 закрыты,
а также исправлены два найденных при проверке бага (см. ниже).

1. ✅ **Конкурентность бюджета** — `SELECT ... FOR UPDATE` + тест (0adf138).

2. ✅ **Эндпоинты FxRate** — `GET/POST /api/v1/fx-rates` + поле в UI (6e634f5).

3. **Импорт цен из API провайдера.** Цены вводятся вручную; можно добавить
   `sync-models` с подтягиванием цен, где провайдер их отдаёт.

4. ✅ **Cooperative cancel для running-задач** — флаг `cancel_requested` (a683c56).

5. ✅ **JSON-логи Celery** — worker/beat в едином JSON-формате (ff0ee18).

   Дополнительно закрыто в текущей сессии:
   - Worker: NullPool для asyncpg — устранён `RuntimeError: attached to a
     different loop` (каждая задача запускалась через `asyncio.run`, а пул
     переиспользовал loop-bound соединения). + регрессионный тест.
   - beat логирует `"service": "beat"` (раньше «worker»).
   - `make lint`: убран сломанный `--entrypoint ruff`, добавлен `apps/worker`.

6. **Windows clean install** — не проверялся (тестировался Linux/Docker на macOS).

7. **Live provider certification** — отдельные тесты реальных API с бюджетом
   (`RUN_LIVE_TESTS=1`, по умолчанию выключены).

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

Текущие проверки зелёные: make test-unit (66), make test-integration (31),
ruff/mypy/tsc/eslint, make test-e2e. Стек: api/worker/beat/web + postgres/valkey/
qdrant, запускается docker compose up -d --build.

Твоя задача — закрыть пробелы (в порядке приоритета, см. docs/NEXT_SESSION.md):
1. Конкурентность бюджета: добавить SELECT ... FOR UPDATE на строку бюджета в
   apps/api/app/billing.py (check_and_reserve) + тест на параллельные запросы.
2. Эндпоинты валют: GET/POST /api/v1/fx-rates + поле в UI (создание курса),
   чтобы конвертация валют была реально применима.
3. (Опционально) импорт цен из API провайдера, cooperative cancel для running,
   JSON-логи Celery.

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
