import asyncio

from mcp import Client

from freightcopilot.mcp.carrier_server import mcp


async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        print("Tools:", [tool.name for tool in tools.tools])

        result = await client.call_tool(
            "lookup_carrier", {"carrier_id": "CARRIER-014"}
        )
        if result.is_error:
            print("Tool returned an error:", result.content)
        elif result.structured_content is not None:
            print("Structured result:", result.structured_content)
        else:
            print("Text result:", result.content)


if __name__ == "__main__":
    asyncio.run(main())
