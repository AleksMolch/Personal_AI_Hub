# Задачи для coding-агента: критическая оценка и внедрение улучшений

## Назначение файла
Этот файл предназначен для ИИ, который пишет код приложения Personal AI Hub в VS Code. Он описывает задачи по усилению текущего проекта за счёт LiteLLM, RapidOCR, MarkItDown, Docling и точечного использования LlamaIndex.

Главное требование: **перед любыми изменениями в коде провести критическую оценку каждого улучшения и сравнить его с уже реализованным функционалом**. Нельзя внедрять библиотеку только потому, что она была рекомендована ранее.

## Контекст проекта
Текущее приложение уже имеет:

- собственный Next.js frontend;
- FastAPI backend;
- PostgreSQL;
- Valkey;
- Qdrant;
- Celery worker;
- OpenAI-compatible provider adapter;
- presets OpenRouter, RouterAI, Selectel;
- чат со streaming;
- provider/model management;
- usage, prices, budgets;
- asset upload/download;
- document ingest;
- RAG через Qdrant;
- таблицы через DuckDB;
- базу для OCR через Tesseract/pytesseract/pdf2image;
- Job/Asset/UsageRecord abstractions, подготовленные к будущему video generation.

Задача улучшений — **усилить существующую архитектуру без большой переделки**, не заменить уже работающий продукт другим фреймворком.

---

# 0. Обязательный предварительный этап: Technical Assessment

## Цель
Перед внедрением любой библиотеки провести критический audit и принять обоснованное решение: внедрять, отложить, отказаться или заменить меньшим изменением.

## Запрет
До завершения assessment запрещено:

- менять production-код;
- добавлять зависимости в lock/requirements/package files;
- переписывать текущие provider/RAG/document modules;
- менять публичные API;
- удалять существующий функционал.

Разрешено:

- читать код;
- запускать тесты;
- создавать analysis-документы;
- делать небольшие throwaway-прототипы в `experiments/`, если они не подключены к приложению.

## Задача 0.1 — провести ревизию текущей реализации

Проверить и описать текущее состояние:

1. Provider layer:
   - где реализован OpenAI-compatible adapter;
   - как хранятся provider credentials;
   - как работает `ProviderConnection`;
   - где происходит streaming;
   - где нормализуются ошибки;
   - где считаются usage и cost.

2. Billing layer:
   - какие внешние AI-вызовы уже проходят через budget reservation;
   - какие вызовы обходят billing;
   - есть ли отдельный путь для embeddings;
   - есть ли cost accounting для RAG synthesis.

3. Document ingest:
   - какие форматы реально поддерживаются;
   - как извлекается текст;
   - как устроен chunking;
   - где вызываются embeddings;
   - где сохраняются chunks и citations.

4. OCR:
   - где используется Tesseract;
   - есть ли end-to-end сценарий OCR → text → chunks → Qdrant → RAG;
   - какие типы PDF/изображений проходят;
   - какие тесты это подтверждают.

5. RAG:
   - как выполняется retrieval;
   - как работает synthesis;
   - есть ли reranking;
   - есть ли оценка достаточности источников;
   - есть ли тесты качества retrieval.

6. UI:
   - какие страницы уже есть;
   - какие настройки доступны пользователю;
   - где нужно добавить управление новыми возможностями.

## Задача 0.2 — создать документ оценки

Создать файл:

```text
docs/IMPROVEMENTS_ASSESSMENT.md
```

В нём для каждого кандидата указать:

```markdown
## <Название библиотеки>

### Что она должна усилить
...

### Что уже реализовано в проекте
...

### Дублирует ли она текущий функционал
Да/нет/частично. Объяснение.

### Пользовательская выгода
Конкретно: что изменится для пользователя.

### Инженерная выгода
Конкретно: что станет проще/надёжнее в коде.

### Риски
- зависимости;
- лицензия;
- размер Docker image;
- RAM/CPU;
- сложность поддержки;
- breaking changes;
- влияние на тесты.

### Альтернативы
Что можно сделать без добавления библиотеки.

### Решение
GO / NO-GO / DEFER / PROTOTYPE ONLY.

### Минимальный безопасный способ внедрения
...

### Критерии успеха
...
```

## Задача 0.3 — создать ADR по каждому принятому улучшению

Для каждого решения `GO` или `PROTOTYPE ONLY` создать ADR:

```text
docs/adr/XXXX-add-litellm.md
docs/adr/XXXX-add-rapidocr.md
docs/adr/XXXX-add-markitdown.md
docs/adr/XXXX-add-docling.md
docs/adr/XXXX-add-llamaindex-targeted.md
```

ADR должен содержать:

- контекст;
- текущее решение;
- рассматриваемые варианты;
- выбранное решение;
- почему не выбран альтернативный путь;
- последствия;
- план rollback;
- влияние на Этап 2 video generation.

---

# 1. Epic: LiteLLM

## Предварительная гипотеза
LiteLLM может усилить provider layer, fallback, совместимость с OpenRouter/RouterAI/Selectel, usage normalization и будущую маршрутизацию.

Но в проекте уже есть собственный OpenAI-compatible adapter и billing. Поэтому LiteLLM нельзя внедрять слепо как замену всего provider layer.

## Для чего конкретно нужен LiteLLM
Добавлять LiteLLM только если он решает хотя бы 2–3 реальные проблемы:

1. снижает количество самописного provider-кода;
2. улучшает compatibility с OpenRouter/RouterAI/Selectel;
3. даёт более стабильный streaming/usage parsing;
4. упрощает fallback между endpoints;
5. даёт proxy-режим для будущих providers;
6. помогает централизовать retry/rate-limit handling;
7. помогает в будущем video/multimodal routing, если официально поддерживается нужный API.

## Что сравнить с текущей реализацией
Проверить:

- текущий `openai_compatible.py`;
- текущий `ProviderAdapter` protocol;
- текущую нормализацию ошибок;
- текущий `billing.py`;
- текущий streaming SSE flow;
- текущие tests для provider adapter.

Сравнить:

| Критерий | Текущая реализация | LiteLLM | Вывод |
|---|---|---|---|
| streaming | | | |
| usage parsing | | | |
| fallback | | | |
| RouterAI/OpenRouter совместимость | | | |
| Selectel совместимость | | | |
| budget integration | | | |
| complexity | | | |
| testability | | | |

## Допустимые варианты внедрения

### Вариант A — LiteLLM как внешний proxy
Приложение вызывает локальный LiteLLM proxy, а LiteLLM ходит во внешние модели.

Плюсы:
- меньше изменений в backend;
- легко включить/выключить;
- можно оставить текущий adapter.

Минусы:
- ещё один сервис;
- ещё одно место конфигурации;
- billing всё равно должен оставаться в нашем backend.

### Вариант B — LiteLLM как внутренняя Python-библиотека
Backend вызывает LiteLLM library напрямую.

Плюсы:
- меньше инфраструктуры;
- можно инкапсулировать в adapter.

Минусы:
- сильнее связывает backend с LiteLLM;
- сложнее isolating failures;
- возможны breaking changes.

### Вариант C — не внедрять, усилить текущий adapter
Если текущий adapter проще и надежнее, не добавлять LiteLLM.

## Предпочтительный путь
Начать с **прототипа Варианта A** как optional profile:

```text
compose profile: litellm
provider_type: litellm_proxy
```

Не удалять текущий OpenAI-compatible adapter.

## Задачи реализации при GO

### Task 1.1 — прототип LiteLLM proxy profile
- Добавить optional compose service `litellm` только через profile.
- Не включать его по умолчанию.
- Создать `.env.example` секцию для optional LiteLLM.
- Настроить минимальный config с mock/local test endpoint.

### Task 1.2 — adapter `litellm_proxy`
- Добавить provider preset `LiteLLM Proxy`.
- Реализовать adapter как OpenAI-compatible wrapper к local LiteLLM URL.
- Не переносить туда budget logic.
- Все budget checks остаются в Personal AI Hub.

### Task 1.3 — fallback strategy assessment
- Проверить, не конфликтует ли fallback LiteLLM с нашим budget reservation.
- Запретить hidden fallback на более дорогую модель без явного price/capability profile.
- Если fallback меняет модель, UsageRecord должен сохранять фактическую модель.

### Task 1.4 — тесты
- Unit: adapter config.
- Contract: streaming response through LiteLLM mock.
- Integration: Personal AI Hub → LiteLLM mock → response.
- Negative: 401/429/5xx mapping.

### Acceptance criteria
- Текущий OpenAI-compatible adapter продолжает работать.
- LiteLLM отключен по умолчанию.
- Добавление LiteLLM не ломает budget pipeline.
- Документация объясняет, когда LiteLLM нужен, а когда нет.

### Rollback
Удаление/отключение profile `litellm` не должно затрагивать существующие providers.

---

# 2. Epic: RapidOCR

## Предварительная гипотеза
RapidOCR может улучшить качество OCR по сравнению с текущим Tesseract-only подходом и усилить RAG по сканам.

## Для чего конкретно нужен RapidOCR
- распознавание сканов PDF без text layer;
- распознавание изображений документов;
- повышение качества OCR для русского/английского текста;
- уменьшение мусора в chunks;
- улучшение качества RAG по отсканированным документам.

## Что сравнить с текущей реализацией
Проверить:

- есть ли сейчас полный OCR flow;
- где используется `pytesseract`;
- как `pdf2image` рендерит страницы;
- есть ли выбор OCR backend;
- как OCR ошибки отображаются в jobs;
- как текст из OCR попадает в chunking.

Сравнить на test fixtures:

1. чистый text-layer PDF;
2. скан PDF на русском;
3. скан PDF на английском;
4. фото документа;
5. плохое качество/шум.

Метрики:

- скорость на страницу;
- RAM peak, если возможно;
- доля распознанного текста;
- качество ручной выборки;
- количество пустых/мусорных chunks;
- стабильность в worker.

## Задачи реализации при GO

### Task 2.1 — OCR backend abstraction
Создать интерфейс:

```python
class OcrBackend(Protocol):
    name: str
    async def recognize_image(self, image_path: Path, languages: list[str]) -> OcrResult: ...
```

Текущий Tesseract завернуть в `TesseractOcrBackend`.

### Task 2.2 — RapidOCR backend
Добавить `RapidOcrBackend`.

Требования:
- lazy import;
- не грузить модели при старте API;
- запускать только в worker;
- timeout на страницу;
- ограничение размера изображения;
- понятная ошибка при отсутствии runtime/model dependency.

### Task 2.3 — OCR policy
Добавить настройки:

```text
OCR_BACKEND=tesseract|rapidocr|auto
OCR_LANGUAGES=rus,eng
OCR_MAX_PAGES=...
OCR_MAX_IMAGE_SIDE=...
```

Режим `auto`:
- сначала text layer;
- если текста мало — OCR;
- если RapidOCR недоступен — fallback на Tesseract.

### Task 2.4 — tests
- Unit: backend selection.
- Unit: fallback logic.
- Integration: fixture image/PDF → text extracted.
- Negative: OCR timeout, unsupported file, too many pages.

### Acceptance criteria
- OCR end-to-end подтвержден тестом: scan/image → text → document chunks → RAG citation.
- Tesseract продолжает работать без RapidOCR.
- RapidOCR не увеличивает idle RAM.
- Docker image size impact задокументирован.

### Rollback
Переменная `OCR_BACKEND=tesseract` полностью отключает RapidOCR path.

---

# 3. Epic: MarkItDown

## Предварительная гипотеза
MarkItDown может упростить document ingest, нормализуя разные форматы в Markdown/text.

## Для чего конкретно нужен MarkItDown
- единый нормализованный вход для chunking;
- меньше специальных parser branches;
- поддержка большего числа форматов;
- улучшение support/debugging ingest;
- более чистый intermediate representation.

## Что сравнить с текущей реализацией
Проверить:

- текущий `parsing.py`;
- какие форматы поддержаны;
- как сохраняется metadata;
- как обрабатываются ошибки;
- как парсятся PDF/DOCX/TXT/MD.

Сравнить MarkItDown с текущим парсером на fixtures:

- TXT;
- Markdown;
- DOCX с заголовками;
- PDF text layer;
- XLSX — только если не конфликтует с DuckDB table path.

## Важное ограничение
MarkItDown не должен заменить специализированный путь таблиц через DuckDB. CSV/XLSX для аналитики остаются в table module.

## Задачи реализации при GO

### Task 3.1 — parser strategy abstraction
Создать уровень:

```python
class DocumentParser(Protocol):
    name: str
    supports(file: AssetMetadata) -> bool
    parse(path: Path) -> ParsedDocument
```

Текущий парсер завернуть как `BuiltInParser`.

### Task 3.2 — MarkItDownParser
Добавить parser, который возвращает:

- normalized markdown/text;
- basic metadata;
- warnings;
- source format.

### Task 3.3 — parser routing
Настройки:

```text
DOCUMENT_PARSER=builtin|markitdown|auto
```

Режим `auto`:
- TXT/MD можно оставить builtin;
- DOCX/PDF можно попробовать MarkItDown;
- таблицы не переводить насильно в Markdown для table analysis.

### Task 3.4 — tests
- Golden fixtures: input file → expected extracted sections/text.
- Regression: текущие fixtures не ухудшились.
- Negative: unsupported/corrupt file returns safe job failure.

### Acceptance criteria
- MarkItDown optional.
- Builtin parser не удалён.
- Результат ingest воспроизводим и покрыт snapshot/golden tests.
- README объясняет, когда включать MarkItDown.

### Rollback
`DOCUMENT_PARSER=builtin` возвращает старое поведение.

---

# 4. Epic: Docling

## Предварительная гипотеза
Docling может улучшить parsing сложных PDF: структура, таблицы, layout.

## Для чего конкретно нужен Docling
- качественная обработка сложных PDF;
- сохранение структуры документа;
- лучшее выделение таблиц/секций;
- меньше мусорных chunks;
- повышение качества RAG по отчётам, инструкциям и научным PDF.

## Что сравнить с текущей реализацией
Сравнить на fixtures:

1. простой PDF;
2. сложный PDF с колонками;
3. PDF с таблицей;
4. PDF с заголовками/секциями;
5. плохой PDF, который должен корректно failed.

Оценить:

- качество структуры;
- скорость;
- RAM;
- Docker image size;
- сложность установки;
- лицензии зависимостей;
- конфликт с OCR/MarkItDown.

## Важное ограничение
Docling не должен стать mandatory dependency для базового запуска. Он должен быть optional enhanced parser.

## Задачи реализации при GO

### Task 4.1 — optional dependency profile
Сделать Docling дополнительным профилем:

```text
DOCUMENT_PARSER=docling|auto
COMPOSE_PROFILE=docling
```

или отдельный Docker image/profile, если зависимости тяжелые.

### Task 4.2 — DoclingParser
Реализовать parser adapter, который возвращает:

- sections;
- tables as markdown/html/text;
- page locations;
- warnings;
- extracted text.

### Task 4.3 — chunking by structure
Если parser возвращает structure, chunking должен использовать заголовки/секции, а не просто fixed-size split.

Не переписывать весь chunking. Добавить optional branch:

```text
if parsed_document.sections: section-aware chunking
else: current chunking
```

### Task 4.4 — tests
- Golden tests по structured PDF.
- Сравнение количества/качества chunks с текущим parser.
- Negative: Docling unavailable → fallback или понятная ошибка.

### Acceptance criteria
- Базовая установка без Docling не ломается.
- Сложный PDF показывает измеримое улучшение структуры.
- Потребление RAM/размер image задокументированы.
- Пользователь может выбрать enhanced parsing только осознанно.

### Rollback
Отключение Docling profile возвращает MarkItDown/builtin parser.

---

# 5. Epic: LlamaIndex — только точечно

## Предварительная гипотеза
LlamaIndex может быть полезен не как замена текущего RAG, а как точечный инструмент для evaluation, дополнительных retrievers или ingestion utilities.

## Запрет
Не заменять текущий knowledge layer на LlamaIndex полностью.
Не переносить весь RAG pipeline в LlamaIndex.
Не хранить отдельный дублирующий индекс без чёткого основания.

## Для чего конкретно можно использовать LlamaIndex
Допустимые точечные применения:

1. evaluation набора RAG-тестов;
2. optional reranking/retrieval experiment;
3. helper для structured node parsing, если это лучше текущего chunking;
4. тестовый benchmark текущего RAG против alternative retriever.

## Что сравнить с текущей реализацией
Проверить:

- текущий retrieval через Qdrant;
- chunking;
- citations;
- synthesis;
- tests quality.

Сравнить с LlamaIndex на фиксированном наборе документов:

- recall@k;
- доля ответов с правильной цитатой;
- latency;
- потребление RAM;
- сложность кода;
- удобство debugging.

## Задачи реализации при PROTOTYPE ONLY

### Task 5.1 — isolated benchmark
Создать:

```text
experiments/llamaindex_rag_benchmark/
```

Там допустимо использовать LlamaIndex для сравнения, но не подключать к production API.

### Task 5.2 — test dataset
Создать небольшой набор synthetic documents и expected answers/citations.

### Task 5.3 — decision report
Добавить в `docs/IMPROVEMENTS_ASSESSMENT.md`:

- улучшает ли LlamaIndex качество;
- что именно стоит перенести;
- стоит ли добавлять dependency;
- что можно реализовать без LlamaIndex.

## Возможный GO только если
LlamaIndex даёт доказуемое улучшение хотя бы в одном:

- качество retrieval;
- качество chunking;
- скорость разработки evaluation;
- снижение собственного кода.

И при этом:

- не дублирует Qdrant storage;
- не ломает citations;
- не увеличивает runtime RAM неприемлемо;
- не усложняет debugging.

## Acceptance criteria
До отдельного решения LlamaIndex остаётся только в `experiments/` или dev dependencies.

### Rollback
Удаление experiments не влияет на production.

---

# 6. Общие требования к тестам

Для каждого принятого улучшения обязательно:

## Unit tests
- selection logic;
- fallback logic;
- error handling;
- configuration validation.

## Integration tests
- полный путь через API/worker, если функция пользовательская;
- mock external provider, если есть API-вызов;
- DB records и job status.

## Regression tests
Подтвердить, что текущие сценарии не сломались:

```bash
make lint
make typecheck
make test-unit
make test-integration
make smoke
```

Если Docker недоступен, честно указать, что integration/smoke не подтверждены.

## Live tests
Запрещены по умолчанию.

```bash
RUN_LIVE_TESTS=1 LIVE_TEST_BUDGET=... make test-live
```

Live-тесты нельзя запускать без явного согласия пользователя.

---

# 7. Общие требования к документации

После каждого принятого улучшения обновить:

- `README.md` — что изменилось для пользователя;
- `README_staff.md` — эксплуатация, диагностика, rollback;
- `AI_MAINTENANCE.md` — как будущему ИИ сопровождать новую функцию;
- `THIRD_PARTY_NOTICES.md` — фактические лицензии и версии;
- `.env.example` — новые настройки;
- `docs/IMPLEMENTATION_STATUS.md` — статус и доказательства;
- `docs/NEXT_SESSION.md` — если остались хвосты.

Документация должна быть на русском языке.

---

# 8. Общие запреты

Запрещено:

- внедрять все библиотеки одновременно;
- переписывать текущий working provider layer без доказанной выгоды;
- заменять Qdrant другой vector DB;
- заменять текущий UI на Open WebUI/LibreChat/AnythingLLM;
- добавлять LangChain/Haystack/Unstructured как новый фундамент;
- делать обязательными тяжелые зависимости;
- увеличивать idle RAM без измерения;
- удалять текущие tests;
- запускать платные API без флага;
- ломать подготовку к Этапу 2 video jobs;
- реализовывать video generation в рамках этого файла задач.

---

# 9. Рекомендуемый порядок выполнения

## Статус итераций (актуально на 2026-10-07)

| Итерация | Решение | Где зафиксировано |
| --- | --- | --- |
| 1 — assessment only | ✅ закрыто | `docs/IMPROVEMENTS_ASSESSMENT.md` |
| 2 — RapidOCR (+ закрытие находок 0.7: billing gap, ошибки OCR, OCR-фикстуры) | ✅ закрыто | ADR-0002, `docs/NEXT_SESSION.md` п. 7 |
| 3 — LiteLLM prototype | ✅ закрыто (вариант A, внешний proxy) | ADR-0004, `docs/NEXT_SESSION.md` п. 7b |
| 4 — Docling enhanced parser | ⏸ DEFER, по одной задаче за раз | `docs/IMPROVEMENTS_ASSESSMENT.md` |
| 5 — LlamaIndex benchmark | ✅ закрыто (PROTOTYPE ONLY, production не затронут) | `experiments/llamaindex_rag_benchmark/`, decision report в `docs/IMPROVEMENTS_ASSESSMENT.md` |

Зелёные проверки после Итерации 5 + минорного прохода (2026-10-07): unit 93, integration 56, ruff,
mypy (66 файлов), tsc/eslint/prettier, `make smoke` (ready/version/alembic 0007
head/worker pong). Дополнительно исправлены дефекты предыдущей сессии: ingest
теперь помечает документ failed при сбоях провайдера/разбора (а не оставляет
pending), OCR рендерит только запрошенные страницы (без лишнего расхода RAM),
исправлен Base URL OpenRouter в примерах LiteLLM. Live provider certification
(`RUN_LIVE_TESTS=1`) — единственный пункт, который нельзя закрыть без реального
ключа и бюджета пользователя.

## Итерация 1 — assessment only
- Выполнить задачи 0.1–0.3.
- Ничего не менять в production-коде.
- Выдать go/no-go по каждому улучшению.

## Итерация 2 — RapidOCR или MarkItDown
Выбрать одно самое безопасное улучшение по итогам assessment.

Рекомендуемый кандидат: MarkItDown или RapidOCR, потому что они усиливают document pipeline и не меняют provider/billing ядро.

## Итерация 3 — LiteLLM prototype
Только optional profile/proxy. Без удаления текущего adapter.

Факт: выбран вариант A. Ключевой вывод замеров — библиотеку `litellm` в backend
ставить нельзя (+355,3 МБ образ, +178,5 МБ RSS на импорт). Proxy вынесен в
отдельный сервис под compose-профилем `litellm`.

## Итерация 4 — Docling enhanced parser
Только optional profile для сложных PDF.

## Итерация 5 — LlamaIndex benchmark
Только experiments/evaluation. Не production.

Факт (2026-10-07): создан `experiments/llamaindex_rag_benchmark/` (dataset +
benchmark + run.sh + README), LlamaIndex ставится только в одноразовый контейнер.
Результат: на синтетическом корпусе recall@k и top-1 совпадают с нативным
pipeline, MRR у нативного чуть выше, при этом LlamaIndex строит индекс ~14 раз
дольше и расходует на порядок больше Python-аллокаций. Вывод: dependency не
добавляется, улучшения переносить нечего; decision report — в
`docs/IMPROVEMENTS_ASSESSMENT.md` (раздел 5).

---

# 10. Definition of Done всего набора улучшений

Набор улучшений можно считать завершённым только если:

- есть `docs/IMPROVEMENTS_ASSESSMENT.md`;
- по каждому инструменту есть решение GO/NO-GO/DEFER;
- по каждому GO есть ADR;
- все новые зависимости зафиксированы и лицензии описаны;
- все изменения optional или имеют rollback;
- текущий чат, провайдеры, budgets, RAG и таблицы не сломаны;
- unit/integration/smoke тесты пройдены;
- пользовательская документация обновлена;
- future video architecture не нарушена.

---

# 11. Формат отчёта coding-агента после каждой итерации

```markdown
## Итерация N: <название>

### Что проверено
...

### Что изменено
...

### Почему это изменение оправдано
...

### Какие альтернативы отклонены
...

### Файлы
...

### Тесты
- command: ...
- result: ...

### Риски
...

### Rollback
...

### Следующий шаг
...
```

Если тесты не запускались, нельзя писать «готово». Нужно писать: «реализация не подтверждена тестами».
