#!/usr/bin/env bash
# Запуск бенчмарка LlamaIndex в одноразовом контейнере.
#
# Зачем контейнер: LlamaIndex тяжёлый и не должен попадать ни в образы проекта,
# ни в lock-файлы (ADR-0003, PROTOTYPE ONLY). Скрипт монтирует репозиторий
# read-write (results.json пишется рядом), ставит зависимости из requirements.txt
# и запускает benchmark.py с PYTHONPATH на packages/core.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

exec docker run --rm \
  -v "$REPO_ROOT":/work \
  -w /work/experiments/llamaindex_rag_benchmark \
  -e PYTHONPATH=/work/packages/core \
  python:3.12-slim \
  sh -c 'pip install -q -r requirements.txt && python benchmark.py --json results.json'
