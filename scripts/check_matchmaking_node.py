import asyncio
import json
from datetime import datetime, timedelta, timezone

from freightcopilot.workflow_nodes import matchmaking_node
from freightcopilot.workflow_schemas import FreightLoadRequest


async def main() -> None:
    pickup_at = datetime.now(timezone.utc) + timedelta(hours=48)
    delivery_at = pickup_at + timedelta(hours=8)

    load_request = FreightLoadRequest(
        load_id="LOAD-MATCH-001",
        equipment_type="dry_van",
        weight_lbs=38_000,
        hazmat=False,
        origin="Chicago, IL",
        destination="Columbus, OH",
        pickup_at=pickup_at,
        delivery_at=delivery_at,
        requested_carrier_id="CARRIER-014",
    )

    state = {
        "question": "Check this load against the requested carrier.",
        "load_request": load_request.model_dump(mode="json"),
        "thread_id": "manual-matchmaking-check",
    }

    result = await matchmaking_node(state)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
