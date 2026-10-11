# FreightCopilot

A learning project for freight-document RAG, MCP tools, streamed answers, and
human-approved agent workflows. The documents and carrier data are fictional.

## Project layout

```text
freightcopilot/          Reusable application package
  api/                   RAG API and mock carrier API
    static/              FastAPI-served dashboard (HTML, CSS, JavaScript)
  mcp/                   MCP tools backed by the mock carrier API
  config.py              Environment and model settings
  database.py            Shared Postgres connection setup
  documents.py           Document and evaluation-question loading
  embeddings.py          Cached sentence-transformer model
  retrieval.py           Dense, hybrid, fusion, and optional reranking
  cache.py               Optional Redis retrieval cache
  extraction.py          Gemini + Pydantic PDF field extraction
  generation.py          Gemini prompt and generation helpers
  schemas.py             Shared Pydantic models
scripts/                 Runnable learning and maintenance commands
data/                    Fictional source documents and evaluation questions
docs/                    Scratch questions and notes
learning.md              Concepts, decisions, and observations
docker-compose.yml       Local pgvector, Redis, and Kafka services
```

## Local setup

Create `.env` in the project root. Keep secrets out of source control.

```dotenv
DATABASE_URL=postgresql://freightcopilot:freightcopilot_dev@localhost:5433/freightcopilot
GEMINI_API_KEY=your_key_here
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
GENERATION_MODEL=gemini-3.5-flash-lite
CARRIER_API_BASE_URL=http://127.0.0.1:8001
```

Install the packages from `requirements.txt` in the active virtual environment.
Start the database from the project root:

```powershell
docker compose up -d
```

## Common commands

Run these from the project root with the virtual environment activated:

```powershell
python -m scripts.check_database
python -m scripts.init_database
python -m scripts.inspect_corpus
python -m scripts.ingest_documents
python -m scripts.evaluate_retrieval
python -m scripts.retrieve_demo "When is a driver required to take a break?"
python -m scripts.answer_demo "When is a driver required to take a break?"
```

Run the RAG API:

```powershell
python -m uvicorn freightcopilot.api.main:app --reload
```

Run the mock carrier API in a second terminal:

```powershell
python -m uvicorn freightcopilot.api.mock_carrier_api:app --reload --port 8001
```

With the mock carrier API running, check the MCP tool in another terminal:

```powershell
python -m scripts.check_mcp_tool
```

The MCP tool test is an in-memory SDK client call; the mock carrier API remains
a separate HTTP service. `/health` on the RAG API is available at
`http://127.0.0.1:8000/health`.

## Local dashboard

Start the RAG API and open `http://127.0.0.1:8000/` in your browser. The page
uses the existing same-origin API and provides:

- Streaming document Q&A with retrieved citations.
- A typed matchmaking and HOS check form at `POST /workflow/check-load`.
- A selectable-text PDF upload path at `POST /extract/load-fields`, returning
  Pydantic-validated JSON via Gemini.
- Agent SSE activity, including MCP tool calls and pending-proposal notices.
- A pending-approval inbox with explicit confirmation before approve/reject.
- A dependency panel for Postgres, Redis, Kafka, cache-enabled state, and the
  booking topic, backed by `GET /health/dependencies`.
- A recent-event monitor for the booking outbox and consumer status, backed by
  `GET /events/recent`.

Keep the mock carrier API running on port 8001 for load checks and carrier
tools. The HOS fields in the dashboard are synthetic demo inputs; they are not
live ELD values. Approving a proposal creates a mock booking and a Kafka
outbox event, just like the existing API workflow. The dashboard polls recent
event status every five seconds while it is open; the publisher and consumer
workers still need to be started separately in terminals.

PDF extraction accepts files up to 8 MB with selectable text. Scanned PDFs
need OCR, which is not implemented. The uploaded document text is sent to the
configured Gemini model; review extracted fields before using them.

## Hybrid retrieval evaluation

`freightcopilot/retrieval.py` keeps dense pgvector retrieval as the baseline
and adds a BM25 + dense reciprocal-rank-fusion path. The evaluation script
compares them on the synthetic questions. The reranker is optional because its
local cross-encoder weights download on first use:

```powershell
python -m scripts.ingest_documents
python -m scripts.evaluate_retrieval
python -m scripts.evaluate_retrieval --with-reranker
```

The corpus and evaluation set are synthetic and intentionally small. Record
the observed scores in `learning.md`; do not present them as production
quality metrics. The current BM25 implementation loads corpus text from
Postgres into the process, which is appropriate only for this small learning
corpus.

The RAGAS answer-quality evaluation is optional because it adds a larger
dependency tree and makes Gemini evaluation calls. Install it only when you
are ready to run the small, model-judged evaluation:

```powershell
python -m pip install -r requirements-evaluation.txt
python -m scripts.evaluate_rag_quality --limit 3
```

Use `--retriever dense`, `--retriever hybrid`, or `--retriever reranked` to
compare pipelines. The reranked option downloads the local cross-encoder the
first time it runs.

## Optional local Redis and Kafka

Redis caches retrieval results only when `REDIS_CACHE_ENABLED=true` is set in
`.env`. Cache keys include `RAG_CACHE_VERSION`; bump it after re-ingesting or
changing the corpus. Redis failure falls back to direct Postgres retrieval.

Kafka receives an event only after a human approves a proposal and the mock
booking is committed. The approval endpoint writes the booking and its outbox
event in the same Postgres transaction. A separate publisher sends pending
outbox records, and a consumer records each event once in
`processed_booking_events`. This is a single-node local learning setup, not a
production Kafka deployment.

After adding the service environment values from `.env.example` to `.env`, use
these commands when you are ready to start the support services:

```powershell
docker compose up -d redis kafka
python -m scripts.init_database
python -m scripts.setup_kafka_topic
```

Install the new Python clients in the active virtual environment:

```powershell
python -m pip install -r requirements.txt
```

Enable the cache by setting `REDIS_CACHE_ENABLED=true` in `.env` and restarting
the API. To run the Kafka consumer and outbox publisher, use separate
terminals:

```powershell
python -m scripts.consume_booking_events
python -m scripts.publish_booking_outbox
```

Approve a new proposal through the existing approval endpoint to create a
booking event. The publisher sends it to Kafka; the consumer records the
mock downstream effect once. Press `Ctrl+C` in each worker terminal to stop
the worker. The database, Redis, and Kafka containers can be inspected with
`docker compose ps` and their logs with `docker compose logs -f redis kafka`.

## Synthetic PDF extraction

The starter extractor handles PDFs with selectable text; scanned-image OCR is
not included. Create and extract the synthetic example with:

```powershell
python -m scripts.create_sample_rate_confirmation_pdf
python -m scripts.extract_load_pdf data/sample_rate_confirmation.pdf
```

Extracted values are Pydantic-validated JSON. Review the result before using
it to start a freight workflow; the extractor deliberately leaves ambiguous
values null instead of inferring them.
