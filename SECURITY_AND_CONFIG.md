# Безопасность, конфигурация и эксплуатационные ограничения

## Назначение и функции
Файл задает минимальную threat model, правила секретов, сетевого доступа, расходов и безопасной обработки пользовательских файлов.

## Основные активы
- API-ключи и master encryption key.
- История запросов и документы.
- Usage/cost данные.
- На Этапе 2 — исходные изображения и видео.

## Угрозы
- Публикация `.env` или ключа в логах.
- Неавторизованный LAN/Internet доступ.
- SSRF при импорте URL или скачивании provider result.
- Вредоносный PDF/Office файл, decompression bomb.
- Prompt injection из RAG-документа.
- Зацикленный retry и двойная платная генерация.
- Подмена webhook/replay.
- Перерасход вследствие устаревшей цены или валютного курса.

## Обязательные меры
- `.env`, backups, uploads и runtime volumes исключить из Git.
- Добавить secret scanning в pre-commit/CI (например, Gitleaks).
- Ключи шифровать authenticated encryption; master key не хранить в БД.
- Маскировать секреты в UI и логах.
- Local bind по умолчанию; CSRF/CORS/secure cookies при LAN.
- Rate limit на login, provider test, generations и upload.
- MIME sniffing, allowlist расширений, лимиты и timeout parser.
- Разбор документов в worker с ограничением CPU/RAM/времени.
- Запретить автоматическое исполнение содержимого документов и SQL модели вне ограниченного DuckDB workflow.
- Download внешнего media URL разрешать только HTTPS, с DNS/IP проверкой против localhost/private ranges, лимитом размера и redirect count.
- На Этапе 2 webhook: signature, timestamp tolerance, event id uniqueness.
- Idempotency key для submit; неизвестный timeout переводит job в `reconciliation_required`, а не повторяет списание.

## `.env.example`: обязательные группы
```dotenv
APP_ENV=production
APP_BIND_HOST=127.0.0.1
APP_BASE_URL=http://localhost:3000
APP_MASTER_KEY=CHANGE_ME_WITH_32_BYTE_RANDOM_SECRET
POSTGRES_PASSWORD=CHANGE_ME
DATABASE_URL=postgresql+asyncpg://app:${POSTGRES_PASSWORD}@postgres:5432/app
VALKEY_URL=redis://valkey:6379/0
QDRANT_URL=http://qdrant:6333
BLOB_STORE_DRIVER=local
BLOB_LOCAL_ROOT=/data/assets
RUN_LIVE_TESTS=0
LOG_LEVEL=INFO
```

Этот блок — шаблон, не рабочие секреты. Setup script должен генерировать случайные значения и проверять placeholder перед production startup.

## Политика бюджетов
- Hard limit проверяется транзакционно.
- До запроса создается cost reservation; после ответа она подтверждается/корректируется.
- Истекшие reservations освобождаются reconciliation job.
- Неизвестная цена блокирует запрос в strict mode или требует подтверждения пользователя.
- Для video выше порога всегда отдельный confirmation.

## Backup
Backup включает PostgreSQL dump, Qdrant snapshot, blob manifest/files и версию приложения. Valkey не считается источником истины. Restore сначала проверяется в отдельном namespace/volume. Скрипт не должен включать `.env` в незашифрованный архив.

## Публичная публикация проекта
- Собственный код лицензировать отдельно.
- Сформировать notices по фактическим dependency manifests и образам.
- Не копировать код сторонних UI без соблюдения их лицензий/branding.
- Не включать реальные provider fixtures с пользовательскими данными.
- В README явно указать: пользователь самостоятельно оплачивает API и соблюдает условия провайдеров.
