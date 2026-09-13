#!/usr/bin/env bash
# restore.sh — восстановление из резервной копии.
#   --verify : проверить целостность архива без изменения данных.
#   иначе    : восстановить БД и assets (требует подтверждения).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

VERIFY=0
if [[ "${1:-}" == "--verify" ]]; then
  VERIFY=1
  FILE="${2:-}"
else
  FILE="${1:-}"
fi

[[ -n "$FILE" ]] || { echo "Использование: restore.sh [--verify] FILE=/path/to/backup" >&2; exit 1; }
[[ -f "$FILE" ]] || { echo "Ошибка: файл не найден: $FILE" >&2; exit 1; }

echo ">> Проверка целостности архива..."
if ! tar -tzf "$FILE" >/dev/null 2>&1; then
  echo "Ошибка: архив повреждён." >&2
  exit 1
fi
TMP="$(mktemp -d)"
tar -xzf "$FILE" -C "$TMP"
CONTENT="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | head -n1)"

if [[ ! -f "$CONTENT/manifest.json" ]]; then
  echo "Ошибка: в архиве нет manifest.json." >&2
  rm -rf "$TMP"
  exit 1
fi

echo ">> Проверка checksum БД..."
DB_SHA="$(python3 -c "import json; print(json.load(open('$CONTENT/manifest.json'))['db_sha256'])")"
ACTUAL_SHA="$(shasum -a 256 "$CONTENT/db.dump" | cut -d' ' -f1)"
if [[ "$DB_SHA" != "$ACTUAL_SHA" ]]; then
  echo "Ошибка: checksum db.dump не совпадает." >&2
  rm -rf "$TMP"
  exit 1
fi
echo "   checksum ok"

if [[ "$VERIFY" -eq 1 ]]; then
  echo ">> Проверка завершена (данные не изменялись)."
  rm -rf "$TMP"
  exit 0
fi

# Подтверждение разрушающей операции.
read -r -p "Восстановление перезапишет текущие данные БД и assets. Продолжить? [y/N] " ans
[[ "$ans" =~ ^[Yy]$ ]] || { echo "Отменено."; rm -rf "$TMP"; exit 0; }

echo ">> Остановка сервисов записи..."
docker compose stop api worker web

echo ">> Восстановление PostgreSQL..."
docker compose up -d postgres
# Ожидание готовности postgres.
for i in $(seq 1 30); do
  docker compose exec -T postgres pg_isready -U app -d app >/dev/null 2>&1 && break
  sleep 1
done
docker compose exec -T postgres pg_restore -U app -d app --clean --if-exists < "$CONTENT/db.dump" \
  || docker compose exec -T postgres pg_restore -U app -d app < "$CONTENT/db.dump"

echo ">> Восстановление assets..."
docker compose cp "$CONTENT/assets" "api:/data" >/dev/null || true

echo ">> Перезапуск стека..."
docker compose up -d

rm -rf "$TMP"
echo ">> Восстановление завершено."
