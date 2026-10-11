from functools import lru_cache

from sentence_transformers import SentenceTransformer

from freightcopilot.config import EMBEDDING_MODEL


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL)
