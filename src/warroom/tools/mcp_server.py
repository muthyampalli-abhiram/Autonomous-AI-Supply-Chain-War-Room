"""FastMCP logistics server exposing war room tools over stdio."""

from __future__ import annotations

from typing import Any
from mcp.server.fastmcp import FastMCP

from warroom.db.session import get_session
from warroom.tools.logistics_api import SimulatedLogisticsAPI
from warroom.tools.registry import call_tool, set_logistics_api

# FastMCP server instance
mcp = FastMCP("warroom-logistics")

# Initialize isolated session and API engine for MCP server
_session = get_session()
_api = SimulatedLogisticsAPI(_session)
set_logistics_api(_api)


@mcp.tool()
def list_carriers() -> list[dict[str, Any]]:
    """List all available freight carriers with speed and base cost."""
    return call_tool("list_carriers")


@mcp.tool()
def get_route_quotes(
    origin_country: str, warehouse_id: str, sku_id: str, quantity: int
) -> list[dict[str, Any]]:
    """Get freight quotes across all carriers for a given lane."""
    return call_tool(
        "get_route_quotes",
        origin_country=origin_country,
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        quantity=quantity,
    )


@mcp.tool()
def report_mode_delay(mode: str, extra_days: int) -> dict[str, Any]:
    """Report an active transit delay in days for a transport mode."""
    return call_tool("report_mode_delay", mode=mode, extra_days=extra_days)


@mcp.tool()
def get_active_delays() -> dict[str, int]:
    """Get currently active transit delays by transport mode."""
    return call_tool("get_active_delays")


def main() -> None:
    """Run FastMCP server using stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
