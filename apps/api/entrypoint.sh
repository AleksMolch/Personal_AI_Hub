#!/bin/sh
# Точка входа backend: применяет миграции, затем запускает API.
# Миграции идемпотентны (alembic upgrade head), поэтому перезапуск безопасен.
set -e

echo ">> Применяю миграции БД..."
alembic upgrade head

echo ">> Запускаю API на ${APP_BIND_HOST:-0.0.0.0}:8000"
exec uvicorn app.main:app --host "${APP_BIND_HOST:-0.0.0.0}" --port 8000 --proxy-headers
