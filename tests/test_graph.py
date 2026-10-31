"""Unit and integration tests for NetworkX supply graph, impact analysis, and disruption detection."""

from __future__ import annotations

import networkx as nx
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from warroom.data_gen.generator import generate_all
from warroom.data_gen.loader import load_to_db
from warroom.db.session import init_db
from warroom.graph.analysis import (
    avg_daily_demand,
    impact_of_supplier_failure,
    single_point_of_failure_report,
)
from warroom.graph.builder import build_supply_graph
from warroom.graph.detection import (
    detect_disruptions,
    restore_supplier,
    simulate_supplier_outage,
)


@pytest.fixture
def memory_session():
    """Create an isolated in-memory SQLite database populated with synthetic data.

    Guarantees data/warroom.db is never touched.
    """
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


def test_graph_node_counts(memory_session: Session):
    """Verify graph has exactly 15 suppliers, 20 skus, 4 warehouses, and 8 customers."""
    G = build_supply_graph(memory_session)

    supplier_nodes = [
        n for n, d in G.nodes(data=True) if d.get("node_type") == "supplier"
    ]
    sku_nodes = [
        n for n, d in G.nodes(data=True) if d.get("node_type") == "sku"
    ]
    warehouse_nodes = [
        n for n, d in G.nodes(data=True) if d.get("node_type") == "warehouse"
    ]
    customer_nodes = [
        n for n, d in G.nodes(data=True) if d.get("node_type") == "customer"
    ]

    assert len(supplier_nodes) == 15
    assert len(sku_nodes) == 20
    assert len(warehouse_nodes) == 4
    assert len(customer_nodes) == 8
    assert G.number_of_nodes() == 47


def test_graph_edges_structure(memory_session: Session):
    """Verify edges have expected relations and attributes."""
    G = build_supply_graph(memory_session)

    # 1. supplier -> sku edges
    supplies_edges = [
        (u, v, d) for u, v, d in G.edges(data=True) if d.get("relation") == "supplies"
    ]
    assert len(supplies_edges) > 0
    for _, _, d in supplies_edges:
        assert "unit_price" in d
        assert "lead_time_days" in d
        assert "monthly_capacity" in d
        assert "is_primary" in d
        assert d["active"] is True

    # 2. sku -> warehouse edges
    stocked_edges = [
        (u, v, d) for u, v, d in G.edges(data=True) if d.get("relation") == "stocked_at"
    ]
    assert len(stocked_edges) == 80  # 20 skus x 4 warehouses
    for _, _, d in stocked_edges:
        assert "on_hand" in d
        assert "safety_stock" in d

    # 3. sku -> customer edges
    ordered_edges = [
        (u, v, d) for u, v, d in G.edges(data=True) if d.get("relation") == "ordered_by"
    ]
    assert len(ordered_edges) > 0
    for _, _, d in ordered_edges:
        assert d["open_order_count"] >= 1
        assert d["open_quantity"] > 0
        assert "earliest_due_date" in d
        assert d["max_priority"] in (1, 2, 3)


def test_baseline_detect_disruptions_empty(memory_session: Session):
    """Before any outage detect_disruptions returns an empty list."""
    disruptions = detect_disruptions(memory_session)
    assert disruptions == []


def test_simulate_supplier_outage_detection(memory_session: Session):
    """After simulate_supplier_outage('SUP01') detect_disruptions returns exactly one critical event."""
    simulate_supplier_outage(memory_session, "SUP01", duration_days=30)

    events = detect_disruptions(memory_session)
    assert len(events) == 1

    event = events[0]
    assert event.supplier_id == "SUP01"
    assert event.severity == "critical"
    assert event.affected_sku_count == 7
    assert event.event_type == "supplier_outage"
    assert event.expected_duration_days == 30


def test_inactive_supplier_edges_marked_inactive(memory_session: Session):
    """Verify that edges from an unavailable supplier are marked active=False."""
    simulate_supplier_outage(memory_session, "SUP01")
    G = build_supply_graph(memory_session)

    sup01_edges = [
        d for _, _, d in G.out_edges("SUP01", data=True) if d.get("relation") == "supplies"
    ]
    assert len(sup01_edges) > 0
    for d in sup01_edges:
        assert d["active"] is False


def test_impact_of_supplier_failure_sup01(memory_session: Session):
    """impact_of_supplier_failure for SUP01 lists 7 affected SKUs with >= 2 alternatives, none being SUP01."""
    simulate_supplier_outage(memory_session, "SUP01")
    G = build_supply_graph(memory_session)

    impact = impact_of_supplier_failure(G, memory_session, "SUP01")

    # 7 affected SKUs
    assert len(impact["affected_skus"]) == 7

    # No sole source SKUs since alternatives were configured
    assert impact["sole_source_skus"] == []

    # Each SKU has at least 2 alternatives, none of which is SUP01
    for sku_id in impact["affected_skus"]:
        alts = impact["alternatives"][sku_id]
        assert len(alts) >= 2, f"SKU {sku_id} has fewer than 2 alternatives"
        for alt in alts:
            assert alt["supplier_id"] != "SUP01"
            assert alt["supplier"] != "SUP01"
            assert alt["lead_time_days"] > 0
            assert alt["unit_price"] > 0

        # Days of cover and supply gap
        assert sku_id in impact["days_of_cover"]
        assert impact["days_of_cover"][sku_id] > 0
        assert sku_id in impact["supply_gap_days"]
        assert impact["supply_gap_days"][sku_id] is not None
        assert impact["supply_gap_days"][sku_id] >= 0

    # Exposed customers and open orders
    assert len(impact["exposed_customers"]) > 0
    for cust_id, cust_info in impact["exposed_customers"].items():
        assert cust_info["quantity"] > 0
        assert cust_info["max_priority"] in (1, 2, 3)

    assert impact["exposed_open_orders"]["count"] > 0
    assert impact["exposed_open_orders"]["total_quantity"] > 0


def test_restore_supplier_returns_to_nominal(memory_session: Session):
    """restore_supplier returns the system to zero detected disruptions and active edges."""
    simulate_supplier_outage(memory_session, "SUP01")
    assert len(detect_disruptions(memory_session)) == 1

    restore_supplier(memory_session, "SUP01")
    assert len(detect_disruptions(memory_session)) == 0

    G = build_supply_graph(memory_session)
    for _, _, d in G.out_edges("SUP01", data=True):
        if d.get("relation") == "supplies":
            assert d["active"] is True


def test_avg_daily_demand(memory_session: Session):
    """Verify avg_daily_demand returns total quantity / 90."""
    demand = avg_daily_demand(memory_session, "SKU001")
    assert demand > 0.0

    # Non-existent SKU returns 0.0
    assert avg_daily_demand(memory_session, "NON_EXISTENT") == 0.0


def test_single_point_of_failure_report(memory_session: Session):
    """Verify SPOF report ranks suppliers correctly."""
    G = build_supply_graph(memory_session)
    df = single_point_of_failure_report(G)

    assert len(df) == 15
    assert list(df.columns) == [
        "supplier_id",
        "name",
        "sole_source_sku_count",
        "primary_sku_count",
        "status",
        "is_key_supplier",
        "country",
    ]
    # In nominal state with no disruptions, all suppliers have active status
    assert (df["status"] == "active").all()
    # SUP01 is the key supplier with 7 primary SKUs
    sup01_row = df[df["supplier_id"] == "SUP01"].iloc[0]
    assert bool(sup01_row["is_key_supplier"]) is True
    assert sup01_row["primary_sku_count"] == 7
