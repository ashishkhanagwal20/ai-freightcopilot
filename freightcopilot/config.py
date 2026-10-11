import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

# Local settings come from the project-root .env file. Deployment environment
# variables can also be supplied by the runtime.
load_dotenv(PROJECT_ROOT / ".env", override=True)

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2",
)
RERANKER_MODEL = os.getenv(
    "RERANKER_MODEL",
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
)
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
REDIS_CACHE_ENABLED = os.getenv(
    "REDIS_CACHE_ENABLED",
    "false",
).strip().casefold() == "true"
RAG_CACHE_VERSION = os.getenv("RAG_CACHE_VERSION", "v1")
RAG_CACHE_TTL_SECONDS = int(os.getenv("RAG_CACHE_TTL_SECONDS", "300"))
KAFKA_BOOTSTRAP_SERVERS = os.getenv(
    "KAFKA_BOOTSTRAP_SERVERS",
    "127.0.0.1:9092",
)
KAFKA_BOOKING_TOPIC = os.getenv(
    "KAFKA_BOOKING_TOPIC",
    "freight.booking.approved",
)
GENERATION_MODEL = os.getenv(
    "GENERATION_MODEL",
    "gemini-3.5-flash-lite",
)
CARRIER_API_BASE_URL = os.getenv(
    "CARRIER_API_BASE_URL",
    "http://127.0.0.1:8001",
).rstrip("/")
FREIGHTCOPILOT_API_BASE_URL = os.getenv(
    "FREIGHTCOPILOT_API_BASE_URL",
    "http://127.0.0.1:8000",
).rstrip("/")


def get_database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError(
            "DATABASE_URL is missing from the environment or .env"
        )
    return value


def get_gemini_api_key() -> str:
    value = os.getenv("GEMINI_API_KEY")
    if not value:
        raise RuntimeError(
            "GEMINI_API_KEY is missing from the environment or .env"
        )
    return value
