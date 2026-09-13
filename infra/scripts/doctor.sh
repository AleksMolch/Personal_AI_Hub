#!/usr/bin/env bash
# doctor.sh — сбор диагностической информации без вывода секретов.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "== Personal AI Hub diagnostics =="
echo "-- docker compose ps --"
docker compose ps 2>&1 || true
echo
echo "-- версии образов --"
docker compose images 2>&1 || true
echo
echo "-- свободное место --"
df -h . | tail -n +1
echo
echo "-- health --"
"$ROOT/infra/scripts/health.sh" || true
echo
echo "-- конфигурация (redacted) --"
if [[ -f .env ]]; then
  # Выводим только имена переменных и наличие значений, не сами секреты.
  sed -E 's/(=.*)$/=<redacted>/' .env | grep -Ev '(MASTER_KEY|PASSWORD)' || true
  echo "(APP_MASTER_KEY / POSTGRES_PASSWORD скрыты)"
fi
