# ADR-0001: Монорепозиторий и технологический стек

- **Статус:** принято
- **Дата:** 2026-09-13

## Контекст
Нужно создать self-hosted платформу (Этап 1 — LLM/чат/документы/RAG),
которая на Этапе 2 добавит генерацию видео без переделки ядра. Требуется
единый стек, быстрый локальный запуск одной командой и расширяемость
провайдеров.

## Решение
- Монорепозиторий: `apps/web`, `apps/api`, `apps/worker`, `packages/core`,
  `packages/contracts` (TS-клиент из OpenAPI — на более позднем срезе),
  `infra`, `tests`, `docs`.
- Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic,
  httpx. Worker — Celery с Valkey-брокером.
- Данные: PostgreSQL (источник истины), Qdrant (векторы), Valkey (кэш/очередь).
- Blob-хранилище: интерфейс `BlobStore`, локальный filesystem по умолчанию.
- Frontend: Next.js (App Router, standalone), React, TypeScript strict.

## Ключевые решения по сборке и запуску
- Один backend-образ (`apps/api/Dockerfile`) обслуживает и `api`, и `worker`:
  они различаются только командой. Это убирает дублирование и упрощает общий
  доменный пакет.
- Общий Python-пакет `personal_hub` (в `packages/core`) подключается через
  `PYTHONPATH` в контейнере; миграции запускает только `api` (entrypoint),
  worker — нет. Это исключает гонку `alembic upgrade head`.
- Миграции выполняются автоматически перед стартом API (идемпотентно).

## Последствия
- Добавление видео-провайдеров на Этапе 2 не меняет Job/Asset/Usage и BlobStore.
- Модель данных с первого дня содержит `user_id` для будущего multi-user.

## Миграция / откат
- Схема БД управляется Alembic; откат — `alembic downgrade` только для
  reversible-миграций, при наличии backup.
