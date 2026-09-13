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

### 4. Usage, цены и бюджеты — ⬜
### 5. Jobs и Assets — ⬜
### 6. Документы и RAG — ⬜
### 7. Таблицы и OCR — ⬜
### 8. Release candidate — ⬜

## Нефункциональные требования (частично)
- [x] Логи без секретов (redaction ключей в JSON-форматере)
- [x] Локальный bind по умолчанию (`APP_BIND_HOST=127.0.0.1`)
- [x] CORS только для собственного frontend
- [ ] Тесты провайдеров (fixtures/mock) — на срезе 2–3
- [ ] Backup/restore drill — скрипты есть, drill на срезе 8

## Известные ограничения
- Celery-логи пока в дефолтном формате (JSON включу вместе с реальными задачами).
- OCR-профиль и таблицы (DuckDB) реализуются на срезах 6–7.
- Usage/бюджеты, jobs/assets — следующие срезы.
- SSE-аутентификация через query-параметр token (EventSource не умеет заголовки);
  для localhost приемлемо, для LAN нужно перейти на cookie или short-lived token.
- Event-буфер генераций — in-memory (однопроцессный MVP); при рестарте незавершённые
  генерации помечаются interrupted.
