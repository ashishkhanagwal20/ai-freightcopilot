import asyncio
from typing import Any, Literal, NotRequired, TypedDict

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from freightcopilot.agent import answer_carrier_question
from freightcopilot.config import get_database_url


class AgentGraphState(TypedDict):
    question: str
    agent_result: NotRequired[dict[str, Any]]
    approval_decision: NotRequired[str]


def run_agent_node(state: AgentGraphState) -> dict[str, Any]:
    """Run the existing agent and store its JSON-compatible result."""
    # This graph node runs in a worker thread, so asyncio.run can drive the
    # existing async MCP workflow.
    result = asyncio.run(answer_carrier_question(state["question"]))

    return {
        "agent_result": result.model_dump(
            mode="json",
            exclude_none=True,
        )
    }


def route_after_agent(
    state: AgentGraphState,
) -> Literal["approval_gate", "finish"]:
    agent_result = state.get("agent_result", {})

    if agent_result.get("approval_required"):
        return "approval_gate"

    return "finish"


def get_approval_status(approval_id: str) -> str | None:
    with psycopg.connect(get_database_url()) as connection:
        row = connection.execute(
            """
            SELECT status
            FROM booking_approvals
            WHERE approval_id = %s
            """,
            (approval_id,),
        ).fetchone()

    if row is None:
        return None

    return row[0]


def approval_gate_node(state: AgentGraphState) -> dict[str, str]:
    """Pause the graph and require a matching stored human decision."""
    agent_result = state.get("agent_result", {})
    approval_id = agent_result.get("approval_id")

    if not approval_id:
        raise ValueError("Agent result is missing its approval_id.")

    resume_value = interrupt(
        {
            "message": "Review this booking proposal before continuing.",
            "approval_id": approval_id,
            "proposal": agent_result.get("tool_result"),
        }
    )

    if not isinstance(resume_value, dict):
        raise ValueError("The graph resume value must be an object.")

    if resume_value.get("approval_id") != approval_id:
        raise ValueError("Resume approval_id does not match this graph thread.")

    decision = resume_value.get("decision")
    if decision not in {"approved", "rejected"}:
        raise ValueError("Decision must be approved or rejected.")

    stored_status = get_approval_status(approval_id)
    if stored_status != decision:
        raise ValueError(
            "The proposal must be approved or rejected through the approval "
            "API before the graph can resume."
        )

    return {"approval_decision": decision}


def build_agent_graph(checkpointer: PostgresSaver):
    builder = StateGraph(AgentGraphState)

    builder.add_node("run_agent", run_agent_node)
    builder.add_node("approval_gate", approval_gate_node)

    builder.add_edge(START, "run_agent")
    builder.add_conditional_edges(
        "run_agent",
        route_after_agent,
        {
            "approval_gate": "approval_gate",
            "finish": END,
        },
    )
    builder.add_edge("approval_gate", END)

    return builder.compile(checkpointer=checkpointer)


def run_agent_graph(
    question: str,
    thread_id: str,
) -> dict[str, Any]:
    """Start a graph run with a persistent Postgres checkpoint."""
    config = {"configurable": {"thread_id": thread_id}}

    with PostgresSaver.from_conn_string(get_database_url()) as checkpointer:
        graph = build_agent_graph(checkpointer)
        return graph.invoke({"question": question}, config)


def resume_agent_graph(
    thread_id: str,
    approval_id: str,
) -> dict[str, Any]:
    """Resume a paused graph only after the proposal has a human decision."""
    config = {"configurable": {"thread_id": thread_id}}

    with PostgresSaver.from_conn_string(get_database_url()) as checkpointer:
        graph = build_agent_graph(checkpointer)
        snapshot = graph.get_state(config)

        if not snapshot.values:
            raise LookupError("LangGraph thread was not found.")

        agent_result = snapshot.values.get("agent_result", {})
        expected_approval_id = agent_result.get("approval_id")

        if expected_approval_id != approval_id:
            raise ValueError(
                "This approval_id does not belong to the requested graph thread."
            )

        stored_status = get_approval_status(approval_id)

        if stored_status is None:
            raise LookupError("Approval proposal was not found.")

        if stored_status == "pending_approval":
            raise ValueError(
                "Proposal is still pending. Approve or reject it first."
            )

        if stored_status not in {"approved", "rejected"}:
            raise ValueError(f"Unexpected approval status: {stored_status}")

        # A repeated resume request returns the completed state.
        if snapshot.values.get("approval_decision") == stored_status:
            return dict(snapshot.values)

        if not snapshot.next:
            raise ValueError("This graph thread is not waiting for approval.")

        return graph.invoke(
            Command(
                resume={
                    "approval_id": approval_id,
                    "decision": stored_status,
                }
            ),
            config,
        )