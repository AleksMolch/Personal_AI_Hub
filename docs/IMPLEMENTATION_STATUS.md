# Статус реализации

## Назначение и функции
Чек-лист требований Этапа 1 с актуальными статусами. Обновляется после каждой
итерации. Статусы: `не начато / в работе / готово / заблокировано`.

## Легенда
- ✅ готово · 🔄 в работе · ⬜ не начато · ⛔ заблокировано

## Вертикальные срезы

### 1. Репозиторий и локальный запуск — ✅
- [x] Монорепозиторий, Makefile, compose.yaml, `.env.example`
- [x] Сервисы web, api, worker, beat, PostgreSQL, Valkey, Qdrant
- [x] `GET /api/v1/version`, `health/live`, `health/ready`
- [x] Alembic-миграции (авто и идемпотентно), structured JSON-логи (api + Celery)
- [x] Healthchecks всех сервисов (проверено `docker compose up`)
- [x] Smoke-скрипт (`make smoke`)
- [x] CI: lint/types/unit/build/secret-scan
- [ ] Windows/Linux clean install проверка (срез 8)

### 2. Авторизация и настройки — ✅
- [x] Local-first bootstrap admin (`POST /auth/bootstrap`, только при пустой БД)
- [x] Вход и JWT (`/auth/login`, `/auth/me`), Argon2id-пароли
- [x] Шифрование provider keys мастер-ключом (Fernet), маска в UI
- [x] CRUD провайдеров + presets (OpenRouter/RouterAI/Selectel/OpenAI-compatible)
- [x] Проверка соединения (`POST /providers/{id}/test`, GET /models, без платных вызовов)
- [x] Синхронизация моделей (`POST /providers/{id}/sync-models`, upsert)
- [x] Каталог моделей (`GET /models?capability=`)
- [x] Нормализация ошибок провайдеров (401/402/403/404/429/5xx) и стабильный формат ошибки
- [x] UI: страница входа и управление провайдерами

### 3. Модели и streaming chat — ✅
- [x] Conversations/Messages (роли, статусы, parent_id для ветвления, model_snapshot)
- [x] Потоковый чат: `POST /conversations/{id}/messages` → `GET /generations/{id}/events` (SSE)
- [x] События SSE: started/content.delta/completed/failed/cancelled + heartbeat
- [x] Отмена генерации (`POST /generations/{id}/cancel`)
- [x] CRUD диалогов, поиск по списку, архив, экспорт Markdown/JSON
- [x] Chat-адаптер (OpenAI-compatible) с SSE-парсингом
- [x] Восстановление после рестарта (streaming → interrupted)
- [x] UI: страница чата с потоковым выводом, выбором модели и отменой
- [ ] Редактирование сообщения с ветвлением (parent_id заложен, UI позже)
- [ ] Поиск по сообщениям (позже)

### 4. Usage, цены и бюджеты — ✅
- [x] UsageRecord (units_json, cost_amount Decimal/NUMERIC, cost_state, price_snapshot_id, fx_rate_id)
- [x] PriceSnapshot (versioned, валюта, effective_at, источник manual/api/url, вход/выход/кэш за 1M)
- [x] FxRate (курс + источник + время) и конвертация без смешивания валют
- [x] GET/POST /fx-rates + поле «Курсы валют» в UI
- [x] Бюджет: дневной/месячный hard limit, резервирование до вызова (SELECT FOR UPDATE)
- [x] Settlement после ответа; release при отмене/ошибке; Celery beat reconcile
- [x] estimated vs actual (usage от провайдера → actual, иначе estimated)
- [x] Эндпоинты: /usage/summary, /usage/records (pagination), GET/PUT /budgets, GET/POST /prices
- [x] Интеграция с чатом: цена обязательна, бюджет блокирует до провайдера (402 BUDGET_EXCEEDED)
- [x] UI: dashboard расходов (день/месяц, токены, лимиты, курсы) + форма бюджета
- [x] Импорт цен из API провайдера (sync-models подтягивает pricing, source="api")

### 5. Jobs и Assets — ✅
- [x] BlobStore: протокол + LocalBlobStore (put/open/delete, sha256, лимит размера)
- [x] Asset модель + загрузка/скачивание/удаление (download через авторизованный API)
- [x] Job state machine (централизованная валидация переходов)
- [x] Celery-задача run_job + heartbeat + идемпотентный повторный запуск
- [x] Reconciliation «мёртвых» задач (worker lost → retryable/failed)
- [x] API: /assets (upload/list/get/content/delete→job), /jobs (list/get/retry/cancel)
- [x] Удаление ассета через document_delete job (безопасно, идемпотентно)
- [x] Cooperative cancel для running-задач (флаг cancel_requested)
- [x] Worker: NullPool для asyncpg (устранён «attached to a different loop» при `asyncio.run` на задачу)
- [x] UI: страница задач (статус, повтор, отмена)
- [ ] Периодический beat для reconciliation (сейчас лениво при чтении)
- [ ] Реальное наполнение document_ingest (срез 6)

### 6. Документы и RAG — ✅
- [x] Парсеры TXT/MD/PDF (pypdf)/DOCX (python-docx)
- [x] OCR-профиль для сканов PDF (tesseract + poppler, ошибки не портят asset)
- [x] Чанкинг с overlap и локацией (страница/позиция) + checksum
- [x] Embedding-адаптер (OpenAI-compatible POST /embeddings)
- [x] VectorStore: Qdrant + InMemory; коллекция на версию эмбеддинг-модели
- [x] Модели KnowledgeBase/Document/Chunk + миграция 0006
- [x] Worker document_ingest (parse→chunk→embed→Qdrant+DB), delete с очисткой векторов
- [x] API: /knowledge-bases (CRUD, upload document, query с цитатами)
- [x] LLM-синтез ответа с цитатами (chat_model_profile_id)
- [x] Порог релевантности → sufficient=false (не выдумывает источник)
- [x] UI: страница баз знаний (создание, загрузка, RAG-запрос с ответом)

### 7. Таблицы и OCR — ✅
- [x] CSV/XLSX schema preview (колонки, типы, первые строки, число строк)
- [x] DuckDB read-only sandbox: SELECT-only, enable_external_access=false, лимиты строк/ячеек
- [x] Модель получает schema/агрегаты, а не всю таблицу; запрещённый SQL отклоняется
- [x] Экспорт результата CSV/XLSX
- [x] API: /assets/{id}/table (preview/query/export), UI страница «Таблицы»
- [x] OCR-профиль для сканов PDF (tesseract+poppler в образе)

### 8. Release candidate — ✅ (частично)
- [x] Backup/restore drill (backup.sh + restore-verify прошли)
- [x] README.md заполнен фактическими командами/URL/функциями
- [x] README_staff.md — карта сервисов (порты, health, образы)
- [x] THIRD_PARTY_NOTICES.md обновлён (все зависимости и лицензии)
- [x] LICENSE (MIT)
- [x] Secret scan (gitleaks в CI) и ручная проверка: ключи не в Git
- [x] Нагрузочный smoke (30 параллельных version + 10 ready — все 200)
- [x] Миграции идемпотентны (alembic upgrade head, 0001→0007)
- [x] Celery beat — периодическая reconciliation (резервирования + задачи)
- [x] E2E Playwright (smoke: вход + навигация по разделам)
- [x] Windows clean install (проверен 2026-09-16, Windows + Docker Desktop 29.8,
      Windows PowerShell smoke-эквивалент зелёный; CRLF-prettier-regression
      исправлен общим `.gitattributes` `* text=auto eol=lf`)
- [ ] Live provider certification (RUN_LIVE_TESTS=1, отдельный бюджет)

## Определение готовности Этапа 1
Чистая установка по README, health, миграции, провайдеры, streaming chat,
бюджеты, RAG, таблицы — реализованы и покрыты unit/integration-тестами.
Windows clean install закрыт (2026-09-16). Из известных ограничений остаются
Live provider certification и host-E2E Playwright при Node <20 (см.
`docs/WINDOWS_HANDOFF.md`); ни то, ни другое не блокирует локальный запуск.

## Нефункциональные требования (частично)
- [x] Логи без секретов (redaction ключей в JSON-форматере)
- [x] Локальный bind по умолчанию (`APP_BIND_HOST=127.0.0.1`)
- [x] CORS только для собственного frontend
- [ ] Тесты провайдеров (fixtures/mock) — на срезе 2–3
- [ ] Backup/restore drill — скрипты есть, drill на срезе 8

## Известные ограничения
- SSE-аутентификация через query-параметр token (EventSource не умеет заголовки);
  для localhost приемлемо, для LAN нужно перейти на cookie или short-lived token.
- Event-буфер генераций — in-memory (однопроцессный MVP); при рестарте незавершённые
  генерации помечаются interrupted.
- Цены можно задать вручную или импортировать из API провайдера (sync-models,
  где провайдер отдаёт pricing; ручная цена имеет приоритет). Все стоимости
  считаются в базовой валюте бюджета с сохранением provenance
  (price_snapshot_id, fx_rate_id).
- OCR запускается только для страниц PDF без текстового слоя; ошибки OCR игнорируются.
- Windows: `.gitattributes` форсирует LF для всех текстовых файлов (`* text=auto
  eol=lf`). Для уже существующих checkout созданных до этого изменения нужно
  `git config core.autocrlf false` + пере-создать рабочее дерево (иначе prettier
  падает на 20 файлах из-за CRLF).
- Windows: bash-скрипты infra (`smoke.sh`, `health.sh`, backup/restore и др.)
  требуют Git Bash или WSL с `/bin/bash`; system32 `bash.exe` при наличии только
  служебного дистрибутива `docker-desktop` не работает. Работает PowerShell-
  эквивалент с командой `docker compose exec -T ...` (см. WINDOWS_HANDOFF).
- Windows: host-E2E Playwright требует Node.js 20+ (Playwright 1.63); при Node 18
  тест не запускается на хосте.
