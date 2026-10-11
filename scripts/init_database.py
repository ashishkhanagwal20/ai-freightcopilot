from freightcopilot.database import connect_database


CREATE_DOCUMENT_CHUNKS_TABLE = """
CREATE TABLE IF NOT EXISTS document_chunks (
    id BIGSERIAL PRIMARY KEY,
    source_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    UNIQUE (document_id, chunk_index)
);
"""

CREATE_BOOKING_APPROVALS_TABLE = """
CREATE TABLE IF NOT EXISTS booking_approvals (
    approval_id UUID PRIMARY KEY,
    load_id TEXT NOT NULL,
    carrier_id TEXT NOT NULL,
    rate_usd NUMERIC(12, 2) NOT NULL CHECK (rate_usd > 0),
    pickup_at TIMESTAMPTZ NOT NULL,
    delivery_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('pending_approval', 'approved', 'rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at TIMESTAMPTZ,
    CHECK (pickup_at < delivery_at)
);
"""

CREATE_MOCK_BOOKINGS_TABLE = """
CREATE TABLE IF NOT EXISTS mock_bookings (
    booking_id UUID PRIMARY KEY,
    approval_id UUID NOT NULL UNIQUE
        REFERENCES booking_approvals (approval_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

CREATE_APPROVAL_STATUS_INDEX = """
CREATE INDEX IF NOT EXISTS booking_approvals_status_created_idx
ON booking_approvals (status, created_at DESC);
"""

CREATE_BOOKING_OUTBOX_TABLE = """
CREATE TABLE IF NOT EXISTS booking_outbox (
    event_id UUID PRIMARY KEY,
    aggregate_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    topic TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);
"""

CREATE_BOOKING_OUTBOX_PENDING_INDEX = """
CREATE INDEX IF NOT EXISTS booking_outbox_pending_created_idx
ON booking_outbox (created_at)
WHERE published_at IS NULL;
"""

CREATE_PROCESSED_BOOKING_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS processed_booking_events (
    event_id UUID PRIMARY KEY,
    approval_id UUID NOT NULL,
    booking_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


with connect_database() as connection:
    connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
    connection.execute(CREATE_DOCUMENT_CHUNKS_TABLE)
    connection.execute(CREATE_BOOKING_APPROVALS_TABLE)
    connection.execute(CREATE_MOCK_BOOKINGS_TABLE)
    connection.execute(CREATE_APPROVAL_STATUS_INDEX)
    connection.execute(CREATE_BOOKING_OUTBOX_TABLE)
    connection.execute(CREATE_BOOKING_OUTBOX_PENDING_INDEX)
    connection.execute(CREATE_PROCESSED_BOOKING_EVENTS_TABLE)

print("Database schema is ready, including approval and event-outbox tables.")
