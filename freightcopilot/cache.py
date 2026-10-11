import hashlib
import json
import logging
from functools import lru_cache

import psycopg
from redis import Redis
from redis.exceptions import RedisError

from freightcopilot.config import (
    EMBEDDING_MODEL,
    RAG_CACHE_TTL_SECONDS,
    RAG_CACHE_VERSION,
    REDIS_CACHE_ENABLED,
    REDIS_URL,
)
from freightcopilot.retrieval import retrieve_chunks
from freightcopilot.schemas import RetrievedChunk

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_redis_client() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)


def retrieve_cached_chunks(
    question: str,
    connection: psycopg.Connection,
    top_k: int = 2,
) -> list[RetrievedChunk]:
    """Cache dense retrieval results; fall back to Postgres if Redis is down.

    Bump RAG_CACHE_VERSION after changing or re-ingesting the corpus so older
    cached results are no longer used.
    """
    if not REDIS_CACHE_ENABLED:
        return retrieve_chunks(question, connection, top_k=top_k)

    normalized_question = " ".join(question.casefold().split())
    cache_material = (
        f"{RAG_CACHE_VERSION}|{EMBEDDING_MODEL}|{top_k}|"
        f"{normalized_question}"
    )
    digest = hashlib.sha256(cache_material.encode("utf-8")).hexdigest()
    cache_key = f"freightcopilot:retrieval:{digest}"

    try:
        cached_value = get_redis_client().get(cache_key)
    except RedisError as exc:
        logger.warning("Redis retrieval-cache read failed; using Postgres: %s", exc)
        cached_value = None

    if cached_value:
        try:
            cached_items = json.loads(cached_value)
            return [
                RetrievedChunk.model_validate(item)
                for item in cached_items
            ]
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Ignoring invalid Redis retrieval cache entry: %s", exc)
            try:
                get_redis_client().delete(cache_key)
            except RedisError:
                pass

    chunks = retrieve_chunks(question, connection, top_k=top_k)

    try:
        get_redis_client().setex(
            cache_key,
            RAG_CACHE_TTL_SECONDS,
            json.dumps(
                [chunk.model_dump(mode="json") for chunk in chunks]
            ),
        )
    except RedisError as exc:
        logger.warning("Redis retrieval-cache write failed: %s", exc)

    return chunks
