#!/usr/bin/env bash
# bootstrap.sh — подготовка окружения и безопасная генерация .env.
# Проверяет Docker, создаёт .env со случайными секретами (если отсутствует)
# и собирает образы. Никогда не выводит секреты.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo ">> Проверка Docker..."
if ! docker info >/dev/null 2>&1; then
  echo "Ошибка: Docker не запущен или недоступен." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Ошибка: docker compose не найден." >&2
  exit 1
fi

if [[ -f .env ]]; then
  echo ">> Файл .env уже существует — пропускаю генерацию."
else
  echo ">> Генерирую .env со случайными секретами..."
  MASTER_KEY="$(openssl rand -hex 32)"
  PG_PASSWORD="$(openssl rand -hex 16)"
  sed \
    -e "s/^APP_MASTER_KEY=.*/APP_MASTER_KEY=${MASTER_KEY}/" \
    -e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${PG_PASSWORD}/" \
    .env.example > .env
  chmod 600 .env
  echo ">> .env создан (права 600)."
fi

echo ">> Проверяю, что секреты не остались placeholder..."
if grep -q "CHANGE_ME" .env; then
  echo "Ошибка: в .env остались placeholder CHANGE_ME. Замените их вручную." >&2
  exit 1
fi

echo ">> Сборка образов..."
docker compose build

echo ">> Готово. Запустите: make up"
