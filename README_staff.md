# Руководство сопровождения Personal AI Hub

> Это обязательный шаблон для команды поддержки. Coding-агент заполняет фактические имена сервисов, команды, схемы и runbooks по мере реализации.

## Назначение и функции документа
Документ объясняет внутреннюю архитектуру, эксплуатацию, диагностику, миграции, backup/restore, инциденты, тесты и добавление провайдеров. Он не заменяет пользовательский README.

## Карта сервисов
| Сервис | Назначение | Порт (хост) | Health | Образ/версия |
| --- | --- | --- | --- | --- |
| `web` | Next.js UI, не владеет ключами | 3000 | `/api/health` | node:22-alpine, Next 16 |
| `api` | FastAPI: auth, providers, conversations, budgets, jobs, RAG | 8000 | `/api/v1/health/ready` | python:3.12-slim |
| `worker` | Celery: document ingest/embedding; Этап 2 — media | — | `celery inspect ping` | тот же backend-образ |
| `postgres` | источник истины | 5432 (внутр.) | `pg_isready` | postgres:16-alpine |
| `valkey` | broker, cache, locks с TTL | 6379 (внутр.) | `valkey-cli ping` | valkey/valkey:8-alpine |
| `qdrant` | embeddings | 6333 (внутр.) | `/readyz` | qdrant/qdrant:v1.15.4 |

Тома: `pgdata`, `valkeydata`, `qdrantdata`, `assets` (BlobStore, `/data/assets`).

Опциональные сервисы (не входят в `make up`, включаются профилем compose):

| Сервис | Назначение | Порт (хост) | Профиль | Команда |
| --- | --- | --- | --- | --- |
| `litellm` | внешний шлюз к моделям (ADR-0004) | 4000 | `litellm` | `make up-litellm` |
| `searxng` | локальный веб-поиск (ADR-0005) | 8888 | `search` | `make up-search` |

Зависимости: `api` зависит от postgres/valkey/qdrant (healthy); `web` — от `api`;
`worker` — от postgres/valkey/qdrant. Миграции применяет только `api` (entrypoint).

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
- Цена обязательна для всех платных путей: chat, embeddings (индексация и
  RAG-запрос) и RAG-синтез. Без `PriceSnapshot` индексация падает с
  `PRICE_REQUIRED` в статусе документа, RAG-запрос возвращает 400, синтез не
  вызывается. Если провайдер отдал usage, запись пишется как `actual`;
  при сбое после части выполненных батчей embeddings резерв финализируется
  по фактически обработанной части, а не отменяется целиком.

## OCR и распознавание документов
Общий интерфейс — `OcrBackend` (`packages/core/personal_hub/ocr.py`). Выбор
backend и лимиты задаются переменными окружения:

| Переменная | Назначение | По умолчанию |
| --- | --- | --- |
| `OCR_BACKEND` | `tesseract` \| `rapidocr` \| `auto` (RapidOCR при доступности, иначе Tesseract) | `tesseract` |
| `OCR_LANGUAGES` | языки tesseract через запятую | `rus,eng` |
| `OCR_MAX_PAGES` | максимум страниц OCR на документ; `0` — OCR отключён | `40` |
| `OCR_MAX_IMAGE_SIDE` | препроцессинг: сторона изображения не более лимита | `3500` |
| `OCR_MAX_IMAGE_PIXELS` | пиксельный лимит до декодирования (bomb-guard) | `50000000` |
| `OCR_PAGE_TIMEOUT_SECONDS` | таймаут распознавания страницы (> 0) | `30.0` |

Пояснения:
- RapidOCR (`rapidocr_onnxruntime`) **не входит** в базовые зависимости и ставится
  отдельно — lazy import, idle память не растёт. `OCR_BACKEND=tesseract` —
  полный rollback (ADR-0002).
- **Установка RapidOCR требует headless-OpenCV.** Пакет `rapidocr_onnxruntime`
  тянет `opencv-python`, которому нужен `libGL.so.1`; в `python:3.12-slim`
  его нет, и backend падает на импорте. Рабочий вариант (в порядке установки):
  ```bash
  pip install opencv-python-headless==4.11.0.86
  pip install --no-deps rapidocr_onnxruntime==1.4.4
  pip install onnxruntime==1.30.0 pyclipper==1.3.0.post6 Shapely==2.1.1 tqdm==4.67.1
  ```
  Если добавить `libgl1` в образ вместо headless-варианта, прирост образа
  вырастет примерно с +329 МБ до +665 МБ.
- Измеренные характеристики RapidOCR (A4 300 dpi, синтетическая страница):
  ~1,3–2,6 с на страницу и пик RAM ~0,8 ГБ против ~1,0 с и ~0,19 ГБ у
  Tesseract; качество распознавания этими числами не измеряется. Включать
  RapidOCR стоит точечно под сложные сканы, а не как замену Tesseract.
- Ошибки OCR не проглатываются: `OcrError` с кодами `OCR_UNAVAILABLE` /
  `OCR_FAILED` / `OCR_TIMEOUT` виден в статусе документа и job (`make logs
  SERVICE=worker`). В тексте ошибки `OCR_UNAVAILABLE` есть первопричина
  импорта (например, отсутствие `libGL.so.1`).
- Частичный сбой: если не распознана часть страниц, документ индексируется по
  успешным, получает `error_code=OCR_PARTIAL`, а коды страниц попадают в
  `warnings` задачи; если не распознана ни одна страница — документ `failed`.
- `OCR_MAX_PAGES=0` полностью отключает OCR: сканы PDF пропускаются
  (содержимое → `EMPTY_DOCUMENT`), изображения отклоняются с `OCR_DISABLED`.
- Изображение крупнее `OCR_MAX_IMAGE_PIXELS` отклоняется до декодирования с
  кодом `OCR_IMAGE_TOO_LARGE`; нормальные большие изображения уменьшаются до
  `OCR_MAX_IMAGE_SIDE`.
- OCR применяется к страницам PDF без текстового слоя и к загруженным
  изображениям (PNG/JPG/TIFF/WEBP/BMP).
- Интеграционные OCR-тесты используют детерминированный fake-backend, чтобы не
  зависеть от системного tesseract; живой путь проверяется и на пустой странице
  (`EMPTY_DOCUMENT`), и на странице с читаемым текстом: токен `VECTORSEARCH`
  должен доехать до чанков.

## Опциональный LiteLLM proxy (ADR-0004)

Локальный шлюз к моделям. Основной стек работает без него: сервис не входит
в `make up` и не качается без compose-профиля `litellm`. Библиотека `litellm`
в backend **не ставится** — новый тип провайдера использует тот же
OpenAI-compatible адаптер.

```bash
make up-litellm      # поднять proxy (нужны LITELLM_* в .env)
make down-litellm    # остановить
```

Включение в два шага:

1. Заполнить в `.env` (значения из `.env.example`):
   `LITELLM_MASTER_KEY`, `LITELLM_UPSTREAM_API_KEY`,
   `LITELLM_UPSTREAM_API_BASE`, `LITELLM_UPSTREAM_MODEL`.
2. `make up-litellm`, затем в UI выбрать пресет «LiteLLM Proxy
   (опционально)» и указать ключ прокси.

Пояснения:
- Проверка работоспособности: `curl http://127.0.0.1:4000/health/liveliness`
  → `I'm alive!`; `GET /v1/models` с ключом возвращает модели из
  `infra/litellm/config.yaml`.
- Образ закреплён: `ghcr.io/berriai/litellm:v1.104.0` (+383 МБ сжатых слоёв,
  качается только с профилем). Порт публикуется на `127.0.0.1` наружу не
  выставляется.
- Бюджет, цены и `UsageRecord` считает Personal AI Hub. Если прокси подменяет
  модель, тарификация всё равно идёт по вашему профилю цены — автоматический
  fallback на более дорогую модель не включайте.
- Точки интеграции — две: сервис `litellm` в `compose.yaml` и пресет
  `litellm_proxy` в `providers/presets.py` + `registry.py`. Их удаление не
  затрагивает существующих провайдеров.

## Live-сертификация провайдера
Проверяет боевой OpenAI-compatible провайдер крошечными запросами: health и
каталог моделей, непотоковый чат с фактическим usage, streaming и (опционально)
эмбеддинги. По умолчанию live-тесты выключены и никогда не запускаются в CI.

```bash
LIVE_TEST_BUDGET=0.05 make test-live
```

Что нужно (окружение или `.env`, файл в `.gitignore`):
- `LIVE_TEST_BUDGET` — обязательный лимит в USD (без него запуск падает);
- `LIVE_PROVIDER_API_KEY` — ключ провайдера (в логах не появляется);
- `LIVE_PROVIDER_TYPE` (по умолчанию `openrouter`) и `LIVE_PROVIDER_BASE_URL`
  (если у типа нет пресета);
- `LIVE_CHAT_MODEL` — дешёвая модель; `LIVE_EMBEDDING_MODEL` — для эмбеддингов;
- `LIVE_MAX_TOKENS` — лимит вывода (по умолчанию 256). Reasoning-моделям
  (DeepSeek Flash и подобным) 8 токенов не хватает: весь бюджет уходит в
  `reasoning_tokens`, и видимого текста не остаётся.

Пояснения:
- Бюджет проверяется ДО каждого платного вызова и списывается после по
  фактическому usage и прайсу модели; если провайдер не отдал прайс, резерв —
  0.01 USD за вызов. Число платных вызовов ограничено (по умолчанию 8).
- Промпты минимальны, `max_tokens=8`; тесты не запускаются при
  `RUN_LIVE_TESTS!=1`, то есть `make test-unit`/`test-integration` их не видят.
- После проверки ключ можно удалить из `.env`: он нужен только на время
  live-сессии.

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

## Веб-поиск (ADR-0005)
Опциональный локальный meta-поисковик SearXNG. Базовая установка работает без
него: сервис входит в отдельный compose-профиль `search`, а
`WEB_SEARCH_ENABLED` по умолчанию `0` — при этом переключатель «Веб» в чате не
рендерится (состояние сообщает `GET /api/v1/capabilities`).

```bash
make up-search       # поднять SearXNG (профиль search)
make down-search     # остановить
```

Порядок включения:

1. `make up-search`; проверить ответ:
   `curl "http://127.0.0.1:8888/search?q=test&format=json"` — должен вернуть JSON.
2. Задать в `.env`: `WEB_SEARCH_ENABLED=1`, `SEARXNG_URL=http://searxng:8080`.
3. Перезапустить api: `docker compose up -d api`, затем обновить страницу чата.

Пояснения:
- **Формат JSON у SearXNG выключен по умолчанию.** Он включён в
  `infra/searxng/settings.yml` (`search.formats: [html, json]`). Ответ 403
  означает, что конфигурация не подхватилась; backend вернёт код
  `WEB_SEARCH_FORBIDDEN` с этой подсказкой.
- Поиск бесплатный, поэтому `UsageRecord` для него не создаётся. Расходы
  контролируются объёмом контекста: `WEB_SEARCH_MAX_RESULTS` (по умолчанию 5) и
  `WEB_SEARCH_MAX_CONTEXT_CHARS` (2000) ограничивают текст, добавляемый во вход
  запроса, а оценка резерва считается по фактическому тексту вместе с
  контекстом.
- На сообщение выполняется **не более одного поиска**: автоматические
  «уточняющие» поиски со стороны модели не реализованы намеренно (аналог
  запрета на скрытый fallback).
- Поиск идёт **до** платного вызова: при сбое поиска API возвращает 502, и
  провайдер LLM не вызывается — это покрыто интеграционным тестом.
- Источники сохраняются в `messages.model_snapshot.web_search.citations`,
  поэтому переживают перезагрузку; миграция не требуется.
- Результаты поиска — недоверенный ввод: системная инструкция требует считать
  их данными и не выполнять найденные команды. При правке промпта это правило
  удалять нельзя.
- Часть движков может быть недоступна (CAPTCHA или блокировка IP) — это
  показывается предупреждением под источниками, а не скрывается.
- Лицензия SearXNG — AGPL-3.0-or-later. Проект обращается к сервису по сети и
  не распространяет изменённый образ; при сборке собственного модифицированного
  образа решение нужно пересмотреть.

## Глубина рассуждений (reasoning depth)
Селектор «Глубина» в чате рендерится **только** для моделей, объявивших
capability `reasoning` (провайдер сообщает это в `supported_parameters` ответа
`/models`). Для остальных моделей параметр не отправляется: часть провайдеров
отвечает на него ошибкой 400.

| Тип провайдера | Поле в теле запроса |
| --- | --- |
| `openrouter` | `reasoning: {"effort": "low\|medium\|high"}` |
| остальные OpenAI-совместимые | `reasoning_effort: "low\|medium\|high"` |

Пояснения:
- Отправляется ровно одно поле: порядок разрешения конфликта при отправке обоих
  не документирован провайдером.
- Значение для модели без capability отклоняется на API (400), поэтому селектор
  не может оказаться декоративным.
- Токены рассуждений тарифицируются как выходные и уже входят в
  `completion_tokens`. `parse_usage` читает их из вложенного
  `completion_tokens_details` **для справки** и никогда не прибавляет к
  выходным токенам: иначе стоимость считалась бы дважды.
- При глубине medium/high резерв бюджета считается по верхней границе вывода
  модели, иначе резерв оказался бы заниженным.

## Инциденты
Severity:
- SEV1: утечка ключей/данных, неконтролируемые списания, потеря данных.
- SEV2: недоступен основной пользовательский сценарий, массово stuck jobs.
- SEV3: отдельный provider/format не работает.

Для SEV1: остановить внешние вызовы, отозвать ключи, сохранить логи без секретов, оценить затраты/данные, выпустить postmortem.

## Definition of support handoff
Новый сотрудник/ИИ должен за 30 минут найти: topology, health, logs, migrations, backup, provider adapter, cost logic и known issues. Если не может — документ недостаточен и должен быть обновлен.
