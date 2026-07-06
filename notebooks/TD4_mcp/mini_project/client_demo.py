

import asyncio
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_SCRIPT = Path(__file__).resolve().parent / "pim_server.py"


def _parse(result) -> object:
    """MCP tool results come back as one content block per JSON value; parse them all."""
    parsed = [json.loads(c.text) for c in result.content]
    return parsed[0] if len(parsed) == 1 else parsed


async def main():
    server_params = StdioServerParameters(command="python", args=[str(SERVER_SCRIPT)])

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listed = await session.list_tools()
            print("Discovered tools:", [t.name for t in listed.tools])

            print("\n--- get_category_tree ---")
            res = await session.call_tool("get_category_tree", {})
            print(_parse(res))

            print("\n--- search_products('noise cancelling headphones') ---")
            res = await session.call_tool(
                "search_products", {"query": "noise cancelling headphones", "k": 2}
            )
            for hit in _parse(res):
                print(f"  - {hit['name']} ({hit['category']}, €{hit['price']:.0f})")

            print("\n--- create_product('SKU999', ...) ---")
            res = await session.call_tool(
                "create_product",
                {
                    "sku": "SKU999",
                    "name": "Test Item",
                    "brand": "DemoBrand",
                    "category": "Headphones",
                    "price": 42.0,
                    "short_description": "A demo product for client_demo.py",
                    "long_description": "Created by client_demo.py to prove out-of-process writes work.",
                    "attributes": {"connectivity": "Bluetooth 5.2", "noise_cancellation": True},
                },
            )
            print(_parse(res))

            print("\n--- get_product('SKU999') right after creating it ---")
            res = await session.call_tool("get_product", {"sku": "SKU999"})
            print(_parse(res))

            print("\n--- delete_product('SKU999') ---")
            res = await session.call_tool("delete_product", {"sku": "SKU999"})
            print(_parse(res))


if __name__ == "__main__":
    asyncio.run(main())
