import asyncio

from google import genai
from google.genai import types
from mcp import Client

from freightcopilot.config import GENERATION_MODEL, get_gemini_api_key
from freightcopilot.mcp.carrier_server import mcp


async def main() -> None:
    client = genai.Client(api_key=get_gemini_api_key())

    lookup_declaration = types.FunctionDeclaration(
        name="lookup_carrier",
        description="Look up a carrier's equipment and capacity by carrier ID.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "carrier_id": types.Schema(
                    type=types.Type.STRING,
                    description="The carrier identifier, such as CARRIER-014.",
                )
            },
            required=["carrier_id"],
        ),
    )

    config = types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=[lookup_declaration])],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            disable=True
        ),
    )

    chat = client.chats.create(model=GENERATION_MODEL, config=config)
    question = (
        "What equipment and maximum weight does carrier CARRIER-014 support? "
        "Use the carrier lookup tool to answer."
    )
    response = chat.send_message(question)

    function_calls = response.function_calls or []
    if not function_calls:
        print("Gemini answered without requesting a tool:")
        print(response.text)
        return

    # This demo exposes only one tool, so reject any other requested function.
    function_call = function_calls[0]
    if function_call.name != "lookup_carrier":
        raise ValueError(f"Unexpected tool requested: {function_call.name}")

    print(f"Gemini requested {function_call.name}: {function_call.args}")

    async with Client(mcp) as mcp_client:
        tool_result = await mcp_client.call_tool(
            function_call.name,
            dict(function_call.args),
        )

    if tool_result.is_error:
        raise RuntimeError(f"MCP tool failed: {tool_result.content}")
    if tool_result.structured_content is None:
        raise RuntimeError(f"MCP returned no structured data: {tool_result.content}")

    print("MCP returned:", tool_result.structured_content)

    response = chat.send_message(
    types.Part(
        function_response=types.FunctionResponse(
            name=function_call.name,
            response={"carrier": tool_result.structured_content},
            id=function_call.id,
        )
    )
)
    print("\nFinal answer:")
    print(response.text)


if __name__ == "__main__":
    asyncio.run(main())