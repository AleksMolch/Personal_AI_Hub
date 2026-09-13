# Руководство сопровождения Personal AI Hub

> Это обязательный шаблон для команды поддержки. Coding-агент заполняет фактические имена сервисов, команды, схемы и runbooks по мере реализации.

## Назначение и функции документа
Документ объясняет внутреннюю архитектуру, эксплуатацию, диагностику, миграции, backup/restore, инциденты, тесты и добавление провайдеров. Он не заменяет пользовательский README.

## Карта сервисов
- `web`: UI, не владеет API-ключами.
- `api`: auth, settings, conversations, budgets, jobs, OpenAPI.
- `worker`: document/OCR/embedding jobs; на Этапе 2 media jobs.
- `postgres`: источник истины.
- `valkey`: broker, cache, locks/reservations с TTL.
- `qdrant`: embeddings.
- `blob`: local/S3-compatible assets.

Агент должен дополнить ports, health endpoints, volumes, image versions и dependency graph из реального Compose.

## Потоки данных
### Chat
UI → API → budget reservation → provider adapter → SSE → message/usage persistence → reservation settlement.

Пояснение: reservation создается до внешнего вызова, чтобы параллельные запросы не обходили лимит. Финальный usage корректирует оценку.

### Document ingest
Upload → Asset → Job → parser → chunks → embeddings → Qdrant → Document ready.

Пояснение: PostgreSQL хранит статусы и provenance, Qdrant не является источником истины. Job должна быть возобновляемой/идемпотентной.

### Video — Этап 2
Request → price confirmation → reservation → submit → external id → webhook/poll → secure download → Asset → FFmpeg child job → gallery.

Пояснение: timeout после submit не означает, что задача не создана; она требует reconciliation, а не немедленного retry.

## Диагностические команды
```bash
make status
make health
make logs SERVICE=api
make logs SERVICE=worker
make doctor
```

Пояснение блока: `status/health` показывают состояние; адресный `logs` уменьшает шум; `doctor` собирает версии, свободное место и redacted конфигурацию. Команда doctor никогда не выводит ключи.

## Runbook: API не ready
1. Проверить PostgreSQL и миграции.
2. Проверить master key: изменение ключа делает сохраненные credentials нечитаемыми.
3. Проверить dependency health.
4. Найти request id/correlation id.
5. Не удалять volumes как «исправление».

## Runbook: worker/jobs
- Сравнить heartbeat и lock TTL.
- Проверить broker connectivity и очередь.
- Stale running job переводится recovery process в retryable/failed по политике типа.
- Для платной video job не использовать manual retry до reconciliation external id.

## Runbook: расходы
- Проверить cost state, price snapshot, валюту и fx rate.
- Сравнить provider request id с внешним кабинетом.
- Не менять старые usage records при обновлении прайса.
- Исправление выполняется reconciliation record/audit, а не silent overwrite.

## Миграции
```bash
make backup
make migrate-check
make migrate
make smoke
```

Пояснение блока: backup обязателен; check проверяет направление/совместимость; migrate применяет Alembic; smoke подтверждает пользовательский путь. Downgrade допустим только если миграция явно reversible и протестирована.

## Backup/restore
Перечислить фактический состав backup: PostgreSQL, Qdrant snapshot, blobs, manifest, app version. Valkey не обязателен. Restore проверять на отдельном volume до замены рабочего окружения.

```bash
make backup
make restore-verify FILE=/path/to/backup
make restore FILE=/path/to/backup
```

Пояснение блока: `restore-verify` валидирует checksum/version без изменения production; `restore` требует подтверждение и останавливает writes.

## Обновление
- Прочитать release notes и migrations.
- Создать backup.
- Обновить на staging/test profile.
- Запустить весь бесплатный test suite и smoke.
- Обновить production.
- Наблюдать errors/latency/jobs минимум один цикл.

## Логи и метрики
Обязательные поля: timestamp UTC, level, service, version, request_id, job_id, provider_type, error_code; запрещены secret, Authorization, полный приватный prompt/document. Метрики: request latency/errors, provider errors, queue depth, stale jobs, usage/cost, disk, Qdrant, backup age.

## Добавление LLM-провайдера
1. Проверить, нельзя ли использовать generic OpenAI-compatible adapter.
2. Добавить adapter только при реальном отличии контракта.
3. Реализовать capability mapping и error normalization.
4. Добавить sanitized contract fixtures.
5. Unit + integration + opt-in live test.
6. Обновить preset, notices и пользовательский README.

## Добавление video-провайдера — Этап 2
1. Зафиксировать официальную документацию/версию/ToS в ADR.
2. Реализовать submit/status/cancel/webhook только по реальному API.
3. Описать billing units и max-cost estimate.
4. Протестировать idempotency/unknown timeout/expired URL.
5. Провести live certification с минимальным бюджетом.

## Инциденты
Severity:
- SEV1: утечка ключей/данных, неконтролируемые списания, потеря данных.
- SEV2: недоступен основной пользовательский сценарий, массово stuck jobs.
- SEV3: отдельный provider/format не работает.

Для SEV1: остановить внешние вызовы, отозвать ключи, сохранить логи без секретов, оценить затраты/данные, выпустить postmortem.

## Definition of support handoff
Новый сотрудник/ИИ должен за 30 минут найти: topology, health, logs, migrations, backup, provider adapter, cost logic и known issues. Если не может — документ недостаточен и должен быть обновлен.
