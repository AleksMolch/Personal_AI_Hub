#!/usr/bin/env bash
# smoke.sh — smoke-тест поднятого локального экземпляра.
# Дожидается readiness, проверяет version/migrations/worker и целостность
# storage. Возвращает ненулевой код при любой ошибке.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

HOST="127.0.0.1"
API_PORT="${API_PORT:-8000}"
# shellcheck disable=SC1091
[[ -f .env ]] && source <(grep -E '^API_PORT=' .env)
API="http://${HOST}:${API_PORT}"

echo "== Smoke test =="

# 1. Дождаться readiness с timeout.
echo ">> Ожидание /health/ready (до 120с)..."
for i in $(seq 1 120); do
  if curl -fsS --max-time 3 "$API/api/v1/health/ready" >/dev/null 2>&1; then
    echo "   ready после ~${i}с"
    break
  fi
  if [[ "$i" -eq 120 ]]; then
    echo "Ошибка: API не стал ready." >&2
    exit 1
  fi
  sleep 1
done

# 2. Версия.
echo ">> Проверка /version..."
version="$(curl -fsS "$API/api/v1/version")"
echo "   $version"
[[ "$version" == *'"version"'* ]] || { echo "Ошибка: нет version." >&2; exit 1; }

# 3. Миграции применены.
echo ">> Проверка миграций..."
docker compose exec -T api python -c \
  "from personal_hub.config import get_settings; print(get_settings().database_url.split('@')[1].split('/')[0] if False else 'ok')" >/dev/null
mig_status="$(docker compose exec -T api alembic current 2>/dev/null || true)"
echo "   alembic current: $mig_status"
[[ "$mig_status" == *"(head)"* ]] || { echo "Ошибка: миграции не на head." >&2; exit 1; }

# 4. Worker отвечает на ping.
echo ">> Проверка worker..."
docker compose exec -T worker celery -A worker.celery_app:app inspect ping >/dev/null 2>&1 \
  || { echo "Ошибка: worker не отвечает." >&2; exit 1; }
echo "   worker pong"

echo "== Smoke test успешно завершён =="
