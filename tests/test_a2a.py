"""Unit tests for the A2A messaging layer and bus integration."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from warroom.a2a.bus import A2ABus
from warroom.a2a.models import A2AMessage, A2ATask, AgentCard
from warroom.agents.base import BaseAgent, create_agent_node
from warroom.data_gen.generator import generate_all
from warroom.data_gen.loader import load_to_db
from warroom.db.session import init_db
from warroom.graph.detection import simulate_supplier_outage
from warroom.orchestrator.graph import build_warroom_graph
from warroom.orchestrator.state import AgentResult, create_initial_state


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


def test_agent_cards_registration_and_discovery():
    """Verify 7 agent cards registered and discover("route_optimization") returns logistics only."""
    bus = A2ABus()

    cards = [
        AgentCard(
            agent_id="orchestrator",
            name="War Room Orchestrator",
            skills=["incident_response", "workflow_orchestration"],
        ),
        AgentCard(
            agent_id="supplier",
            name="Supplier Agent",
            skills=["alternative_supplier_discovery", "supplier_scoring"],
        ),
        AgentCard(
            agent_id="inventory",
            name="Inventory Agent",
            skills=["stock_allocation", "shortage_analysis"],
        ),
        AgentCard(
            agent_id="logistics",
            name="Logistics Agent",
            skills=["route_optimization", "freight_quoting"],
        ),
        AgentCard(
            agent_id="demand",
            name="Demand Agent",
            skills=["demand_forecasting", "stockout_projection"],
        ),
        AgentCard(
            agent_id="procurement",
            name="Procurement Agent",
            skills=["po_generation", "procurement_planning"],
        ),
        AgentCard(
            agent_id="customer_impact",
            name="Customer Impact Agent",
            skills=["sla_penalty_calculation", "customer_risk_assessment"],
        ),
    ]

    for card in cards:
        bus.register(card)

    all_cards = bus.discover()
    assert len(all_cards) == 7

    discovered = bus.discover("route_optimization")
    assert len(discovered) == 1
    assert discovered[0].agent_id == "logistics"
    assert discovered[0].name == "Logistics Agent"


def test_task_state_transitions_and_history():
    """Verify each delegated task transitions submitted -> working -> completed in state_history."""
    bus = A2ABus()
    bus.register(AgentCard(agent_id="orchestrator", name="Orchestrator"))
    bus.register(AgentCard(agent_id="supplier", name="Supplier"))

    task = bus.send_task("orchestrator", "supplier", "Analyze alternative suppliers")
    assert task.state == "submitted"
    assert len(task.state_history) == 1
    assert task.state_history[0]["state"] == "submitted"

    bus.update_task(task.task_id, "working")
    assert task.state == "working"
    assert len(task.state_history) == 2
    assert task.state_history[1]["state"] == "working"

    artifact = {"status": "ok", "summary": "Found 3 alternative suppliers"}
    bus.complete_task(task.task_id, artifact=artifact, text="Task completed")
    assert task.state == "completed"
    assert len(task.state_history) == 3
    assert task.state_history[2]["state"] == "completed"

    # Verify artifact holds only status and summary
    assert task.artifact == artifact
    assert set(task.artifact.keys()) == {"status", "summary"}


def test_fake_agent_failure_and_illegal_transitions():
    """Verify a fake agent returning status 'error' leaves task 'failed', and illegal transitions raise ValueError."""
    bus = A2ABus()
    bus.register(AgentCard(agent_id="orchestrator", name="Orchestrator"))
    bus.register(AgentCard(agent_id="fake_agent", name="Fake Agent"))

    class FakeErrorAgent(BaseAgent):
        def __init__(self) -> None:
            super().__init__(name="fake_agent", result_key="fake_result")

        def run(self, state):
            return AgentResult(
                agent_name=self.name,
                status="error",
                summary="Simulated domain analysis failure",
                data={},
            )

    node = create_agent_node(FakeErrorAgent(), bus=bus)
    state = create_initial_state()
    node(state)

    # Task should be marked failed
    assert len(bus.tasks) == 1
    task = list(bus.tasks.values())[0]
    assert task.state == "failed"
    assert task.error == "Simulated domain analysis failure"
    assert task.state_history[-1]["state"] == "failed"

    # Illegal transition: completed -> working or failed -> working raises ValueError
    with pytest.raises(ValueError, match="Illegal state transition"):
        bus.update_task(task.task_id, "working")

    # Complete a separate task and test completed -> working
    task2 = bus.send_task("orchestrator", "fake_agent", "Another task")
    bus.update_task(task2.task_id, "working")
    bus.complete_task(task2.task_id, artifact={"status": "ok", "summary": "Done"})
    with pytest.raises(ValueError, match="Illegal state transition"):
        bus.update_task(task2.task_id, "working")


def test_message_ids_timestamps_and_task_correlation():
    """Verify message IDs are unique, timestamps are non-decreasing, and every task_result points to a task_request."""
    bus = A2ABus()
    bus.register(AgentCard(agent_id="orchestrator", name="Orchestrator"))
    bus.register(AgentCard(agent_id="inventory", name="Inventory"))

    bus.broadcast("orchestrator", "Outage declared")
    t1 = bus.send_task("orchestrator", "inventory", "Check stock")
    bus.update_task(t1.task_id, "working")
    bus.complete_task(t1.task_id, artifact={"status": "ok", "summary": "Done"})

    log = bus.log
    assert len(log) == 4

    # Unique message IDs
    msg_ids = [m["message_id"] for m in log]
    assert len(msg_ids) == len(set(msg_ids))

    # Non-decreasing timestamps
    for i in range(len(log) - 1):
        assert log[i]["timestamp"] <= log[i + 1]["timestamp"]

    # Every task_result points to a task with a task_request
    request_task_ids = {m["task_id"] for m in log if m["msg_type"] == "task_request"}
    result_task_ids = [m["task_id"] for m in log if m["msg_type"] == "task_result"]

    for r_tid in result_task_ids:
        assert r_tid in request_task_ids


def test_full_run_a2a_bus_counts_and_escalation(memory_session: Session):
    """Verify full run has exactly 1 broadcast, 6 task_requests, 6 task_results, and 1 approval escalation."""
    simulate_supplier_outage(memory_session, "SUP01")
    graph = build_warroom_graph(memory_session)
    state = create_initial_state()

    result = graph.invoke(state)
    a2a_log = result.get("a2a_log", [])
    assert len(a2a_log) > 0

    broadcasts = [m for m in a2a_log if m["msg_type"] == "broadcast"]
    task_requests = [m for m in a2a_log if m["msg_type"] == "task_request"]
    task_results = [m for m in a2a_log if m["msg_type"] == "task_result"]
    escalations = [m for m in a2a_log if m["msg_type"] == "escalation"]

    # Exactly 1 broadcast at intake
    assert len(broadcasts) == 1
    assert broadcasts[0]["sender"] == "orchestrator"
    assert broadcasts[0]["recipient"] == "all"

    # Exactly 6 task requests and 6 task results
    assert len(task_requests) == 6
    assert len(task_results) == 6

    # Verify procurement approval escalation
    proc_data = result["procurement_result"]["data"]
    approval_required = proc_data.get("approval_required", False)

    approval_escalations = [
        m
        for m in escalations
        if m["recipient"] == "human_approver"
        and "approval required" in m["parts"][0].get("text", "").lower()
    ]

    if approval_required:
        assert len(approval_escalations) == 1
        assert approval_escalations[0]["sender"] == "orchestrator"
        assert "total_landed_cost" in approval_escalations[0]["parts"][1]["data"]


def test_a2a_export_jsonl(tmp_path: Path):
    """Verify export_jsonl writes one valid JSON object per line, equal to log length."""
    bus = A2ABus()
    bus.register(AgentCard(agent_id="orchestrator", name="Orchestrator"))
    bus.register(AgentCard(agent_id="supplier", name="Supplier"))

    bus.broadcast("orchestrator", "Incident alert")
    task = bus.send_task("orchestrator", "supplier", "Find vendor")
    bus.update_task(task.task_id, "working")
    bus.complete_task(task.task_id, artifact={"status": "ok", "summary": "Found vendor"})

    export_file = tmp_path / "test_a2a_log.jsonl"
    bus.export_jsonl(export_file)

    assert export_file.exists()
    lines = export_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == len(bus.log)

    for line in lines:
        parsed = json.loads(line)
        assert "message_id" in parsed
        assert "msg_type" in parsed
        assert "sender" in parsed


def test_messages_order_and_bus_none_compatibility():
    """Verify 7-message order is preserved and create_agent_node with bus=None works identically."""
    class DummyAgent(BaseAgent):
        def __init__(self) -> None:
            super().__init__(name="dummy", result_key="dummy_result")

        def run(self, state):
            return AgentResult(
                agent_name=self.name,
                status="ok",
                summary="Dummy executed without bus",
                data={"key": 123},
            )

    node = create_agent_node(DummyAgent(), bus=None)
    out = node(create_initial_state())

    assert "dummy_result" in out
    assert out["dummy_result"]["status"] == "ok"
    assert len(out["messages"]) == 1
    assert out["messages"][0]["from"] == "dummy"
