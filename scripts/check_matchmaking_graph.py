import json
from datetime import datetime, timedelta, timezone

from freightcopilot.freight_workflow import run_freight_workflow
from freightcopilot.workflow_schemas import (
    FreightLoadRequest,
    FreightWorkflowInput,
)


def main() -> None:
    pickup_at = datetime.now(timezone.utc) + timedelta(hours=48)
    delivery_at = pickup_at + timedelta(hours=8)

    workflow_input = FreightWorkflowInput(
        question="Check this load against the requested carrier.",
        load_request=FreightLoadRequest(
            load_id="LOAD-GRAPH-001",
            equipment_type="dry_van",
            weight_lbs=38_000,
            hazmat=False,
            origin="Chicago, IL",
            destination="Columbus, OH",
            pickup_at=pickup_at,
            delivery_at=delivery_at,
            requested_carrier_id="CARRIER-014",
            # Synthetic ELD/route values for this local demonstration.
            estimated_driving_hours_for_load=7.5,
            driver_hours_driven_since_qualifying_rest=2.0,
            driver_hours_since_last_30m_break=2.0,
            break_scheduled_before_8_hour_limit=True,
        ),
    )

    result = run_freight_workflow(workflow_input)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
