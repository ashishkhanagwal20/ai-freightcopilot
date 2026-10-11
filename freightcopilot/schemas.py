from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AgentAnswer(BaseModel):
    answer: str
    tool_name: str | None = None
    tool_arguments: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None
    approval_required: bool = False
    approval_id: str | None = None


class Carrier(BaseModel):
    carrier_id: str
    name: str
    equipment: list[str]
    max_weight_lbs: int
    hazmat_enabled: bool
    required_pickup_notice_hours: int


class BookingProposalToolResult(BaseModel):
    approval_id: str
    status: Literal["pending_approval", "approved", "rejected"]
    load_id: str
    carrier_id: str
    rate_usd: float
    pickup_at: str
    delivery_at: str
    booking_id: str | None = None
    detail: str


class RetrievedChunk(BaseModel):
    source_id: str
    document_id: str
    content: str
    similarity: float
    dense_rank: int | None = None
    sparse_rank: int | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
