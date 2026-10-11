import argparse
from collections.abc import Callable

import psycopg

from freightcopilot.database import connect_database
from freightcopilot.documents import load_questions
from freightcopilot.retrieval import (
    retrieve_chunks,
    retrieve_hybrid_chunks,
    retrieve_reranked_chunks,
)
from freightcopilot.schemas import RetrievedChunk


Retriever = Callable[[str, psycopg.Connection], list[RetrievedChunk]]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare dense, hybrid BM25+dense, and optional reranked retrieval."
    )
    parser.add_argument(
        "--with-reranker",
        action="store_true",
        help=(
            "Load the local cross-encoder model. The first run may download "
            "its weights."
        ),
    )
    args = parser.parse_args()

    questions = load_questions()
    retrievers: list[tuple[str, Retriever]] = [
        (
            "dense",
            lambda query, connection: retrieve_chunks(
                query,
                connection,
                top_k=3,
            ),
        ),
        (
            "hybrid_bm25_dense_rrf",
            lambda query, connection: retrieve_hybrid_chunks(
                query,
                connection,
                top_k=3,
            ),
        ),
    ]

    if args.with_reranker:
        retrievers.append(
            (
                "hybrid_then_cross_encoder",
                lambda query, connection: retrieve_reranked_chunks(
                    query,
                    connection,
                    top_k=3,
                    candidate_k=5,
                ),
            )
        )

    with connect_database() as connection:
        for name, retrieve in retrievers:
            hit_at_1 = 0
            hit_at_3 = 0
            reciprocal_rank_sum = 0.0

            print(f"\n--- {name} ---")
            for item in questions:
                chunks = retrieve(item["question"], connection)
                ranked_sources = [chunk.source_id for chunk in chunks]
                expected_source = item["expected_document"]
                rank = next(
                    (
                        index
                        for index, source in enumerate(ranked_sources, start=1)
                        if source == expected_source
                    ),
                    None,
                )

                hit_at_1 += rank == 1
                hit_at_3 += rank is not None and rank <= 3
                reciprocal_rank_sum += 1 / rank if rank is not None else 0.0
                print(
                    f"Expected {expected_source}; retrieved {ranked_sources}; "
                    f"rank={rank}"
                )

            total = len(questions)
            mrr = reciprocal_rank_sum / total if total else 0.0
            print(f"Hit@1: {hit_at_1}/{total}")
            print(f"Hit@3: {hit_at_3}/{total}")
            print(f"MRR: {mrr:.4f} ({total} synthetic questions)")

    if len(questions) < 20:
        print(
            "\nNote: this is a small synthetic evaluation set. Treat the "
            "scores as a learning baseline, not a production-quality claim."
        )


if __name__ == "__main__":
    main()
