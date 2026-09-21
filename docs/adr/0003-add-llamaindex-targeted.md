# ADR-0003: LlamaIndex — только прототип для оценочных экспериментов

- **Статус:** принято (PROTOTYPE ONLY)
- **Дата:** 2026-09-21

## Контекст
Текущий RAG реализован нативно: Qdrant-поиск, свой chunking, citations,
synthesis, порог `MIN_RELEVANCE`. Тестов качества retrieval нет. Появляется
идея использовать LlamaIndex как инструмент для evaluation и экспериментов,
но есть явный запрет заменять им текущий knowledge layer (см.
`IMPROVEMENT_TASKS_FOR_CODING_AI.md`, раздел 5).

## Текущее решение
LlamaIndex используется только в изолированном каталоге
`experiments/llamaindex_rag_benchmark/` для объективного сравнения:

- набор synthetic-документов с ожидаемыми ответами и цитатами;
- сравнение текущего RAG vs LlamaIndex по метрикам: recall@k, доля ответов
  с правильной цитатой, latency, RAM, сложность кода, удобство отладки;
- результат — decision report в `docs/IMPROVEMENTS_ASSESSMENT.md`.

В production runtime и в обязательные зависимости проект не добавляется.
Qdrant-хранилище, citations и synthesis не заменяются.

## Рассматриваемые варианты
1. Полная замена knowledge layer на LlamaIndex (отклонено: запрет в задании,
   риск потери контроля над citations и storage).
2. LlamaIndex только в experiments (выбран).
3. Лёгкий нативный benchmark на текущем pipeline без новых зависимостей
   (допустимая альтернатива, если experiments покажут отсутствие выгоды).

## Почему не выбран альтернативный путь
Вариант 1 теряет существующие, проверенные интеграцией сценарии (citations,
sufficient, хранилище на коллекцию-версию модели) и вносит тяжёлую зависимость.
Вариант 3 может оказаться достаточным, но не даёт «эталонного» сравнительного
реализации с альтернативным retriever/chunking — для этого и нужен эксперимент.

## Последствия
- Зависимость присутствует только в dev/experimental окружении; Docker-образ
  и runtime не растут.
- Риск «расползания» в production исключён соглашением: любые переносимыe
  улучшения (chunking/rerank/evaluation) внедряются нативно и отдельно.

## План rollback
Удаление каталога `experiments/llamaindex_rag_benchmark/` не влияет на
production-код и тесты.

## Влияние на Этап 2 (video generation)
Никакого: эксперимент не меняет runtime-зависимости и контракты
`Provider`, `Job`, `Asset`, `UsageRecord`, `BlobStore`.