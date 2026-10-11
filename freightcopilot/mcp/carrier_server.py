import httpx
from mcp.server import MCPServer

from freightcopilot.config import (
    CARRIER_API_BASE_URL,
    FREIGHTCOPILOT_API_BASE_URL,
)
from freightcopilot.schemas import BookingProposalToolResult, Carrier


mcp = MCPServer("Freight carrier and booking proposal tools")


@mcp.tool()
async def lookup_carrier(carrier_id: str) -> Carrier:
    """Look up carrier equipment, capacity, hazmat, and pickup notice details."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{CARRIER_API_BASE_URL}/carriers/{carrier_id}"
        )
        response.raise_for_status()
        return Carrier.model_validate(response.json())


@mcp.tool()
async def create_booking_proposal(
    load_id: str,
    carrier_id: str,
    rate_usd: float,
    pickup_at: str,
    delivery_at: str,
) -> BookingProposalToolResult:
    """Create a booking proposal that requires human approval.

    This only creates a pending approval proposal. It does not approve or book
    the load. Dates must be ISO-8601 strings with a timezone offset.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        carrier_response = await client.get(
            f"{CARRIER_API_BASE_URL}/carriers/{carrier_id}"
        )
        carrier_response.raise_for_status()
        Carrier.model_validate(carrier_response.json())

        proposal_response = await client.post(
            f"{FREIGHTCOPILOT_API_BASE_URL}/approvals/proposals",
            json={
                "load_id": load_id,
                "carrier_id": carrier_id,
                "rate_usd": rate_usd,
                "pickup_at": pickup_at,
                "delivery_at": delivery_at,
            },
        )
        proposal_response.raise_for_status()

    return BookingProposalToolResult.model_validate(
        proposal_response.json()
    )