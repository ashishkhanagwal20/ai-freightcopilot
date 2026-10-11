from datetime import datetime, timezone
from typing import Any

from mcp import Client

from freightcopilot.cache import retrieve_cached_chunks
from freightcopilot.database import connect_database
from freightcopilot.mcp.carrier_server import mcp
from freightcopilot.schemas import Carrier
from freightcopilot.workflow_schemas import (
    ComplianceFinding,
    ComplianceResult,
    FreightLoadRequest,
    FreightWorkflowState,
    MatchFinding,
    MatchmakingResult,
)


async def matchmaking_node(
    state: FreightWorkflowState,
) -> dict[str, Any]:
    """Check one requested carrier against the load's basic requirements."""
    load = FreightLoadRequest.model_validate(state["load_request"])
    carrier_id = load.requested_carrier_id

    if not carrier_id:
        raise ValueError(
            "Matchmaking requires load_request.requested_carrier_id."
        )

    async with Client(mcp) as client:
        tool_result = await client.call_tool(
            "lookup_carrier",
            {"carrier_id": carrier_id},
        )

    if tool_result.is_error:
        raise RuntimeError(
            f"Carrier lookup MCP tool failed: {tool_result.content}"
        )

    if tool_result.structured_content is None:
        raise RuntimeError(
            "Carrier lookup MCP tool returned no structured content."
        )

    carrier = Carrier.model_validate(tool_result.structured_content)

    equipment_matches = (
        load.equipment_type.casefold()
        in {item.casefold() for item in carrier.equipment}
    )
    weight_matches = load.weight_lbs <= carrier.max_weight_lbs
    hazmat_matches = not load.hazmat or carrier.hazmat_enabled

    now_utc = datetime.now(timezone.utc)
    pickup_utc = load.pickup_at.astimezone(timezone.utc)
    hours_until_pickup = (pickup_utc - now_utc).total_seconds() / 3600
    notice_matches = (
        hours_until_pickup >= carrier.required_pickup_notice_hours
    )

    findings = [
        MatchFinding(
            check="equipment",
            passed=equipment_matches,
            detail=(
                f"Load requires {load.equipment_type}; carrier equipment is "
                f"{', '.join(carrier.equipment)}."
            ),
        ),
        MatchFinding(
            check="weight",
            passed=weight_matches,
            detail=(
                f"Load weight is {load.weight_lbs:,} lbs; carrier maximum is "
                f"{carrier.max_weight_lbs:,} lbs."
            ),
        ),
        MatchFinding(
            check="hazmat",
            passed=hazmat_matches,
            detail=(
                "Carrier supports hazmat loads."
                if hazmat_matches and load.hazmat
                else (
                    "Load is not hazmat."
                    if hazmat_matches
                    else "Load is hazmat, but carrier is not hazmat-enabled."
                )
            ),
        ),
        MatchFinding(
            check="pickup_notice",
            passed=notice_matches,
            detail=(
                f"Pickup is in {hours_until_pickup:.1f} hours; carrier "
                f"requires {carrier.required_pickup_notice_hours} hours "
                "of notice."
            ),
        ),
    ]

    eligible = all(finding.passed for finding in findings)

    result = MatchmakingResult(
        status="eligible" if eligible else "ineligible",
        carrier=carrier,
        findings=findings,
    )

    return {"matchmaking_result": result.model_dump(mode="json")}


def compliance_node(state: FreightWorkflowState) -> dict[str, Any]:
    """Retrieve HOS evidence and check only the policy's supported limits."""
    load = FreightLoadRequest.model_validate(state["load_request"])

    retrieval_query = (
        "Hours-of-service policy for a driver's scheduled freight delivery. "
        f"Load travels from {load.origin} to {load.destination}. "
        f"Pickup is {load.pickup_at.isoformat()} and delivery is "
        f"{load.delivery_at.isoformat()}. Find relevant driving-hour limits, "
        "required breaks, and rest-period rules."
    )

    with connect_database() as connection:
        retrieved_chunks = retrieve_cached_chunks(
            retrieval_query,
            connection,
            top_k=3,
        )

    # This starter corpus labels the fictional HOS document as "hos_policy".
    # Keep only that document so unrelated carrier or booking text is not
    # presented as HOS evidence.
    hos_chunks = [
        chunk
        for chunk in retrieved_chunks
        if chunk.document_id == "hos_policy"
    ]

    source_ids = sorted({chunk.source_id for chunk in hos_chunks})
    findings: list[ComplianceFinding] = []

    if not hos_chunks:
        findings.append(
            ComplianceFinding(
                rule_id="HOS-EVIDENCE-MISSING",
                severity="review",
                detail=(
                    "No HOS policy evidence was retrieved. A human must "
                    "review compliance before booking."
                ),
                source_ids=[],
            )
        )
    else:
        missing_inputs = [
            field_name
            for field_name in (
                "estimated_driving_hours_for_load",
                "driver_hours_driven_since_qualifying_rest",
                "driver_hours_since_last_30m_break",
                "break_scheduled_before_8_hour_limit",
            )
            if getattr(load, field_name) is None
        ]

        if missing_inputs:
            findings.append(
                ComplianceFinding(
                    rule_id="HOS-DRIVER-CONTEXT-MISSING",
                    severity="review",
                    detail=(
                        "Cannot evaluate the HOS limits because these driver "
                        "or trip inputs are missing: "
                        f"{', '.join(missing_inputs)}."
                    ),
                    source_ids=source_ids,
                )
            )
        else:
            driving_hours = (
                load.driver_hours_driven_since_qualifying_rest
                + load.estimated_driving_hours_for_load
            )
            if driving_hours > 11:
                findings.append(
                    ComplianceFinding(
                        rule_id="HOS-11-HOUR-DRIVING-LIMIT",
                        severity="block",
                        detail=(
                            f"The driver would reach {driving_hours:.1f} "
                            "driving hours since qualifying rest, exceeding "
                            "the fictional policy's 11-hour limit."
                        ),
                        source_ids=source_ids,
                    )
                )
            else:
                findings.append(
                    ComplianceFinding(
                        rule_id="HOS-11-HOUR-DRIVING-LIMIT",
                        severity="info",
                        detail=(
                            f"The driver would reach {driving_hours:.1f} "
                            "driving hours since qualifying rest, within the "
                            "fictional policy's 11-hour limit."
                        ),
                        source_ids=source_ids,
                    )
                )

            hours_since_break = (
                load.driver_hours_since_last_30m_break
                + load.estimated_driving_hours_for_load
            )
            if hours_since_break > 8:
                if load.break_scheduled_before_8_hour_limit:
                    findings.append(
                        ComplianceFinding(
                            rule_id="HOS-30-MINUTE-BREAK",
                            severity="info",
                            detail=(
                                "The trip exceeds 8 cumulative driving hours "
                                "since the last break, and a 30-minute break "
                                "is reported as scheduled before the limit."
                            ),
                            source_ids=source_ids,
                        )
                    )
                else:
                    findings.append(
                        ComplianceFinding(
                            rule_id="HOS-30-MINUTE-BREAK",
                            severity="block",
                            detail=(
                                f"The driver would reach {hours_since_break:.1f} "
                                "cumulative driving hours without a reported "
                                "30-minute break before the fictional policy's "
                                "8-hour limit."
                            ),
                            source_ids=source_ids,
                        )
                    )
            else:
                findings.append(
                    ComplianceFinding(
                        rule_id="HOS-30-MINUTE-BREAK",
                        severity="info",
                        detail=(
                            f"The driver would reach {hours_since_break:.1f} "
                            "cumulative driving hours since the last break, "
                            "within the fictional policy's 8-hour threshold."
                        ),
                        source_ids=source_ids,
                    )
                )

    if any(finding.severity == "block" for finding in findings):
        status = "blocked"
    elif any(finding.severity == "review" for finding in findings):
        status = "review"
    else:
        status = "clear"

    result = ComplianceResult(status=status, findings=findings)

    return {"compliance_result": result.model_dump(mode="json")}
