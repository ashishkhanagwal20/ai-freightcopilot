import math
import re
from collections import Counter
from functools import lru_cache

import psycopg
from sentence_transformers import CrossEncoder

from freightcopilot.config import RERANKER_MODEL
from freightcopilot.embeddings import get_embedding_model
from freightcopilot.schemas import RetrievedChunk


def retrieve_chunks(
    question: str,
    connection: psycopg.Connection,
    top_k: int = 2,
) -> list[RetrievedChunk]:
    query_embedding = get_embedding_model().encode(question)
    rows = connection.execute(
        """
        SELECT
            source_id,
            document_id,
            content,
            1 - (embedding <=> %s) AS similarity
        FROM document_chunks
        ORDER BY embedding <=> %s
        LIMIT %s
        """,
        (query_embedding, query_embedding, top_k),
    ).fetchall()

    return [
        RetrievedChunk(
            source_id=row[0],
            document_id=row[1],
            content=row[2],
            similarity=float(row[3]),
        )
        for row in rows
    ]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def _bm25_scores(
    query: str,
    documents: list[RetrievedChunk],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    """Compute BM25 scores over the current corpus rows."""
    tokenized_docs = [_tokenize(document.content) for document in documents]
    query_terms = set(_tokenize(query))

    if not tokenized_docs or not query_terms:
        return [0.0] * len(tokenized_docs)

    document_frequency: Counter[str] = Counter()
    term_frequencies: list[Counter[str]] = []

    for tokens in tokenized_docs:
        frequencies = Counter(tokens)
        term_frequencies.append(frequencies)
        document_frequency.update(frequencies.keys())

    average_length = sum(map(len, tokenized_docs)) / len(tokenized_docs)
    if average_length == 0:
        return [0.0] * len(tokenized_docs)

    scores: list[float] = []
    total_docs = len(tokenized_docs)

    for tokens, frequencies in zip(tokenized_docs, term_frequencies):
        document_length = len(tokens)
        score = 0.0

        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue

            doc_frequency = document_frequency[term]
            inverse_frequency = math.log(
                1.0
                + (total_docs - doc_frequency + 0.5)
                / (doc_frequency + 0.5)
            )
            denominator = frequency + k1 * (
                1.0 - b + b * document_length / average_length
            )
            score += (
                inverse_frequency
                * frequency
                * (k1 + 1.0)
                / denominator
            )

        scores.append(score)

    return scores


def retrieve_hybrid_chunks(
    question: str,
    connection: psycopg.Connection,
    top_k: int = 3,
    candidate_k: int = 20,
    rrf_k: int = 60,
) -> list[RetrievedChunk]:
    """Fuse dense pgvector and BM25 rankings with reciprocal-rank fusion.

    BM25 currently scores the corpus loaded from Postgres in-process. This is
    suitable for the synthetic learning corpus; at larger scale, move lexical
    scoring to a database/search index and measure before choosing it.
    """
    dense_results = retrieve_chunks(
        question,
        connection,
        top_k=candidate_k,
    )
    corpus_rows = connection.execute(
        """
        SELECT source_id, document_id, content
        FROM document_chunks
        """
    ).fetchall()
    corpus = [
        RetrievedChunk(
            source_id=row[0],
            document_id=row[1],
            content=row[2],
            similarity=0.0,
        )
        for row in corpus_rows
    ]

    if not corpus:
        return []

    dense_key = lambda chunk: (
        chunk.document_id,
        chunk.source_id,
        chunk.content,
    )
    corpus_by_key = {dense_key(chunk): chunk for chunk in corpus}
    dense_scores = {dense_key(chunk): chunk.similarity for chunk in dense_results}

    bm25_scores = _bm25_scores(question, corpus)
    sparse_indices = sorted(
        range(len(corpus)),
        key=lambda index: bm25_scores[index],
        reverse=True,
    )[:candidate_k]
    sparse_indices = [
        index for index in sparse_indices if bm25_scores[index] > 0
    ]

    dense_ranks = {
        dense_key(chunk): rank
        for rank, chunk in enumerate(dense_results, start=1)
    }
    sparse_ranks = {
        dense_key(corpus[index]): rank
        for rank, index in enumerate(sparse_indices, start=1)
    }

    candidate_keys = set(dense_ranks) | set(sparse_ranks)
    fused: list[RetrievedChunk] = []

    for key in candidate_keys:
        dense_rank = dense_ranks.get(key)
        sparse_rank = sparse_ranks.get(key)
        rrf_score = 0.0
        if dense_rank is not None:
            rrf_score += 1.0 / (rrf_k + dense_rank)
        if sparse_rank is not None:
            rrf_score += 1.0 / (rrf_k + sparse_rank)

        base_chunk = corpus_by_key[key]
        fused.append(
            base_chunk.model_copy(
                update={
                    "similarity": dense_scores.get(key, 0.0),
                    "dense_rank": dense_rank,
                    "sparse_rank": sparse_rank,
                    "rrf_score": rrf_score,
                }
            )
        )

    fused.sort(key=lambda chunk: chunk.rrf_score or 0.0, reverse=True)
    return fused[:top_k]


@lru_cache(maxsize=1)
def get_reranker() -> CrossEncoder:
    return CrossEncoder(RERANKER_MODEL)


def rerank_chunks(
    question: str,
    candidates: list[RetrievedChunk],
    top_k: int = 3,
) -> list[RetrievedChunk]:
    """Rerank retrieved candidates with a local cross-encoder model."""
    if not candidates:
        return []

    pairs = [(question, chunk.content) for chunk in candidates]
    scores = get_reranker().predict(pairs)
    reranked = [
        chunk.model_copy(update={"rerank_score": float(score)})
        for chunk, score in zip(candidates, scores)
    ]
    reranked.sort(
        key=lambda chunk: chunk.rerank_score or float("-inf"),
        reverse=True,
    )
    return reranked[:top_k]


def retrieve_reranked_chunks(
    question: str,
    connection: psycopg.Connection,
    top_k: int = 3,
    candidate_k: int = 20,
) -> list[RetrievedChunk]:
    candidates = retrieve_hybrid_chunks(
        question,
        connection,
        top_k=candidate_k,
        candidate_k=candidate_k,
    )
    return rerank_chunks(question, candidates, top_k=top_k)
