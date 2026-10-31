"""Unit tests for the War Room LangGraph orchestrator and stub agents."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from warroom.agents.base import BaseAgent, create_agent_node
from warroom.agents.stubs import (
    CustomerImpactAgent,
    DemandAgent,
    InventoryAgent,
    LogisticsAgent,
    ProcurementAgent,
    SupplierAgent,
)
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


def test_orchestrator_nominal_condition(memory_session: Session):
    """With no disruption: final status is 'nominal' and no agent result is set."""
    graph = build_warroom_graph(memory_session)
    state = create_initial_state()

    result = graph.invoke(state)

    assert result["status"] == "nominal"
    assert result.get("disruption") is None
    assert result.get("final_plan") is None
    assert result.get("supplier_result") is None
    assert result.get("inventory_result") is None
    assert result.get("logistics_result") is None
    assert result.get("demand_result") is None
    assert result.get("procurement_result") is None
    assert result.get("customer_impact_result") is None
    assert result.get("messages") == []


def test_orchestrator_with_sup01_outage(memory_session: Session):
    """With SUP01 outage: all 6 agent results exist, status is 'complete', and message order is correct."""
    simulate_supplier_outage(memory_session, "SUP01")

    graph = build_warroom_graph(memory_session)
    state = create_initial_state()

    result = graph.invoke(state)

    # 1. Final status
    assert result["status"] == "complete"
    assert result.get("disruption") is not None
    assert result["disruption"]["supplier_id"] == "SUP01"

    # 2. All six agent results exist and have ok status
    agent_result_keys = [
        "supplier_result",
        "inventory_result",
        "logistics_result",
        "demand_result",
        "procurement_result",
        "customer_impact_result",
    ]
    for key in agent_result_keys:
        res = result.get(key)
        assert res is not None, f"Expected {key} to be populated in state"
        assert res["status"] == "ok"
        assert len(res["summary"]) > 0

    # 3. Message order is exactly: orchestrator, supplier, inventory, logistics, demand, procurement, customer_impact
    messages = result.get("messages", [])
    assert len(messages) == 7

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

    # 4. Final plan contains disruption id and six agent summaries
    plan = result.get("final_plan")
    assert plan is not None
    assert plan["status"] == "complete"
    assert plan["plan_version"] == 1
    assert plan["disruption_id"] == "DISR-SUP01"

    summaries = plan.get("agent_summaries", {})
    assert len(summaries) == 6

    expected_agents = [
        "supplier",
        "inventory",
        "logistics",
        "demand",
        "procurement",
        "customer_impact",
    ]
    for agent_name in expected_agents:
        assert agent_name in summaries
        assert "DISR-SUP01" in summaries[agent_name]


def test_stub_agent_node_execution():
    """Verify stub agents and create_agent_node helper in isolation."""
    stubs = [
        (SupplierAgent(), "supplier", "supplier_result"),
        (InventoryAgent(), "inventory", "inventory_result"),
        (LogisticsAgent(), "logistics", "logistics_result"),
        (DemandAgent(), "demand", "demand_result"),
        (ProcurementAgent(), "procurement", "procurement_result"),
        (CustomerImpactAgent(), "customer_impact", "customer_impact_result"),
    ]

    mock_state = create_initial_state()
    mock_state["disruption"] = {"event_id": "DISR-TEST99", "supplier_id": "TEST99"}

    for agent, expected_name, expected_key in stubs:
        assert agent.name == expected_name
        assert agent.result_key == expected_key

        node_fn = create_agent_node(agent)
        node_output = node_fn(mock_state)

        assert expected_key in node_output
        res = node_output[expected_key]
        assert res["agent_name"] == expected_name
        assert res["status"] == "ok"
        assert "DISR-TEST99" in res["summary"]

        assert "messages" in node_output
        assert len(node_output["messages"]) == 1
        msg = node_output["messages"][0]
        assert msg["from"] == expected_name
        assert msg["to"] == "orchestrator"
        assert msg["type"] == "result"
        assert "DISR-TEST99" in msg["summary"]
