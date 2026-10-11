import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated
from uuid import UUID, uuid4

import psycopg
from confluent_kafka.admin import AdminClient
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel
from redis.exceptions import RedisError
from starlette.staticfiles import StaticFiles

from freightcopilot.agent import (
    answer_carrier_question,
    stream_carrier_question,
)
from freightcopilot.api.booking_approvals import router as approvals_router
from freightcopilot.cache import get_redis_client, retrieve_cached_chunks
from freightcopilot.config import (
    KAFKA_BOOKING_TOPIC,
    KAFKA_BOOTSTRAP_SERVERS,
    REDIS_CACHE_ENABLED,
)
from freightcopilot.database import connect_database, get_db_connection
from freightcopilot.extraction import extract_load_fields
from freightcopilot.generation import build_rag_prompt, stream_answer
from freightcopilot.graph import resume_agent_graph, run_agent_graph
from freightcopilot.schemas import AgentAnswer, AgentQuestion
from freightcopilot.freight_workflow import run_freight_workflow
from freightcopilot.workflow_schemas import FreightWorkflowInput


app = FastAPI(title="FreightCopilot")
logger = logging.getLogger(__name__)

app.include_router(approvals_router)
STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_PDF_UPLOAD_BYTES = 8 * 1024 * 1024
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


DbConnection = Annotated[
    psycopg.Connection,
    Depends(get_db_connection, scope="function"),
]


class GraphResumeRequest(BaseModel):
    approval_id: UUID


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/dependencies")
def dependency_health() -> dict:
    """Report local dependency availability without exposing connection data."""
    dependencies: dict[str, dict] = {
        "postgres": {"status": "unavailable"},
        "redis": {
            "status": "unavailable",
            "cache_enabled": REDIS_CACHE_ENABLED,
        },
        "kafka": {
            "status": "unavailable",
            "topic": KAFKA_BOOKING_TOPIC,
            "topic_exists": False,
        },
    }

    try:
        with connect_database() as connection:
            connection.execute("SELECT 1")
        dependencies["postgres"]["status"] = "ok"
    except Exception:
        pass

    try:
        get_redis_client().ping()
        dependencies["redis"]["status"] = "ok"
    except RedisError:
        pass

    try:
        admin = AdminClient({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})
        topics = admin.list_topics(timeout=3).topics
        dependencies["kafka"]["status"] = "ok"
        dependencies["kafka"]["topic_exists"] = (
            KAFKA_BOOKING_TOPIC in topics
        )
    except Exception:
        pass

    all_available = all(
        dependency["status"] == "ok"
        for dependency in dependencies.values()
    )
    return {
        "status": "ok" if all_available else "degraded",
        "dependencies": dependencies,
    }


@app.get("/events/recent")
def recent_booking_events(connection: DbConnection) -> list[dict]:
    """Show recent outbox delivery and consumer status for the dashboard."""
    rows = connection.execute(
        """
        SELECT
            outbox.event_id,
            outbox.event_type,
            outbox.topic,
            outbox.payload ->> 'load_id',
            outbox.payload ->> 'approval_id',
            outbox.payload ->> 'booking_id',
            outbox.created_at,
            outbox.published_at,
            outbox.attempts,
            outbox.last_error,
            processed.processed_at
        FROM booking_outbox AS outbox
        LEFT JOIN processed_booking_events AS processed
            ON processed.event_id = outbox.event_id
        ORDER BY outbox.created_at DESC
        LIMIT 10
        """
    ).fetchall()

    return [
        {
            "event_id": str(row[0]),
            "event_type": row[1],
            "topic": row[2],
            "load_id": row[3],
            "approval_id": row[4],
            "booking_id": row[5],
            "created_at": row[6].isoformat(),
            "published_at": row[7].isoformat() if row[7] else None,
            "attempts": row[8],
            "last_error": row[9],
            "processed_at": row[10].isoformat() if row[10] else None,
        }
        for row in rows
    ]


@app.get("/ask")
def ask(question: str, connection: DbConnection):
    evidence = retrieve_cached_chunks(question, connection)

    if not evidence:
        return PlainTextResponse(
            "I couldn't find supporting information in the documents."
        )

    prompt = build_rag_prompt(question, evidence)
    return StreamingResponse(
        stream_answer(prompt),
        media_type="text/plain",
    )


@app.post("/agent/ask", response_model=AgentAnswer)
async def ask_agent(request: AgentQuestion) -> AgentAnswer:
    return await answer_carrier_question(request.question)


@app.post(
    "/agent/ask/stream",
    response_class=EventSourceResponse,
)
async def ask_agent_stream(
    request: AgentQuestion,
) -> AsyncIterator[ServerSentEvent]:
    try:
        async for event_name, data in stream_carrier_question(request.question):
            yield ServerSentEvent(event=event_name, data=data)
    except Exception:
        yield ServerSentEvent(
            event="error",
            data={"message": "Agent request failed; check the API logs."},
        )


@app.post("/agent/graph/ask")
async def start_agent_graph(request: AgentQuestion) -> dict:
    thread_id = str(uuid4())

    result = await asyncio.to_thread(
        run_agent_graph,
        request.question,
        thread_id,
    )

    interrupts = result.get("__interrupt__", [])

    if interrupts:
        return {
            "status": "waiting_for_approval",
            "thread_id": thread_id,
            "interrupt": interrupts[0].value,
            "agent_result": result.get("agent_result"),
        }

    return {
        "status": "completed",
        "thread_id": thread_id,
        "agent_result": result.get("agent_result"),
    }


@app.post("/workflow/check-load")
async def check_load(request: FreightWorkflowInput) -> dict:
    """Run typed matchmaking and HOS checks for a submitted load."""
    return await asyncio.to_thread(run_freight_workflow, request)


@app.post("/extract/load-fields")
async def extract_pdf_load_fields(request: Request) -> dict:
    """Extract validated load fields from a selectable-text PDF upload."""
    pdf_content = bytearray()
    async for chunk in request.stream():
        pdf_content.extend(chunk)
        if len(pdf_content) > MAX_PDF_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail="PDF uploads must be 8 MB or smaller.",
            )

    if not pdf_content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=415,
            detail="Upload a valid PDF document.",
        )

    try:
        with TemporaryDirectory(prefix="freightcopilot-pdf-") as temp_dir:
            pdf_path = Path(temp_dir) / "upload.pdf"
            await asyncio.to_thread(pdf_path.write_bytes, bytes(pdf_content))
            extracted = await asyncio.to_thread(extract_load_fields, pdf_path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("PDF load-field extraction failed")
        raise HTTPException(
            status_code=502,
            detail=(
                "PDF extraction failed. Check the API logs, Gemini key, "
                "and model quota."
            ),
        ) from exc

    return extracted.model_dump(mode="json")


@app.post("/agent/graph/{thread_id}/resume")
async def resume_graph(
    thread_id: str,
    request: GraphResumeRequest,
) -> dict:
    try:
        result = await asyncio.to_thread(
            resume_agent_graph,
            thread_id,
            str(request.approval_id),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "status": result.get("approval_decision", "completed"),
        "thread_id": thread_id,
        "agent_result": result.get("agent_result"),
    }
