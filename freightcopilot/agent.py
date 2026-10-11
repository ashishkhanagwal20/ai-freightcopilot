import asyncio
from collections.abc import AsyncIterator
from typing import Any

from google.genai import types
from mcp import Client

from freightcopilot.config import GENERATION_MODEL
from freightcopilot.generation import get_gemini_client
from freightcopilot.mcp.carrier_server import mcp
from freightcopilot.schemas import AgentAnswer


AgentEvent = tuple[str, dict[str, Any]]

LOOKUP_CARRIER_TOOL = "lookup_carrier"
CREATE_PROPOSAL_TOOL = "create_booking_proposal"


def build_agent_config() -> types.GenerateContentConfig:
    lookup_declaration = types.FunctionDeclaration(
        name=LOOKUP_CARRIER_TOOL,
        description=(
            "Look up a carrier's equipment and capacity by carrier ID."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "carrier_id": types.Schema(
                    type=types.Type.STRING,
                    description="Carrier identifier, such as CARRIER-014.",
                )
            },
            required=["carrier_id"],
        ),
    )

    proposal_declaration = types.FunctionDeclaration(
        name=CREATE_PROPOSAL_TOOL,
        description=(
            "Create a pending booking proposal for human review. "
            "This does not approve or book the load. Only call when the user "
            "provided all required details: load ID, carrier ID, rate in USD, "
            "pickup time, and delivery time. Times must be ISO-8601 strings "
            "with timezone offsets."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "load_id": types.Schema(
                    type=types.Type.STRING,
                    description="The user's load identifier.",
                ),
                "carrier_id": types.Schema(
                    type=types.Type.STRING,
                    description="The carrier identifier, such as CARRIER-014.",
                ),
                "rate_usd": types.Schema(
                    type=types.Type.NUMBER,
                    description="The proposed rate in US dollars.",
                ),
                "pickup_at": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "Pickup date and time in ISO-8601 format with offset."
                    ),
                ),
                "delivery_at": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "Delivery date and time in ISO-8601 format with offset."
                    ),
                ),
            },
            required=[
                "load_id",
                "carrier_id",
                "rate_usd",
                "pickup_at",
                "delivery_at",
            ],
        ),
    )

    return types.GenerateContentConfig(
        system_instruction=(
            "You assist with freight carrier questions and booking proposals. "
            "Use lookup_carrier for carrier details. If the user asks to "
            "prepare a booking, create a proposal only when all required "
            "details were supplied by the user. If details are missing, ask "
            "for them. A proposal is pending human approval. Never say a load "
            "is booked or approved; only a human approval action can do that."
        ),
        tools=[
            types.Tool(
                function_declarations=[
                    lookup_declaration,
                    proposal_declaration,
                ]
            )
        ],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            disable=True
        ),
    )


async def stream_carrier_question(question: str) -> AsyncIterator[AgentEvent]:
    """Yield progress events while the agent answers a question."""
    yield ("status", {"stage": "started"})

    chat = get_gemini_client().chats.create(
        model=GENERATION_MODEL,
        config=build_agent_config(),
    )

    # Gemini's SDK call is synchronous, so run it outside the async event loop.
    response = await asyncio.to_thread(chat.send_message, question)
    function_calls = response.function_calls or []

    if not function_calls:
        answer = AgentAnswer(answer=response.text or "")
        yield ("answer", answer.model_dump(exclude_none=True))
        return

    if len(function_calls) != 1:
        raise ValueError("This demo supports one tool call per request.")

    function_call = function_calls[0]
    allowed_tools = {LOOKUP_CARRIER_TOOL, CREATE_PROPOSAL_TOOL}

    if function_call.name not in allowed_tools:
        raise ValueError(f"Unexpected tool requested: {function_call.name}")

    arguments = dict(function_call.args)

    if function_call.name == LOOKUP_CARRIER_TOOL:
        carrier_id = arguments.get("carrier_id")
        if not isinstance(carrier_id, str) or not carrier_id:
            raise ValueError("lookup_carrier requires a carrier_id.")

    if function_call.name == CREATE_PROPOSAL_TOOL:
        required_arguments = {
            "load_id",
            "carrier_id",
            "rate_usd",
            "pickup_at",
            "delivery_at",
        }
        missing_arguments = required_arguments.difference(arguments)
        if missing_arguments:
            raise ValueError(
                "Proposal is missing required fields: "
                + ", ".join(sorted(missing_arguments))
            )

    yield (
        "tool_call",
        {
            "name": function_call.name,
            "arguments": arguments,
        },
    )

    async with Client(mcp) as mcp_client:
        tool_result = await mcp_client.call_tool(
            function_call.name,
            arguments,
        )

    if tool_result.is_error:
        raise RuntimeError(f"MCP tool failed: {tool_result.content}")

    if tool_result.structured_content is None:
        raise RuntimeError("MCP returned no structured tool result.")

    tool_data = tool_result.structured_content

    yield (
        "tool_result",
        {
            "name": function_call.name,
            "result": tool_data,
        },
    )

    approval_required = (
        function_call.name == CREATE_PROPOSAL_TOOL
        and tool_data.get("status") == "pending_approval"
    )
    approval_id = (
        str(tool_data["approval_id"])
        if approval_required and tool_data.get("approval_id")
        else None
    )

    if approval_required:
        yield (
            "approval_required",
            {
                "approval_id": approval_id,
                "status": "pending_approval",
                "proposal": tool_data,
            },
        )

    final_response = await asyncio.to_thread(
        chat.send_message,
        types.Part(
            function_response=types.FunctionResponse(
                name=function_call.name,
                response={"result": tool_data},
                id=function_call.id,
            )
        ),
    )

    answer = AgentAnswer(
        answer=final_response.text or "",
        tool_name=function_call.name,
        tool_arguments=arguments,
        tool_result=tool_data,
        approval_required=approval_required,
        approval_id=approval_id,
    )

    yield ("answer", answer.model_dump(exclude_none=True))


async def answer_carrier_question(question: str) -> AgentAnswer:
    """Run the agent and return its final answer for the JSON API endpoint."""
    async for event_name, data in stream_carrier_question(question):
        if event_name == "answer":
            return AgentAnswer.model_validate(data)

    raise RuntimeError("Agent workflow ended without producing an answer.")