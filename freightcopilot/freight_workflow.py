import asyncio
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

from freightcopilot.config import get_database_url
from freightcopilot.workflow_nodes import (
    compliance_node,
    matchmaking_node,
)
from freightcopilot.workflow_schemas import (
    FreightWorkflowInput,
    FreightWorkflowState,
)


def run_matchmaking_node(
    state: FreightWorkflowState,
) -> dict[str, Any]:
    """Adapt the async MCP-backed node for synchronous graph invocation."""
    return asyncio.run(matchmaking_node(state))


def route_after_matchmaking(
    state: FreightWorkflowState,
) -> str:
    """Only run compliance review for a carrier that passed matching."""
    result = state.get("matchmaking_result", {})

    if result.get("status") == "eligible":
        return "compliance"

    return "stop"


def build_freight_workflow(checkpointer: PostgresSaver):
    """Build the matchmaking-then-compliance workflow."""
    builder = StateGraph(FreightWorkflowState)

    builder.add_node("matchmaking", run_matchmaking_node)
    builder.add_node("compliance", compliance_node)

    builder.add_edge(START, "matchmaking")
    builder.add_conditional_edges(
        "matchmaking",
        route_after_matchmaking,
        {
            "compliance": "compliance",
            "stop": END,
        },
    )
    builder.add_edge("compliance", END)

    return builder.compile(checkpointer=checkpointer)


def run_freight_workflow(
    workflow_input: FreightWorkflowInput,
) -> dict[str, Any]:
    """Run and checkpoint the freight workflow using a new graph thread."""
    thread_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state: FreightWorkflowState = {
        "question": workflow_input.question,
        "load_request": workflow_input.load_request.model_dump(mode="json"),
        "thread_id": thread_id,
    }

    with PostgresSaver.from_conn_string(get_database_url()) as checkpointer:
        graph = build_freight_workflow(checkpointer)
        result = graph.invoke(initial_state, config)

    return result