"""Бенчмарк: нативный RAG Personal AI Hub против LlamaIndex (PROTOTYPE ONLY).

Назначение: в изоляции от production сравнить chunking+retrieval текущего
pipeline проекта и LlamaIndex на синтетическом наборе документов
(`dataset.json`) по объективным метрикам:

- recall@k по документу и по факту (факт обязан попасть в найденный чанк);
- MRR (первая позиция чанка ожидаемого документа);
- точность top-1 цитаты;
- отказ на неотвечаемых вопросах (порог `MIN_RELEVANCE`);
- latency запроса и пиковая RAM (tracemalloc) на этапе построения и запросов.

Границы эксперимента: LlamaIndex НЕ подключается к production API, НЕ заменяет
Qdrant/citations/synthesis и не входит в зависимости проекта. Оба pipeline
используют один и тот же локальный детерминированный hash-эмбеддинг (без
платных API), поэтому сравнение изолирует chunking/retrieval, а не качество
модели эмбеддингов. Для сравнения с LlamaIndex используется character-level
tokenizer и SentenceSplitter с теми же окнами 2000/200, что и у проекта.

Запуск (одноразовый контейнер, зависимости не попадают в проект):
    experiments/llamaindex_rag_benchmark/run.sh
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import statistics
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass
from pathlib import Path

# Те же константы, что в production-пайплайне: сравниваем при равных условиях.
from personal_hub.chunking import chunk_document
from personal_hub.knowledge import MIN_RELEVANCE
from personal_hub.parsing import TextPage
from personal_hub.vectorstore import InMemoryVectorStore, VectorPoint

HERE = Path(__file__).resolve().parent
DATASET_PATH = HERE / "dataset.json"

TOP_K = 5
CHUNK_CHARS = 2000
OVERLAP_CHARS = 200
EMBED_DIM = 256
_TOKEN_RE = re.compile(r"[a-zа-я0-9]+")


def embed_text(text: str) -> list[float]:
    """Детерминированный hash-эмбеддинг: bag-of-tokens со знаком, L2-норма.

    Детерминизм между запусками и процессами обеспечивается sha256 (встроенный
    hash() рандомизирован). Вектор общий для обоих pipeline, чтобы сравнение
    не зависело от внешней embedding-модели.
    """
    vector = [0.0] * EMBED_DIM
    for token in _TOKEN_RE.findall(text.lower()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % EMBED_DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


@dataclass
class QuestionOutcome:
    """Результат одного вопроса для одного pipeline."""

    id: str
    expected_document: str | None
    rank: int | None
    top1_document: str | None
    top1_score: float
    fact_found: bool
    refused: bool
    latency_ms: float


def _evaluate_question(
    question: dict,
    retrieved: list[tuple[str, str, float]],
    latency_ms: float,
) -> QuestionOutcome:
    """Считает метрики вопроса по списку (document_id, text, score)."""
    expected = question["expected_document"]
    if expected is None:
        # Неотвечаемый вопрос: корректный отказ — все хиты ниже порога.
        return QuestionOutcome(
            id=question["id"],
            expected_document=None,
            rank=None,
            top1_document=retrieved[0][0] if retrieved else None,
            top1_score=retrieved[0][2] if retrieved else 0.0,
            fact_found=False,
            refused=all(score < MIN_RELEVANCE for _, _, score in retrieved),
            latency_ms=latency_ms,
        )

    rank = None
    fact_found = False
    fact = (question["expected_fact"] or "").lower()
    for position, (document_id, text, _score) in enumerate(retrieved, start=1):
        if document_id != expected:
            continue
        if rank is None:
            rank = position
        if fact and fact in text.lower():
            fact_found = True
    return QuestionOutcome(
        id=question["id"],
        expected_document=expected,
        rank=rank,
        top1_document=retrieved[0][0] if retrieved else None,
        top1_score=retrieved[0][2] if retrieved else 0.0,
        fact_found=fact_found,
        refused=False,
        latency_ms=latency_ms,
    )


def _summarize(
    pipeline: str,
    outcomes: list[QuestionOutcome],
    chunks: int,
    build_ms: float,
    peak_ram_mb: float,
) -> dict:
    """Агрегирует метрики pipeline в отчётную структуру."""
    answerable = [o for o in outcomes if o.expected_document is not None]
    unanswerable = [o for o in outcomes if o.expected_document is None]
    latencies = [o.latency_ms for o in outcomes]

    def _rate(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 4) if denominator else 0.0

    return {
        "pipeline": pipeline,
        "chunks": chunks,
        "build_ms": round(build_ms, 2),
        "peak_ram_mb": round(peak_ram_mb, 2),
        "recall_doc_at_k": _rate(sum(o.rank is not None for o in answerable), len(answerable)),
        "recall_fact_at_k": _rate(sum(o.fact_found for o in answerable), len(answerable)),
        "mrr": round(
            statistics.fmean(
                [1.0 / o.rank if o.rank else 0.0 for o in answerable]
            )
            if answerable
            else 0.0,
            4,
        ),
        "top1_accuracy": _rate(
            sum(o.top1_document == o.expected_document for o in answerable), len(answerable)
        ),
        "refusal_accuracy": _rate(sum(o.refused for o in unanswerable), len(unanswerable)),
        "latency_ms_mean": round(statistics.fmean(latencies), 2) if latencies else 0.0,
        "latency_ms_p50": round(statistics.median(latencies), 2) if latencies else 0.0,
    }


async def run_current(dataset: dict, top_k: int) -> tuple[list[QuestionOutcome], dict]:
    """Текущий pipeline: chunk_document + InMemoryVectorStore (как в проекте)."""
    tracemalloc.start()
    started = time.perf_counter()
    store = InMemoryVectorStore()
    collection = "bench-current"
    await store.ensure_collection(collection, EMBED_DIM)

    points: list[VectorPoint] = []
    chunks_total = 0
    for document in dataset["documents"]:
        chunks = chunk_document(
            [TextPage(page=1, text=document["text"])], CHUNK_CHARS, OVERLAP_CHARS
        )
        chunks_total += len(chunks)
        for index, chunk in enumerate(chunks):
            points.append(
                VectorPoint(
                    id=f"{document['id']}#{index}",
                    vector=embed_text(chunk.text),
                    payload={"document_id": document["id"], "text": chunk.text},
                )
            )
    await store.upsert(collection, points)

    # Прогрев: первый поиск не должен попадать в замер latency.
    await store.search(collection, embed_text(dataset["questions"][0]["question"]), top_k)

    outcomes: list[QuestionOutcome] = []
    for question in dataset["questions"]:
        query_started = time.perf_counter()
        hits = await store.search(collection, embed_text(question["question"]), top_k)
        latency_ms = (time.perf_counter() - query_started) * 1000.0
        retrieved = [
            (str(hit.payload["document_id"]), str(hit.payload["text"]), hit.score)
            for hit in hits
        ]
        outcomes.append(_evaluate_question(question, retrieved, latency_ms))

    build_ms = (time.perf_counter() - started) * 1000.0
    peak_ram_mb = tracemalloc.get_traced_memory()[1] / 1024 / 1024
    tracemalloc.stop()
    summary = _summarize("current", outcomes, chunks_total, build_ms, peak_ram_mb)
    return outcomes, summary


def run_llamaindex(dataset: dict, top_k: int) -> tuple[list[QuestionOutcome], dict]:
    """LlamaIndex: SentenceSplitter(2000/200) + VectorStoreIndex (SimpleVectorStore)."""
    try:
        from llama_index.core import Document, StorageContext, VectorStoreIndex
        from llama_index.core.embeddings import BaseEmbedding
        from llama_index.core.node_parser import SentenceSplitter
        from llama_index.core.vector_stores import SimpleVectorStore
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        print(
            "LlamaIndex не установлен в этом окружении. Запустите "
            "experiments/llamaindex_rag_benchmark/run.sh или установите "
            f"requirements.txt вручную. Причина: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc

    class HashEmbedding(BaseEmbedding):
        """LlamaIndex-обёртка над общим hash-эмбеддингом (без платных API)."""

        def _get_query_embedding(self, query: str) -> list[float]:
            return embed_text(query)

        def _get_text_embedding(self, text: str) -> list[float]:
            return embed_text(text)

        async def _aget_query_embedding(self, query: str) -> list[float]:
            return embed_text(query)

        async def _aget_text_embedding(self, text: str) -> list[float]:
            return embed_text(text)

    tracemalloc.start()
    started = time.perf_counter()
    embed_model = HashEmbedding()
    # Character-level tokenizer: сравнение с char-окнами проекта при тех же
    # 2000/200 и без сетевой загрузки tiktoken-словаря.
    splitter = SentenceSplitter(
        chunk_size=CHUNK_CHARS,
        chunk_overlap=OVERLAP_CHARS,
        tokenizer=lambda text: list(text),
    )
    storage = StorageContext.from_defaults(vector_store=SimpleVectorStore())
    documents = [
        Document(text=document["text"], metadata={"document_id": document["id"]})
        for document in dataset["documents"]
    ]
    index = VectorStoreIndex.from_documents(
        documents,
        transformations=[splitter],
        storage_context=storage,
        embed_model=embed_model,
    )
    chunks_total = len(getattr(index.index_struct, "nodes_dict", {}))

    retriever = index.as_retriever(similarity_top_k=top_k)
    retriever.retrieve(dataset["questions"][0]["question"])  # прогрев

    outcomes: list[QuestionOutcome] = []
    for question in dataset["questions"]:
        query_started = time.perf_counter()
        nodes = retriever.retrieve(question["question"])
        latency_ms = (time.perf_counter() - query_started) * 1000.0
        retrieved = [
            (
                str(node.metadata.get("document_id", "")),
                node.text or "",
                float(node.score or 0.0),
            )
            for node in nodes
        ]
        outcomes.append(_evaluate_question(question, retrieved, latency_ms))

    build_ms = (time.perf_counter() - started) * 1000.0
    peak_ram_mb = tracemalloc.get_traced_memory()[1] / 1024 / 1024
    tracemalloc.stop()
    summary = _summarize("llamaindex", outcomes, chunks_total, build_ms, peak_ram_mb)
    return outcomes, summary


def _print_report(summaries: list[dict], outcomes: dict[str, list[QuestionOutcome]]) -> None:
    """Печатает сравнительную таблицу и расхождения по вопросам."""
    metrics = [
        ("chunks", "Чанков"),
        ("build_ms", "Построение, мс"),
        ("peak_ram_mb", "Пик RAM, МБ"),
        ("recall_doc_at_k", "recall@k (документ)"),
        ("recall_fact_at_k", "recall@k (факт)"),
        ("mrr", "MRR"),
        ("top1_accuracy", "top-1 цитата"),
        ("refusal_accuracy", "Отказ (неотвечаемые)"),
        ("latency_ms_mean", "Latency, мс (среднее)"),
        ("latency_ms_p50", "Latency, мс (медиана)"),
    ]
    names = [summary["pipeline"] for summary in summaries]
    print(f"\n=== RAG benchmark: {' vs '.join(names)} (k={TOP_K}) ===\n")
    header = f"{'Метрика':<26}" + "".join(f"{name:>14}" for name in names)
    print(header)
    print("-" * len(header))
    for key, label in metrics:
        row = f"{label:<26}" + "".join(f"{summary[key]:>14}" for summary in summaries)
        print(row)

    print("\nРасхождения по вопросам (там, где pipeline расходятся):")
    by_pipeline = {name: {o.id: o for o in items} for name, items in outcomes.items()}
    for question_id in by_pipeline[names[0]]:
        cells = [by_pipeline[name][question_id] for name in names]
        ranks = [cell.rank for cell in cells]
        facts = [cell.fact_found for cell in cells]
        refused = [cell.refused for cell in cells]
        if len(set(ranks)) > 1 or len(set(facts)) > 1 or len(set(refused)) > 1:
            parts = []
            for name, cell in zip(names, cells):
                if cell.expected_document is None:
                    parts.append(f"{name}: отказ={cell.refused}")
                else:
                    parts.append(
                        f"{name}: rank={cell.rank}, факт={cell.fact_found}, "
                        f"top1={cell.top1_document}"
                    )
            print(f"- {question_id}: " + "; ".join(parts))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=TOP_K, help="глубина retrieval")
    parser.add_argument("--json", type=Path, default=None, help="куда сохранить результаты")
    args = parser.parse_args()

    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    current_outcomes, current_summary = asyncio.run(run_current(dataset, args.k))
    llama_outcomes, llama_summary = run_llamaindex(dataset, args.k)

    outcomes = {"current": current_outcomes, "llamaindex": llama_outcomes}
    summaries = [current_summary, llama_summary]
    _print_report(summaries, outcomes)

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "dataset": dataset["name"],
                    "k": args.k,
                    "summaries": summaries,
                    "questions": {
                        name: [asdict(outcome) for outcome in items]
                        for name, items in outcomes.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nРезультаты сохранены: {args.json}")


if __name__ == "__main__":
    main()
