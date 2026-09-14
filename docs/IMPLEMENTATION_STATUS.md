# Статус реализации

## Назначение и функции
Чек-лист требований Этапа 1 с актуальными статусами. Обновляется после каждой
итерации. Статусы: `не начато / в работе / готово / заблокировано`.

## Легенда
- ✅ готово · 🔄 в работе · ⬜ не начато · ⛔ заблокировано

## Вертикальные срезы

### 1. Репозиторий и локальный запуск — ✅
- [x] Монорепозиторий, Makefile, compose.yaml, `.env.example`
- [x] Сервисы web, api, worker, PostgreSQL, Valkey, Qdrant
- [x] `GET /api/v1/version`, `health/live`, `health/ready`
- [x] Alembic-миграции (авто и идемпотентно), structured JSON-логи
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
- [x] Бюджет: дневной/месячный hard limit, резервирование до вызова (транзакционно)
- [x] Settlement после ответа; release при отмене/ошибке; ленивый reconcile просроченных
- [x] estimated vs actual (usage от провайдера → actual, иначе estimated)
- [x] Эндпоинты: /usage/summary, /usage/records (pagination), GET/PUT /budgets, GET/POST /prices
- [x] Интеграция с чатом: цена обязательна, бюджет блокирует до провайдера (402 BUDGET_EXCEEDED)
- [x] UI: dashboard расходов (день/месяц, токены, лимиты) + форма бюджета
- [ ] Reconciliation в отдельную фоновую задачу (сейчас лениво при резервировании)
- [ ] Импорт цен из API провайдера (сейчас manual)

### 5. Jobs и Assets — ✅
- [x] BlobStore: протокол + LocalBlobStore (put/open/delete, sha256, лимит размера)
- [x] Asset модель + загрузка/скачивание/удаление (download через авторизованный API)
- [x] Job state machine (централизованная валидация переходов)
- [x] Celery-задача run_job + heartbeat + идемпотентный повторный запуск
- [x] Reconciliation «мёртвых» задач (worker lost → retryable/failed)
- [x] API: /assets (upload/list/get/content/delete→job), /jobs (list/get/retry/cancel)
- [x] Удаление ассета через document_delete job (безопасно, идемпотентно)
- [x] UI: страница задач (статус, повтор, отмена)
- [ ] Периодический beat для reconciliation (сейчас лениво при чтении)
- [ ] Реальное наполнение document_ingest (срез 6)

### 6. Документы и RAG — ✅
- [x] Парсеры TXT/MD/PDF (pypdf)/DOCX (python-docx)
- [x] Чанкинг с overlap и локацией (страница/позиция) + checksum
- [x] Embedding-адаптер (OpenAI-compatible POST /embeddings)
- [x] VectorStore: Qdrant + InMemory; коллекция на версию эмбеддинг-модели
- [x] Модели KnowledgeBase/Document/Chunk + миграция 0006
- [x] Worker document_ingest (parse→chunk→embed→Qdrant+DB), delete с очисткой векторов
- [x] API: /knowledge-bases (CRUD, upload document, query с цитатами)
- [x] Порог релевантности → sufficient=false (не выдумывает источник)
- [x] UI: страница баз знаний (создание, загрузка, RAG-запрос)
- [ ] LLM-синтез ответа с цитатами (пока retrieval-only)
- [ ] OCR-профиль для сканов (срез 7)

### 7. Таблицы и OCR — ✅ (таблицы; OCR отложен)
- [x] CSV/XLSX schema preview (колонки, типы, первые строки, число строк)
- [x] DuckDB read-only sandbox: SELECT-only, enable_external_access=false, лимиты строк/ячеек
- [x] Модель получает schema/агрегаты, а не всю таблицу; запрещённый SQL отклоняется
- [x] Экспорт результата CSV/XLSX
- [x] API: /assets/{id}/table (preview/query/export), UI страница «Таблицы»
- [ ] OCR-профиль для сканов (отложен: требует OCR-движок, отдельное решение)

### 8. Release candidate — ✅ (частично)
- [x] Backup/restore drill (backup.sh + restore-verify прошли)
- [x] README.md заполнен фактическими командами/URL/функциями
- [x] README_staff.md — карта сервисов (порты, health, образы)
- [x] THIRD_PARTY_NOTICES.md обновлён (все зависимости и лицензии)
- [x] LICENSE (MIT)
- [x] Secret scan (gitleaks в CI) и ручная проверка: ключи не в Git
- [x] Нагрузочный smoke (30 параллельных version + 10 ready — все 200)
- [x] Миграции идемпотентны (alembic upgrade head, 0001→0006)
- [ ] Windows clean install (не проверялся на этой машине)
- [ ] E2E Playwright (настроен контракт, тесты — следующий этап)
- [ ] Live provider certification (RUN_LIVE_TESTS=1, отдельный бюджет)

## Определение готовности Этапа 1
Чистая установка по README, health, миграции, провайдеры, streaming chat,
бюджеты, RAG, таблицы — реализованы и покрыты unit/integration-тестами.
Невыполненными остаются Windows clean install и E2E Playwright (не блокируют
локальный запуск, отмечены выше).

## Нефункциональные требования (частично)
- [x] Логи без секретов (redaction ключей в JSON-форматере)
- [x] Локальный bind по умолчанию (`APP_BIND_HOST=127.0.0.1`)
- [x] CORS только для собственного frontend
- [ ] Тесты провайдеров (fixtures/mock) — на срезе 2–3
- [ ] Backup/restore drill — скрипты есть, drill на срезе 8

## Известные ограничения
- Celery-логи пока в дефолтном формате (JSON включу вместе с реальными задачами).
- OCR-профиль и таблицы (DuckDB) реализуются на срезах 6–7.
- SSE-аутентификация через query-параметр token (EventSource не умеет заголовки);
  для localhost приемлемо, для LAN нужно перейти на cookie или short-lived token.
- Event-буфер генераций — in-memory (однопроцессный MVP); при рестарте незавершённые
  генерации помечаются interrupted.
- Цены вводятся вручную (импорт из API провайдера — позже). Все стоимости считаются
  в базовой валюте бюджета с сохранением provenance (price_snapshot_id, fx_rate_id).
- Reconciliation задач — ленивая (при чтении), не периодическая (beat добавим позже).
- Отмена задачи работает для queued; cooperative cancel для running — в срезе 6.
- RAG возвращает цитаты (retrieval); LLM-синтез ответа — следующий срез.
- OCR-профиль для сканов PDF отложен (нужен OCR-движок — отдельное продуктовое решение).
