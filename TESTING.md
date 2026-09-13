# Тестирование, тестовые запуски и приемка

## Назначение и функции
Документ определяет обязательную пирамиду тестов, команды, фикстуры, smoke/live режимы и критерии выпуска. Coding-агент обязан адаптировать команды к созданному проекту, сохранив единый интерфейс Makefile.

## Обязательные команды
```bash
make bootstrap       # Проверка Docker, генерация безопасного .env, pull/build
make up              # Запуск основного профиля
make down            # Корректная остановка
make lint            # Ruff/ESLint/Prettier checks
make typecheck       # mypy + tsc
make test-unit       # Быстрые тесты без инфраструктуры
make test-integration
make test-e2e
make test             # Все бесплатные тесты
make smoke            # Проверка поднятого локального экземпляра
make logs             # Агрегированные логи
make backup
make restore FILE=...
```

Блок команд — публичный контракт для пользователя и CI. Реализация может использовать pnpm/uv/pytest, но пользователь не обязан помнить внутренние команды.

## Unit-тесты
Покрыть:
- state machine Job и запрещенные переходы;
- Decimal cost calculation, currency и budget reservation;
- capability routing;
- нормализацию provider errors;
- chunking/location metadata;
- validation upload/video parameters;
- webhook signature parser на Этапе 2.

Цель — не процент ради процента. Для критических модулей cost, budget, encryption, job state и provider normalization требуется branch coverage не ниже 90%; общий ориентир 80%.

## Integration-тесты
Поднимать изолированные PostgreSQL, Valkey, Qdrant и mock provider. Проверить:
- Alembic upgrade с нуля и upgrade с предыдущей fixture schema;
- транзакционный budget under concurrency;
- API → DB → worker → Qdrant → API;
- SSE order/heartbeat/disconnect/cancel;
- BlobStore lifecycle;
- retry и dead job recovery;
- backup manifest и тестовый restore.

## Contract-тесты провайдеров
Для каждого adapter хранить sanitized fixtures:
- успешный streaming response;
- usage в финальном chunk/отдельном ответе;
- 401, 402/insufficient balance, 429 с Retry-After, 5xx;
- malformed event и disconnect;
- list models variation.

Этап 2 дополнительно: submit, polling status, webhook, expired URL, unknown timeout, cancel unsupported.

## E2E Playwright Этапа 1
1. Первый запуск и создание администратора.
2. Добавление mock OpenAI-compatible provider.
3. Синхронизация/создание модели.
4. Чат со streaming и остановкой.
5. Сохранение после restart API/web.
6. Загрузка документа, наблюдение job, RAG-вопрос с цитатой.
7. Budget limit и блокировка запроса.
8. Экспорт диалога.
9. Проверка keyboard navigation ключевых экранов.

## E2E Этапа 2
1. Создание video job с mock provider.
2. Webhook success и polling fallback.
3. Скачивание, thumbnail, gallery.
4. Ошибка post-processing с сохранением исходника.
5. Confirmation дорогой генерации.
6. Неизвестный submit timeout не приводит к автоматическому дублю.

## Live-тесты
- По умолчанию `RUN_LIVE_TESTS=0`.
- Запуск только вручную: `RUN_LIVE_TESTS=1 LIVE_TEST_BUDGET=... make test-live`.
- Использовать минимально дорогую модель и короткий input/output.
- Перед каждым платным video test вывести верхнюю оценку и потребовать подтверждение.
- Никогда не запускать live-тесты на pull request из fork.
- Секреты брать только из CI secrets/environment.

## Smoke-тест после запуска
Smoke script должен:
- дождаться readiness с timeout;
- проверить version и migrations;
- создать временного mock provider/model;
- выполнить streaming chat;
- создать background job и дождаться completion;
- проверить storage write/read/delete;
- удалить тестовые данные;
- вернуть non-zero exit code при любой ошибке.

## Нагрузочные проверки
Этап 1: 3 одновременных streaming chats, 2 ingest jobs, 20 RPS внутренних read endpoints в течение 5 минут. Проверяются отсутствие OOM, потерянных jobs и нарушений budgets.

Этап 2: 10 одновременно ожидающих внешних video jobs не должны занимать worker slot постоянным polling; polling планируется отложенными задачами.

## Проверка документации
На чистой VM/машине выполнить команды исключительно из README. Все code blocks должны быть синтаксически валидны. Ссылки проверяются CI. Переменные `.env.example` сравниваются с реально читаемыми settings автоматически.

## Release checklist
- Все обязательные tests green.
- Нет high/critical dependency vulnerabilities без documented exception.
- Secret scan clean.
- License notices обновлены.
- Backup создан и restore проверен.
- Миграция с предыдущего релиза проверена.
- README и README_staff отражают фактические команды.
- Known issues опубликованы.
- Version/tag/changelog согласованы.
