# Статус реализации

## Назначение и функции
Чек-лист требований Этапа 1 с актуальными статусами. Обновляется после каждой
итерации. Статусы: `не начато / в работе / готово / заблокировано`.

## Легенда
- ✅ готово · 🔄 в работе · ⬜ не начато · ⛔ заблокировано

## Вертикальные срезы

### 1. Репозиторий и локальный запуск — 🔄 (готово для MVP-скелета)
- [x] Монорепозиторий, Makefile, compose.yaml, `.env.example`
- [x] Сервисы web, api, worker, PostgreSQL, Valkey, Qdrant
- [x] `GET /api/v1/version`, `health/live`, `health/ready`
- [x] Alembic-миграции (авто и идемпотентно), structured JSON-логи
- [x] Healthchecks всех сервисов (проверено `docker compose up`)
- [x] Smoke-скрипт (`make smoke`)
- [ ] CI: lint/types/unit/build/secret-scan (конфиг создан, прогон в GitHub — при первом push)
- [ ] Windows/Linux clean install проверка

### 2. Авторизация и настройки — ⬜
- [ ] Local-first bootstrap admin
- [ ] Шифрование provider keys (мастер-ключ)
- [ ] CRUD provider + test connection + presets

### 3. Модели и streaming chat — ⬜
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
- OCR-профиль и таблицы (DuckDB) реализуются на срезах 6–7.
- Аутентификация (admin bootstrap) — следующий срез.
