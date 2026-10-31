"""Unit tests for deterministic DemandAgent and ProcurementAgent within the War Room graph."""

from __future__ import annotations

import math
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from warroom.agents.demand_agent import TREND_CLAMP, DemandAgent
from warroom.agents.procurement_agent import ProcurementAgent
from warroom.data_gen.generator import generate_all
from warroom.data_gen.loader import load_to_db
from warroom.db.session import init_db
from warroom.graph.detection import simulate_supplier_outage
from warroom.orchestrator.graph import build_warroom_graph
from warroom.orchestrator.state import create_initial_state


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


def test_demand_agent_evaluation(memory_session: Session):
    """Verify DemandAgent trend clamping, positive forecast, tier mix sum, determinism, and gap bounds."""
    simulate_supplier_outage(memory_session, "SUP01")
    graph = build_warroom_graph(memory_session)

    # Determinism: two identical invocations
    state1 = create_initial_state()
    res1 = graph.invoke(state1)

    state2 = create_initial_state()
    res2 = graph.invoke(state2)

    assert res1["demand_result"]["data"] == res2["demand_result"]["data"]

    d_data = res1["demand_result"]["data"]
    per_sku = d_data.get("per_sku", {})
    assert len(per_sku) == 7

    for sku_id, data in per_sku.items():
        # Trend factor within clamp
        assert (
            TREND_CLAMP[0] <= data["trend_factor"] <= TREND_CLAMP[1]
        ), f"{sku_id} trend factor {data['trend_factor']} outside {TREND_CLAMP}"

        # Forecast daily positive
        assert data["forecast_daily"] > 0, f"{sku_id} forecast daily non-positive"

        # Tier mix percentages sum to 100.0
        tier_sum = round(sum(data["tier_mix_pct"].values()), 1)
        assert tier_sum == 100.0, f"{sku_id} tier mix sum was {tier_sum}, expected 100.0"

    # SKU-specific assertions: SKU004 has days_uncovered > 0, SKU007 has days_uncovered == 0
    assert (
        per_sku["SKU004"]["days_uncovered"] > 0
    ), f"SKU004 expected days_uncovered > 0, got {per_sku['SKU004']['days_uncovered']}"
    assert (
        per_sku["SKU007"]["days_uncovered"] == 0.0
    ), f"SKU007 expected days_uncovered == 0.0, got {per_sku['SKU007']['days_uncovered']}"


def test_demand_agent_missing_inputs(memory_session: Session):
    """Verify DemandAgent returns status 'error' when required upstream results are missing."""
    agent = DemandAgent(memory_session)

    # Missing all
    state1 = create_initial_state()
    res1 = agent.run(state1)
    assert res1.status == "error"
    assert "required" in res1.summary

    # Missing logistics_result
    state2 = create_initial_state()
    state2["supplier_result"] = {"status": "ok", "data": {"per_sku": {}}}
    state2["inventory_result"] = {"status": "ok", "data": {"per_sku": {}}}
    res2 = agent.run(state2)
    assert res2.status == "error"


def test_procurement_agent_plan(memory_session: Session):
    """Verify PO quantities, supplier validity, capacity limits, net requirements, and totals."""
    simulate_supplier_outage(memory_session, "SUP01")
    graph = build_warroom_graph(memory_session)
    state = create_initial_state()

    result = graph.invoke(state)

    p_res = result.get("procurement_result")
    assert p_res is not None
    assert p_res["status"] == "ok"

    p_data = p_res["data"]
    pos = p_data.get("purchase_orders", [])
    assert len(pos) > 0

    po_ids = []
    sup_per_sku = result["supplier_result"]["data"]["per_sku"]

    for po in pos:
        # Multiple of 10 and positive
        assert po["quantity"] > 0, f"PO {po['po_id']} non-positive quantity"
        assert (
            po["quantity"] % 10 == 0
        ), f"PO {po['po_id']} quantity {po['quantity']} not multiple of 10"

        # Disrupted supplier SUP01 never awarded a PO
        assert (
            po["supplier_id"] != "SUP01"
        ), f"Disrupted supplier SUP01 appeared in PO {po['po_id']}"

        # Unique PO IDs
        po_ids.append(po["po_id"])

        # Line cost exact formula
        expected_line_cost = round(
            po["quantity"] * po["unit_price"] + po["freight_cost"], 2
        )
        assert math.isclose(
            po["line_cost"], expected_line_cost, abs_tol=0.01
        ), f"PO {po['po_id']} line cost {po['line_cost']} != expected {expected_line_cost}"

        # Capacity window check
        sku_cand = sup_per_sku[po["sku_id"]][po["role"]]
        monthly_cap = float(sku_cand["monthly_capacity"])
        # Coverage days default 30 -> max cap is monthly capacity
        assert (
            po["quantity"] <= monthly_cap
        ), f"PO {po['po_id']} quantity {po['quantity']} exceeds monthly capacity {monthly_cap}"

    assert len(po_ids) == len(set(po_ids)), "PO IDs are not unique"

    # Per SKU coverage: ordered_qty + unsourced_qty >= net_requirement
    per_sku_summary = p_data.get("per_sku", {})
    assert len(per_sku_summary) == 7
    for sku_id, summary in per_sku_summary.items():
        assert (
            summary["ordered_qty"] + summary["unsourced_qty"]
            >= summary["net_requirement"]
        ), f"{sku_id}: ordered + unsourced < net requirement"

    # Totals equal the sum of the PO lines
    totals = p_data.get("totals", {})
    assert totals["po_count"] == len(pos)
    assert math.isclose(
        totals["total_po_value"],
        sum(po["quantity"] * po["unit_price"] for po in pos),
        abs_tol=0.05,
    )
    assert math.isclose(
        totals["total_freight"],
        sum(po["freight_cost"] for po in pos),
        abs_tol=0.05,
    )
    assert math.isclose(
        totals["total_landed_cost"],
        sum(po["line_cost"] for po in pos),
        abs_tol=0.05,
    )
    assert math.isclose(
        totals["total_premium_vs_baseline"],
        sum(po["premium_vs_baseline"] for po in pos),
        abs_tol=0.05,
    )


def test_procurement_agent_missing_inputs(memory_session: Session):
    """Verify ProcurementAgent returns status 'error' when required upstream results are missing."""
    agent = ProcurementAgent(memory_session)

    # Missing all
    state1 = create_initial_state()
    res1 = agent.run(state1)
    assert res1.status == "error"

    # Missing demand_result
    state2 = create_initial_state()
    state2["supplier_result"] = {"status": "ok", "data": {"per_sku": {}}}
    state2["inventory_result"] = {"status": "ok", "data": {"per_sku": {}}}
    state2["logistics_result"] = {"status": "ok", "data": {"per_sku": {}}}
    res2 = agent.run(state2)
    assert res2.status == "error"


def test_pipeline_message_order_and_final_stub(memory_session: Session):
    """Verify message order is strictly preserved and ONLY customer_impact is still a stub."""
    simulate_supplier_outage(memory_session, "SUP01")
    graph = build_warroom_graph(memory_session)
    state = create_initial_state()

    result = graph.invoke(state)

    # 1. Message order
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

    # 2. All 6 agents are real, no stubs remain
    real_agents = [
        "supplier_result",
        "inventory_result",
        "logistics_result",
        "demand_result",
        "procurement_result",
        "customer_impact_result",
    ]
    for key in real_agents:
        res = result[key]
        assert res["status"] == "ok"
        assert not res["summary"].startswith("[STUB]"), f"{key} unexpectedly returned stub summary"

    ci_res = result["customer_impact_result"]
    assert "per_order" in ci_res["data"]
