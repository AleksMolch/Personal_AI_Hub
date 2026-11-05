# Отчёт о проверках защищённых режимов

Назначение: зафиксировать фактические команды, окружение и результаты прогонов
на момент коммита. Отчёт обновляется каждым срезом; неподтверждённые проверки
отмечаются явно.

- Дата: 2026-10-19
- Окружение: Windows 10, Docker Desktop (Linux containers), PostgreSQL 16,
  Valkey 8, Python 3.12, Node 24, Playwright 1.63 (Chromium)
- База теста: изолированные контейнеры `infra/compose/test.yaml`

## 1. Backend: unit

```powershell
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=... python:3.12-slim `
  sh -c "pip install -q -r apps/api/requirements-dev.txt; pytest tests/unit -q"
```

Результат: **193 passed**. В том числе 20 тестов защиты (детектор, vault,
санитизация, восстановление, digest).

## 2. Backend: integration

```powershell
docker compose -f compose.yaml -f infra/compose/test.yaml run --rm test `
  sh -c "... alembic upgrade head; pytest tests/integration -q"
```

Результат: **97 passed**, включая:

- 8 тестов подготовки и vault (шифротекст, идемпотентность, отказы);
- 6 тестов гибридного чата (перехват payload, stale, подмена, cloud, local_only);
- 2 теста модели без цены (`cost_state=unknown`, `cost_amount=NULL`, бюджет не
  блокирует);
- 8 тестов HTTP-контракта prepare/commit.

Миграции: `alembic current` → `0010_usage_cost_nullable (head)`.

## 3. Frontend

```powershell
cd apps/web; npx tsc --noEmit; npx eslint .; npx prettier --check .
```

Результат: без ошибок.

## 4. E2E

```powershell
cd apps/web; npx playwright test
```

Результат: **9 passed, 1 skipped**. Пропущен `protection.spec.ts`: он требует
`PROTECTION_MODES_ENABLED=1` и настроенного провайдера и включается
`PROTECTION_E2E=1`. Отдельный прогон с флагом: **1 passed** (переключатель,
preview с `[EMAIL_1]`, отмена без отправки).

## 5. Линтеры и типы

```powershell
ruff check apps/api packages/core apps/worker   # All checks passed
mypy apps/api packages/core apps/worker         # no issues in 85 files
```

## 6. Известные ограничения проверок

- **Платные вызовы не выполнялись**: все провайдеры в тестах — mock HTTP.
  Это осознанно: AGENTS.md запрещает реальные платные API в обычных тестах.
- **`local_only` не проверен**: режим недоступен, локальный runtime не подключён.
- **Зависание тестов из-за окружения**: оставшиеся контейнеры `test-run` держали
  блокировки тестовой БД, из-за чего `TRUNCATE` в фикстуре ждал вечно. Лечится
  удалением зависших контейнеров (`docker kill`), а не изменением кода; тесты
  чтения SSE дополнительно ограничены таймаутом, чтобы сбой не вешал прогон.
- **Ручная правка sanitized-текста в preview** не реализована и не проверялась.

## 7. Команды для повторения

```powershell
make test-unit
make test-integration
make lint
make typecheck
cd apps/web; npx playwright test
PROTECTION_E2E=1 npx playwright test e2e/protection.spec.ts
```
