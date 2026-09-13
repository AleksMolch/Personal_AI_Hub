#!/usr/bin/env bash
# backup.sh — создание резервной копии (PostgreSQL + assets + manifest).
# Valkey/Qdrant не считаются источником истины и не входят в базовый backup.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DIR="$ROOT/backups/backup-$STAMP"
mkdir -p "$DIR"

echo ">> Дамп PostgreSQL..."
docker compose exec -T postgres pg_dump -U app -d app -Fc > "$DIR/db.dump"

echo ">> Копирование assets..."
mkdir -p "$DIR/assets"
docker compose cp "api:/data/assets" "$DIR/assets" >/dev/null

echo ">> Фиксация версии приложения..."
APP_VERSION="$(docker compose exec -T api python -c 'from personal_hub.version import APP_VERSION; print(APP_VERSION)' 2>/dev/null || echo unknown)"

echo ">> Сбор manifest и checksums..."
{
  echo "{"
  echo "  \"format\": 1,"
  echo "  \"created_at\": \"$STAMP\","
  echo "  \"app_version\": \"$APP_VERSION\","
  echo "  \"db_sha256\": \"$(shasum -a 256 "$DIR/db.dump" | cut -d' ' -f1)\""
  echo "}"
} > "$DIR/manifest.json"

tar -czf "$DIR.tar.gz" -C "$ROOT/backups" "backup-$STAMP"
rm -rf "$DIR"

echo ">> Backup создан: $DIR.tar.gz"
