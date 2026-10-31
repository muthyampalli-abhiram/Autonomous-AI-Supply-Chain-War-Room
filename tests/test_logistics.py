"""Unit tests for SimulatedLogisticsAPI, FastMCP server, and LogisticsAgent."""

from __future__ import annotations

import asyncio
import json
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from warroom.agents.logistics_agent import LogisticsAgent
from warroom.data_gen.generator import generate_all
from warroom.data_gen.loader import load_to_db
from warroom.db.models import Carrier
from warroom.db.session import init_db
from warroom.graph.detection import simulate_supplier_outage
from warroom.orchestrator.graph import build_warroom_graph
from warroom.orchestrator.state import create_initial_state
from warroom.tools.logistics_api import SimulatedLogisticsAPI
from warroom.tools.mcp_server import mcp
from warroom.tools.registry import call_tool, clear_delays, set_logistics_api


@pytest.fixture
def memory_session():
    """Create an isolated in-memory SQLite database populated with synthetic data."""
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    init_db(engine=engine, drop=True)
    dfs = generate_all(seed=42)
    load_to_db(dfs, engine=engine)

    with Session(engine) as session:
        yield session

    engine.dispose()


def test_deterministic_quotes_and_carrier_count(memory_session: Session):
    """Verify identical inputs produce identical quotes and quote count equals carrier count."""
    api = SimulatedLogisticsAPI(memory_session)
    set_logistics_api(api)

    quotes1 = api.get_route_quotes("Taiwan", "WH01", "SKU001", 100)
    quotes2 = api.get_route_quotes("Taiwan", "WH01", "SKU001", 100)

    # Determinism: identical quotes
    assert quotes1 == quotes2

    carrier_count = len(memory_session.scalars(select(Carrier)).all())
    assert len(quotes1) == carrier_count
    assert carrier_count > 0


def test_mode_delay_and_clear_delays(memory_session: Session):
    """Verify report_mode_delay adds transit days to specified mode only, and clear_delays restores it."""
    api = SimulatedLogisticsAPI(memory_session)
    set_logistics_api(api)

    base_quotes = call_tool(
        "get_route_quotes",
        origin_country="Taiwan",
        warehouse_id="WH01",
        sku_id="SKU001",
        quantity=100,
    )
    base_transit = {q["mode"]: q["transit_days"] for q in base_quotes}

    # Add 4 days delay to air mode
    call_tool("report_mode_delay", mode="air", extra_days=4)

    delayed_quotes = call_tool(
        "get_route_quotes",
        origin_country="Taiwan",
        warehouse_id="WH01",
        sku_id="SKU001",
        quantity=100,
    )
    delayed_transit = {q["mode"]: q["transit_days"] for q in delayed_quotes}

    assert delayed_transit["air"] == base_transit["air"] + 4
    for mode in delayed_transit:
        if mode != "air":
            assert delayed_transit[mode] == base_transit[mode]

    # Clear delays and verify restoration
    clear_delays()
    restored_quotes = call_tool(
        "get_route_quotes",
        origin_country="Taiwan",
        warehouse_id="WH01",
        sku_id="SKU001",
        quantity=100,
    )
    restored_transit = {q["mode"]: q["transit_days"] for q in restored_quotes}
    assert restored_transit == base_transit


def test_mcp_server_tools_and_call(memory_session: Session):
    """Verify FastMCP server list_tools contains all 4 tool names and call_tool matches registry."""
    api = SimulatedLogisticsAPI(memory_session)
    set_logistics_api(api)

    async def run_mcp_checks():
        # 1. list_tools contains all four tools
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        required_tools = {
            "list_carriers",
            "get_route_quotes",
            "report_mode_delay",
            "get_active_delays",
        }
        assert required_tools.issubset(tool_names)

        # 2. call_tool matches registry result
        reg_result = call_tool(
            "get_route_quotes",
            origin_country="Japan",
            warehouse_id="WH02",
            sku_id="SKU002",
            quantity=200,
        )

        mcp_res = await mcp.call_tool(
            "get_route_quotes",
            {
                "origin_country": "Japan",
                "warehouse_id": "WH02",
                "sku_id": "SKU002",
                "quantity": 200,
            },
        )

        if (
            isinstance(mcp_res, tuple)
            and len(mcp_res) > 1
            and isinstance(mcp_res[1], dict)
            and "result" in mcp_res[1]
        ):
            mcp_quotes = mcp_res[1]["result"]
        elif isinstance(mcp_res, tuple) and len(mcp_res) > 0 and len(mcp_res[0]) > 0:
            mcp_quotes = json.loads(mcp_res[0][0].text)
        else:
            mcp_quotes = mcp_res

        assert mcp_quotes == reg_result

    asyncio.run(run_mcp_checks())


def test_logistics_agent_with_sup01_outage(memory_session: Session):
    """Verify LogisticsAgent route plan, lead times, critical SKU mode choice, and message order."""
    simulate_supplier_outage(memory_session, "SUP01")
    graph = build_warroom_graph(memory_session)
    state = create_initial_state()

    result = graph.invoke(state)

    l_res = result.get("logistics_result")
    assert l_res is not None
    assert l_res["status"] == "ok"

    l_data = l_res["data"]
    per_sku = l_data.get("per_sku", {})
    assert len(per_sku) == 7

    carrier_count = len(memory_session.scalars(select(Carrier)).all())
    sup_per_sku = result["supplier_result"]["data"]["per_sku"]

    for sku_id, sku_info in per_sku.items():
        lanes = sku_info["lanes"]
        rec_lane = next((l for l in lanes if l["role"] == "recommended"), None)
        assert rec_lane is not None, f"SKU {sku_id} missing recommended lane"

        # One option per carrier
        assert len(rec_lane["options"]) == carrier_count

        rec_sup = sup_per_sku[sku_id]["recommended"]
        sup_lead = rec_sup["lead_time_days"]

        for opt in rec_lane["options"]:
            assert opt["total_lead_time_days"] == sup_lead + opt["transit_days"]

        # For every critical SKU, selected mode has minimum total_lead_time_days
        if sku_info["is_critical"]:
            min_lead = min(opt["total_lead_time_days"] for opt in rec_lane["options"])
            selected_lead = rec_lane["selected"]["total_lead_time_days"]
            assert (
                selected_lead == min_lead
            ), f"Critical SKU {sku_id} selected lead time {selected_lead}d, expected min {min_lead}d"

    # Message order check
    messages = result.get("messages", [])
    expected_order = [
        "orchestrator",
        "supplier",
        "inventory",
        "logistics",
        "demand",
        "procurement",
        "customer_impact",
    ]
    actual_order = [m["from"] for m in messages]
    assert actual_order == expected_order

    # Customer Impact is real
    res = result["customer_impact_result"]
    assert res["status"] == "ok"
    assert not res["summary"].startswith("[STUB]")


def test_logistics_agent_missing_dependencies(memory_session: Session):
    """Verify LogisticsAgent returns status 'error' when required upstream results are missing."""
    agent = LogisticsAgent(memory_session)

    # 1. Missing both
    state1 = create_initial_state()
    res1 = agent.run(state1)
    assert res1.status == "error"
    assert "supplier_result and inventory_result are both required" in res1.summary

    # 2. Missing inventory_result
    state2 = create_initial_state()
    state2["supplier_result"] = {"status": "ok", "data": {"per_sku": {}}}
    res2 = agent.run(state2)
    assert res2.status == "error"
