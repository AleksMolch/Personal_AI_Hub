# План разработки в два этапа

## Назначение и функции
Документ разбивает разработку на проверяемые вертикальные срезы. Каждый срез должен завершаться работающим сценарием, тестами и документацией.

# Этап 1 — языковые модели, файлы и RAG

## 1. Репозиторий и локальный запуск
- Создать монорепозиторий, Makefile, Compose, `.env.example`, version endpoint.
- Поднять web, API, worker, PostgreSQL, Valkey, Qdrant.
- Добавить migrations, healthchecks, structured logs.
- Создать CI: lint, types, unit, integration, build, secret/license scan.

**Приемка:** чистый clone запускается одной командой; health ready; volumes переживают restart.

## 2. Авторизация и настройки
- Local-first bootstrap admin.
- Settings UI и шифрование provider keys.
- CRUD provider и test connection.
- Presets OpenRouter, RouterAI, Selectel, generic OpenAI-compatible.

**Приемка:** ключ не возвращается/не логируется; неправильный ключ дает понятную ошибку; generic base URL тестируется mock server.

## 3. Модели и streaming chat
- Provider registry/capabilities.
- Sync/manual model profiles.
- Conversations/messages, SSE, cancel/retry, Markdown/code.
- Persist history, search/archive/delete, export MD/JSON.

**Приемка:** E2E с mock provider проходит создание чата, streaming, cancel, restart и экспорт.

## 4. Usage, цены и бюджеты
- UsageRecord, PriceSnapshot, FxRate, cost reservation.
- Dashboard и дневной/месячный hard limit.
- Импорт/ручное обновление цены с provenance.

**Приемка:** расчеты Decimal тестируются граничными значениями; budget блокирует до отправки; estimated не отображается как actual.

## 5. Унифицированные Jobs и Assets
- BlobStore local adapter, upload/download/delete.
- Job state machine, worker heartbeat, retry/cancel, reconciliation.
- UI jobs.

**Приемка:** потеря worker не оставляет job бесконечно running; повтор идемпотентен; удаление asset безопасно.

## 6. Документы и RAG
- Import TXT/MD/PDF/DOCX.
- Chunking, embeddings adapter, Qdrant index version.
- Knowledge base UI, query, citations.
- Удаление и reindex.

**Приемка:** фиксированный набор документов дает ожидаемые цитаты; низкая релевантность не выдумывает источник; embedding versions не смешиваются.

## 7. Таблицы и OCR
- CSV/XLSX schema preview и DuckDB analysis sandbox.
- Export CSV/XLSX.
- Опциональный OCR profile с лимитами и очередью.

**Приемка:** большая таблица не отправляется целиком модели; запрещенный SQL отклоняется; OCR failure не повреждает asset.

## 8. Release candidate Этапа 1
- Backup/restore drill.
- Windows/Linux clean install.
- Security review, dependency/license notices.
- Нагрузочный smoke, документация, upgrade test.

**Release gate:** все пункты Definition of Done в стартовом промпте и `TESTING.md` выполнены.

# Этап 2 — AI video через API

Начинать только после release gate Этапа 1.

## 9. Исследование и provider contracts
- Проверить официальные API/ToS/цены на дату реализации.
- Зафиксировать matrix capabilities для Veo, Seedance, Kling, Sora/OpenRouter.
- Создать ADR по каждому адаптеру и sanitized contract fixtures.

**Приемка:** ни один параметр/endpoint не выдуман; unsupported options скрыты UI.

## 10. AsyncGeneration adapters
- Submit/status/cancel/webhook adapters.
- Video request schema, idempotency, cost confirmation.
- Reconciliation неизвестных timeout.

**Приемка:** contract tests на queued/success/failure/rate limit/timeout; повтор не создает двойную платную job.

## 11. Получение и хранение результата
- Безопасное скачивание временного provider URL.
- Asset metadata и checksums.
- Lifecycle/quotas/cleanup.

**Приемка:** SSRF и oversized download заблокированы; истекающая ссылка сохраняется локально; delete чистит blob и DB.

## 12. Галерея и post-processing
- Video form по capabilities.
- Job progress, gallery, preview/download.
- FFprobe, thumbnail, MP4 faststart/нормализация через worker.

**Приемка:** пользователь проходит text/image-to-video с mock provider; исходник не теряется при ошибке FFmpeg.

## 13. Live provider certification
- Отдельные opt-in тесты каждого реального API с жестким budget cap.
- Проверить фактические webhook/polling, duration, MIME, стоимость.

**Приемка:** результаты и дата проверки задокументированы; unsupported provider помечен experimental.

## 14. Release candidate Этапа 2
- Backup/restore видео и jobs.
- Disk quota/lifecycle тесты.
- Cost dashboard по секундам/генерациям.
- Обновить README/README_staff/AI_MAINTENANCE.

# После MVP
Не включать без отдельного решения: timeline editor, совместная работа, SaaS billing, автономный auto-routing по «сложности», автоматический premium retry, локальный video inference.
