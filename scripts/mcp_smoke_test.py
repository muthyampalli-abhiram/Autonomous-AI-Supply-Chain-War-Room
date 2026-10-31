"""In-process smoke test for the War Room FastMCP server."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Ensure src/ is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from warroom.tools.mcp_server import mcp


async def smoke_test() -> None:
    print("=" * 70)
    print("FastMCP In-Process Smoke Test")
    print("=" * 70)

    # 1. List available tools
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]
    print(f"[*] Registered MCP Tools ({len(tools)}):")
    for t in tools:
        print(f"    - {t.name}: {t.description}")
    print()

    # 2. Call get_route_quotes once
    test_params = {
        "origin_country": "Taiwan",
        "warehouse_id": "WH01",
        "sku_id": "SKU001",
        "quantity": 250,
    }
    print(f"[*] Invoking 'get_route_quotes' with params: {test_params}")
    result = await mcp.call_tool("get_route_quotes", test_params)

    # Extract returned quotes from tuple or text content
    if isinstance(result, tuple) and len(result) > 1 and isinstance(result[1], dict) and "result" in result[1]:
        quotes = result[1]["result"]
    elif isinstance(result, tuple) and len(result) > 0 and len(result[0]) > 0:
        quotes = json.loads(result[0][0].text)
    else:
        quotes = result

    print(f"[*] Response Quotes ({len(quotes)} carriers):")
    for q in quotes:
        print(
            f"    Carrier {q.get('carrier_id')} ({q.get('mode').upper()}): "
            f"Freight=${q.get('freight_total'):,.2f} (${q.get('freight_per_unit'):.2f}/unit), "
            f"Transit={q.get('transit_days')}d, OnTime={q.get('on_time_prob')*100:.0f}%"
        )
    print("=" * 70)
    print("[*] MCP Smoke Test Completed Successfully.")


if __name__ == "__main__":
    asyncio.run(smoke_test())
