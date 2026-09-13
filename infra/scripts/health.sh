#!/usr/bin/env bash
# health.sh — проверка health endpoints поднятого стека.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Хост и порт читаются из .env, иначе defaults.
HOST="127.0.0.1"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
# shellcheck disable=SC1091
[[ -f .env ]] && source <(grep -E '^(API_PORT|WEB_PORT)=' .env)

check() {
  local name="$1" url="$2"
  if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
    echo "  ok       $name ($url)"
    return 0
  else
    echo "  FAIL     $name ($url)" >&2
    return 1
  fi
}

echo "Health checks:"
failed=0
check "api live"  "http://${HOST}:${API_PORT}/api/v1/health/live" || failed=1
check "api ready" "http://${HOST}:${API_PORT}/api/v1/health/ready" || failed=1
check "web"       "http://${HOST}:${WEB_PORT}/api/health" || failed=1

if [[ "$failed" -ne 0 ]]; then
  echo "Некоторые проверки не прошли." >&2
  exit 1
fi
echo "Все проверки пройдены."
