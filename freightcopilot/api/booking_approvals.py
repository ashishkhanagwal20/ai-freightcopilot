from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from psycopg.types.json import Jsonb

from freightcopilot.config import KAFKA_BOOKING_TOPIC
from freightcopilot.database import get_db_connection

router = APIRouter(prefix="/approvals", tags=["Human approval"])


DbConnection = Annotated[
    psycopg.Connection,
    Depends(get_db_connection, scope="function"),
]


class BookingProposalRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    load_id: str = Field(min_length=1, max_length=80)
    carrier_id: str = Field(min_length=1, max_length=80)
    rate_usd: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    pickup_at: datetime
    delivery_at: datetime

    @model_validator(mode="after")
    def validate_schedule(self) -> "BookingProposalRequest":
        if self.pickup_at.utcoffset() is None:
            raise ValueError("pickup_at must include a timezone offset.")

        if self.delivery_at.utcoffset() is None:
            raise ValueError("delivery_at must include a timezone offset.")

        if self.pickup_at >= self.delivery_at:
            raise ValueError("delivery_at must be later than pickup_at.")

        return self


class BookingApprovalResponse(BaseModel):
    approval_id: UUID
    status: Literal["pending_approval", "approved", "rejected"]
    load_id: str
    carrier_id: str
    rate_usd: Decimal
    pickup_at: datetime
    delivery_at: datetime
    booking_id: UUID | None = None
    detail: str


def _to_response(
    row: tuple,
    *,
    detail: str,
    booking_id: UUID | None = None,
) -> BookingApprovalResponse:
    return BookingApprovalResponse(
        approval_id=row[0],
        load_id=row[1],
        carrier_id=row[2],
        rate_usd=row[3],
        pickup_at=row[4],
        delivery_at=row[5],
        status=row[6],
        booking_id=booking_id,
        detail=detail,
    )


def _fetch_approval(
    connection: psycopg.Connection,
    approval_id: UUID,
) -> tuple | None:
    return connection.execute(
        """
        SELECT
            approval.approval_id,
            approval.load_id,
            approval.carrier_id,
            approval.rate_usd,
            approval.pickup_at,
            approval.delivery_at,
            approval.status,
            booking.booking_id
        FROM booking_approvals AS approval
        LEFT JOIN mock_bookings AS booking
            ON booking.approval_id = approval.approval_id
        WHERE approval.approval_id = %s
        """,
        (approval_id,),
    ).fetchone()


@router.post(
    "/proposals",
    response_model=BookingApprovalResponse,
    status_code=201,
)
def create_booking_proposal(
    proposal: BookingProposalRequest,
    connection: DbConnection,
) -> BookingApprovalResponse:
    approval_id = uuid4()

    row = connection.execute(
        """
        INSERT INTO booking_approvals (
            approval_id,
            load_id,
            carrier_id,
            rate_usd,
            pickup_at,
            delivery_at,
            status
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'pending_approval')
        RETURNING
            approval_id,
            load_id,
            carrier_id,
            rate_usd,
            pickup_at,
            delivery_at,
            status
        """,
        (
            approval_id,
            proposal.load_id,
            proposal.carrier_id,
            proposal.rate_usd,
            proposal.pickup_at,
            proposal.delivery_at,
        ),
    ).fetchone()

    return _to_response(
        row,
        detail="Proposal saved. A human must approve it before booking.",
    )


@router.get(
    "/proposals",
    response_model=list[BookingApprovalResponse],
)
def list_pending_proposals(
    connection: DbConnection,
) -> list[BookingApprovalResponse]:
    rows = connection.execute("""
        SELECT
            approval.approval_id,
            approval.load_id,
            approval.carrier_id,
            approval.rate_usd,
            approval.pickup_at,
            approval.delivery_at,
            approval.status,
            booking.booking_id
        FROM booking_approvals AS approval
        LEFT JOIN mock_bookings AS booking
            ON booking.approval_id = approval.approval_id
        WHERE approval.status = 'pending_approval'
        ORDER BY approval.created_at DESC
        """).fetchall()

    return [
        _to_response(
            row[:7],
            detail="Waiting for human review.",
            booking_id=row[7],
        )
        for row in rows
    ]


@router.get(
    "/proposals/{approval_id}",
    response_model=BookingApprovalResponse,
)
def get_booking_proposal(
    approval_id: UUID,
    connection: DbConnection,
) -> BookingApprovalResponse:
    row = _fetch_approval(connection, approval_id)

    if row is None:
        raise HTTPException(status_code=404, detail="Approval proposal not found.")

    status = row[6]
    if status == "approved":
        detail = "Proposal was approved and the mock booking was created."
    elif status == "rejected":
        detail = "Proposal was rejected."
    else:
        detail = "Waiting for human review."

    return _to_response(row[:7], detail=detail, booking_id=row[7])


@router.post(
    "/proposals/{approval_id}/approve",
    response_model=BookingApprovalResponse,
)
def approve_booking_proposal(
    approval_id: UUID,
    connection: DbConnection,
) -> BookingApprovalResponse:
    row = connection.execute(
        """
        UPDATE booking_approvals
        SET status = 'approved', decided_at = now()
        WHERE approval_id = %s
          AND status = 'pending_approval'
        RETURNING
            approval_id,
            load_id,
            carrier_id,
            rate_usd,
            pickup_at,
            delivery_at,
            status
        """,
        (approval_id,),
    ).fetchone()

    if row is None:
        existing = _fetch_approval(connection, approval_id)

        if existing is None:
            raise HTTPException(
                status_code=404,
                detail="Approval proposal not found.",
            )

        if existing[6] == "approved":
            return _to_response(
                existing[:7],
                detail="Already approved; the existing mock booking is returned.",
                booking_id=existing[7],
            )

        raise HTTPException(
            status_code=409,
            detail="This proposal is no longer pending approval.",
        )

    booking_id = uuid4()

    connection.execute(
        """
        INSERT INTO mock_bookings (booking_id, approval_id)
        VALUES (%s, %s)
        """,
        (booking_id, approval_id),
    )

    event_id = uuid4()
    event_payload = {
        "event_id": str(event_id),
        "event_type": "booking.approved",
        "approval_id": str(approval_id),
        "booking_id": str(booking_id),
        "load_id": row[1],
        "carrier_id": row[2],
        "rate_usd": str(row[3]),
        "pickup_at": row[4].isoformat(),
        "delivery_at": row[5].isoformat(),
    }
    connection.execute(
        """
        INSERT INTO booking_outbox (
            event_id,
            aggregate_id,
            event_type,
            topic,
            payload
        )
        VALUES (%s, %s, 'booking.approved', %s, %s)
        """,
        (
            event_id,
            approval_id,
            KAFKA_BOOKING_TOPIC,
            Jsonb(event_payload),
        ),
    )

    return _to_response(
        row,
        detail="Approved. The mock booking record was created.",
        booking_id=booking_id,
    )


@router.post(
    "/proposals/{approval_id}/reject",
    response_model=BookingApprovalResponse,
)
def reject_booking_proposal(
    approval_id: UUID,
    connection: DbConnection,
) -> BookingApprovalResponse:
    row = connection.execute(
        """
        UPDATE booking_approvals
        SET status = 'rejected', decided_at = now()
        WHERE approval_id = %s
          AND status = 'pending_approval'
        RETURNING
            approval_id,
            load_id,
            carrier_id,
            rate_usd,
            pickup_at,
            delivery_at,
            status
        """,
        (approval_id,),
    ).fetchone()

    if row is not None:
        return _to_response(
            row,
            detail="Proposal rejected. No booking was created.",
        )

    existing = _fetch_approval(connection, approval_id)

    if existing is None:
        raise HTTPException(
            status_code=404,
            detail="Approval proposal not found.",
        )

    if existing[6] == "rejected":
        return _to_response(
            existing[:7],
            detail="Already rejected. No booking was created.",
        )

    raise HTTPException(
        status_code=409,
        detail="This proposal is no longer pending approval.",
    )
