"""Unit tests for deterministic SupplierAgent and InventoryAgent within the War Room graph."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from warroom.agents.inventory_agent import InventoryAgent
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


def test_supplier_agent_evaluation(memory_session: Session):
    """Test SupplierAgent deterministic ranking, score bounds, and capacity splits on SUP01 outage."""
    simulate_supplier_outage(memory_session, "SUP01")
    graph = build_warroom_graph(memory_session)
    state = create_initial_state()

    result = graph.invoke(state)

    supplier_result = result.get("supplier_result")
    assert supplier_result is not None
    assert supplier_result["status"] == "ok"

    s_data = supplier_result["data"]
    per_sku = s_data.get("per_sku", {})

    # 1. Exactly 7 SKUs affected by SUP01 outage
    assert len(per_sku) == 7

    # 2. SUP01 never appears as an alternative, ranked lists sorted desc, scores in [0, 1]
    for sku_id, sku_info in per_sku.items():
        alts = sku_info["ranked_alternatives"]
        assert len(alts) > 0, f"Expected alternatives for {sku_id}"

        for alt in alts:
            assert (
                alt["supplier_id"] != "SUP01"
            ), f"Disrupted supplier SUP01 appeared as alternative for {sku_id}"
            assert (
                0.0 <= alt["score"] <= 1.0
            ), f"Score {alt['score']} for {alt['supplier_id']} not in [0, 1]"

        scores = [a["score"] for a in alts]
        assert scores == sorted(
            scores, reverse=True
        ), f"Alternatives for {sku_id} are not sorted by score descending: {scores}"

        # Recommended and backup integrity
        assert sku_info["recommended"] == alts[0]
        if len(alts) > 1:
            assert sku_info["backup"] == alts[1]

    # 3. skus_needing_split is not empty
    skus_needing_split = s_data.get("skus_needing_split", [])
    assert (
        len(skus_needing_split) > 0
    ), "Expected at least one SKU to require order splitting across suppliers"


def test_inventory_agent_allocation(memory_session: Session):
    """Test InventoryAgent greedy priority allocation, fill rates, and shortfall calculations."""
    simulate_supplier_outage(memory_session, "SUP01")
    graph = build_warroom_graph(memory_session)
    state = create_initial_state()

    result = graph.invoke(state)

    inv_result = result.get("inventory_result")
    assert inv_result is not None
    assert inv_result["status"] == "ok"

    i_data = inv_result["data"]
    per_sku = i_data.get("per_sku", {})
    assert len(per_sku) == 7

    # 1. allocated_qty <= total on_hand and allocated_qty + shortfall_qty == window_demand
    for sku_id, sku_info in per_sku.items():
        allocated = sku_info["allocated_qty"]
        on_hand = sku_info["on_hand"]
        shortfall = sku_info["shortfall_qty"]
        window_demand = sku_info["window_demand"]

        assert (
            allocated <= on_hand
        ), f"{sku_id}: allocated_qty ({allocated}) exceeds total on_hand ({on_hand})"
        assert (
            allocated + shortfall == window_demand
        ), f"{sku_id}: allocated ({allocated}) + shortfall ({shortfall}) != window_demand ({window_demand})"

        # 2. Priority-ordered allocation: once short, no later order gets > 0
        allocations = sku_info["allocations"]
        seen_short = False
        for alloc in allocations:
            if seen_short:
                assert (
                    alloc["allocated_qty"] == 0
                ), f"{sku_id}: order {alloc['order_id']} allocated > 0 after an earlier order was short"
            if alloc["short_qty"] > 0:
                seen_short = True

    # 3. Specific SKU assertions: SKU006 and SKU007 are well covered, SKU001 is the worst-hit
    # Tolerances account for synthetic order due dates shifting relative to date.today() replenishment window.
    assert (
        per_sku["SKU006"]["fill_rate_pct"] >= 90.0
    ), f"SKU006 fill rate was {per_sku['SKU006']['fill_rate_pct']}%, expected >= 90%"
    assert (
        per_sku["SKU007"]["fill_rate_pct"] >= 90.0
    ), f"SKU007 fill rate was {per_sku['SKU007']['fill_rate_pct']}%, expected >= 90%"
    assert (
        per_sku["SKU006"]["fill_rate_pct"] > per_sku["SKU001"]["fill_rate_pct"]
    ), f"SKU006 fill rate ({per_sku['SKU006']['fill_rate_pct']}%) should be greater than SKU001 ({per_sku['SKU001']['fill_rate_pct']}%)"
    assert (
        per_sku["SKU007"]["fill_rate_pct"] > per_sku["SKU001"]["fill_rate_pct"]
    ), f"SKU007 fill rate ({per_sku['SKU007']['fill_rate_pct']}%) should be greater than SKU001 ({per_sku['SKU001']['fill_rate_pct']}%)"
    assert (
        per_sku["SKU001"]["shortfall_qty"] > 0
    ), f"SKU001 expected shortfall > 0, got {per_sku['SKU001']['shortfall_qty']}"


def test_pipeline_message_order_and_stubs(memory_session: Session):
    """Verify message order is strictly maintained and remaining 4 agents are untouched stubs."""
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

    # 2. customer_impact is now a real agent
    res = result.get("customer_impact_result")
    assert res is not None, "Expected customer_impact_result in final state"
    assert res["status"] == "ok"
    assert not res["summary"].startswith("[STUB]")


def test_inventory_agent_missing_supplier_result(memory_session: Session):
    """Verify InventoryAgent returns status 'error' when supplier_result is missing."""
    agent = InventoryAgent(memory_session)
    state = create_initial_state()
    state["disruption"] = {"event_id": "DISR-SUP01", "supplier_id": "SUP01"}
    # Do NOT provide supplier_result

    res = agent.run(state)
    assert res.status == "error"
    assert "supplier_result is missing" in res.summary
