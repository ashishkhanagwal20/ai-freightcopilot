from datetime import datetime
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from freightcopilot.schemas import Carrier


class FreightLoadRequest(BaseModel):
    """Validated load details supplied to the freight workflow."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    load_id: str = Field(min_length=1, max_length=80)
    equipment_type: str = Field(min_length=1, max_length=40)
    weight_lbs: int = Field(gt=0)
    hazmat: bool = False
    origin: str = Field(min_length=1, max_length=160)
    destination: str = Field(min_length=1, max_length=160)
    pickup_at: datetime
    delivery_at: datetime
    requested_carrier_id: str | None = Field(default=None, max_length=80)
    estimated_driving_hours_for_load: float | None = Field(
        default=None,
        ge=0,
    )
    driver_hours_driven_since_qualifying_rest: float | None = Field(
        default=None,
        ge=0,
    )
    driver_hours_since_last_30m_break: float | None = Field(
        default=None,
        ge=0,
    )
    break_scheduled_before_8_hour_limit: bool | None = None

    @model_validator(mode="after")
    def validate_schedule(self) -> "FreightLoadRequest":
        if self.pickup_at.utcoffset() is None:
            raise ValueError("pickup_at must include a timezone offset.")

        if self.delivery_at.utcoffset() is None:
            raise ValueError("delivery_at must include a timezone offset.")

        if self.pickup_at >= self.delivery_at:
            raise ValueError("delivery_at must be later than pickup_at.")

        return self


class FreightWorkflowInput(BaseModel):
    """Validated top-level input for a future multi-agent graph run."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    load_request: FreightLoadRequest


class MatchFinding(BaseModel):
    """One carrier-versus-load matching check."""

    check: Literal[
        "equipment",
        "weight",
        "hazmat",
        "pickup_notice",
    ]
    passed: bool
    detail: str


class MatchmakingResult(BaseModel):
    """Structured outcome from the matchmaking step."""

    status: Literal["eligible", "ineligible", "needs_review"]
    carrier: Carrier | None = None
    findings: list[MatchFinding] = Field(default_factory=list)


class ComplianceFinding(BaseModel):
    """One compliance finding with a traceable source."""

    rule_id: str | None = None
    severity: Literal["info", "review", "block"]
    detail: str
    source_ids: list[str] = Field(default_factory=list)


class ComplianceResult(BaseModel):
    """Structured outcome from the compliance step."""

    status: Literal["clear", "review", "blocked"]
    findings: list[ComplianceFinding] = Field(default_factory=list)


class NegotiationResult(BaseModel):
    """Rate recommendation produced before human booking approval."""

    status: Literal["not_started", "needs_review", "ready"]
    proposed_rate_usd: float | None = Field(default=None, gt=0)
    rationale: str | None = None


class FreightWorkflowState(TypedDict):
    """JSON-compatible state shared and checkpointed by LangGraph nodes."""

    question: str
    load_request: dict[str, Any]
    thread_id: str

    matchmaking_result: NotRequired[dict[str, Any]]
    compliance_result: NotRequired[dict[str, Any]]
    negotiation_result: NotRequired[dict[str, Any]]

    agent_result: NotRequired[dict[str, Any]]
    approval_decision: NotRequired[Literal["approved", "rejected"]]
