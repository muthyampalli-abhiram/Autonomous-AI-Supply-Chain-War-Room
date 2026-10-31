"""Unit and integration tests for dynamic replanning timeline and versioned snapshots."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from warroom.db.models import Order, Supplier
from warroom.db.session import init_db
from warroom.data_gen.generator import generate_all
from warroom.data_gen.loader import load_to_db
from warroom.graph.detection import restore_supplier, simulate_supplier_outage
from warroom.orchestrator.graph import build_warroom_graph
from warroom.orchestrator.state import create_initial_state
from warroom.replanning.engine import ReplanEngine, write_outputs
from warroom.replanning.events import SimEvent, apply_event
from warroom.replanning.scenario import default_scenario
from warroom.tools.registry import call_tool


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


def test_default_scenario_structure():
    """Verify default_scenario has exactly 5 events on days 0, 3, 6, 10, 14 in chronological order."""
    events = default_scenario()
    assert len(events) == 5
    assert [e.day for e in events] == [0, 3, 6, 10, 14]
    for e in events:
        assert len(e.description.strip()) > 0
        assert e.event_id.startswith("EVT-")


def test_apply_event_unknown_type_raises(memory_session: Session):
    """Verify apply_event raises ValueError when given an unrecognized event_type."""
    bad_event = SimEvent(
        event_id="EVT-BAD",
        day=1,
        event_type="unknown_event_type",
        params={},
        description="Invalid event",
    )
    with pytest.raises(ValueError, match="Unknown event type"):
        apply_event(memory_session, bad_event)


def test_replanning_five_snapshots_and_stand_down(memory_session: Session):
    """Verify engine returns 5 snapshots with versions 1..5; v1-4 replanned, v5 stand_down."""
    engine = ReplanEngine(memory_session)
    snapshots = engine.run(default_scenario())

    assert len(snapshots) == 5
    assert [s.version for s in snapshots] == [1, 2, 3, 4, 5]

    for s in snapshots[:4]:
        assert s.status == "replanned"
        assert len(s.sku_view) > 0
        assert s.a2a_message_count > 0

    # Version 5 is stand_down
    v5 = snapshots[4]
    assert v5.status == "stand_down"
    assert v5.sku_view == {}
    assert v5.a2a_message_count == 0
    assert v5.a2a_log == []
    assert v5.headline["net_financial_exposure"] == 0.0
    assert v5.headline["po_count"] == 0


def test_version_1_matches_single_compiled_graph_run(memory_session: Session):
    """Verify version 1 matches a plain single run of the compiled graph on SUP01 outage."""
    # 1. Plain single run
    simulate_supplier_outage(memory_session, "SUP01")
    single_graph = build_warroom_graph(memory_session)
    single_res = single_graph.invoke(create_initial_state())
    restore_supplier(memory_session, "SUP01")

    expected_sup_rec = {
        sku_id: info["recommended"]["supplier_id"]
        for sku_id, info in single_res["supplier_result"]["data"]["per_sku"].items()
    }
    expected_net_exposure = single_res["customer_impact_result"]["data"]["financials"][
        "net_financial_exposure"
    ]

    # 2. Replanning run
    engine = ReplanEngine(memory_session)
    snapshots = engine.run(default_scenario())
    v1 = snapshots[0]

    assert v1.version == 1
    assert v1.day == 0
    assert v1.headline["net_financial_exposure"] == expected_net_exposure

    for sku_id, rec_sup in expected_sup_rec.items():
        assert v1.sku_view[sku_id]["recommended"] == rec_sup


def test_carrier_delay_mode_changes_and_active_delays(memory_session: Session):
    """Verify version 2 lists air delay 6 in active_delays; mode_changes non-empty and every change from air."""
    engine = ReplanEngine(memory_session)
    snapshots = engine.run(default_scenario())
    v2 = snapshots[1]

    assert v2.active_delays.get("air") == 6
    assert v2.diff is not None

    mode_changes = v2.diff.get("mode_changes", [])
    assert len(mode_changes) > 0, "Expected freight mode changes after air transit delay was introduced"
    for mc in mode_changes:
        assert mc["from"].lower() == "air", f"Expected mode shift away from air, got: {mc}"


def test_sup07_outage_reroutes_sku005(memory_session: Session):
    """Verify SUP07 outage removes it as recommended for SKU005, diff records change, and no PO uses SUP07."""
    engine = ReplanEngine(memory_session)
    snapshots = engine.run(default_scenario())

    v2 = snapshots[1]
    v3 = snapshots[2]
    v4 = snapshots[3]

    # Precondition: SUP07 is recommended supplier for SKU005 in v2
    assert v2.sku_view["SKU005"]["recommended"] == "SUP07"

    # In v3: SUP07 is offline and cannot be recommended
    assert v3.sku_view["SKU005"]["recommended"] != "SUP07"

    # Diff records SKU005 change from SUP07
    sup_changes = v3.diff.get("supplier_changes", [])
    sku5_change = next((c for c in sup_changes if c["sku"] == "SKU005"), None)
    assert sku5_change is not None, "Expected supplier change recorded for SKU005 in v3 diff"
    assert sku5_change["from"] == "SUP07"

    # No PO in v3 or v4 uses SUP07
    for v in (v3, v4):
        for po in v.purchase_orders:
            assert po["supplier_id"] != "SUP07", f"PO {po['po_id']} in v{v.version} unexpectedly used down supplier SUP07"


def test_demand_surge_increases_forecast_daily(memory_session: Session):
    """Verify demand surge event increases SKU004 forecast_daily in version 4 compared to version 3."""
    engine = ReplanEngine(memory_session)
    snapshots = engine.run(default_scenario())

    v3_fc = snapshots[2].sku_view["SKU004"]["forecast_daily"]
    v4_fc = snapshots[3].sku_view["SKU004"]["forecast_daily"]

    assert v4_fc > v3_fc, f"Expected SKU004 forecast_daily to rise after surge (v3={v3_fc}, v4={v4_fc})"


def test_no_po_ever_uses_down_suppliers(memory_session: Session):
    """Verify that no purchase order in any snapshot ever sources from a down supplier."""
    engine = ReplanEngine(memory_session)
    snapshots = engine.run(default_scenario())

    for s in snapshots:
        down_set = set(s.down_suppliers)
        for po in s.purchase_orders:
            sup = po["supplier_id"]
            assert (
                sup not in down_set
            ), f"PO {po['po_id']} in v{s.version} used supplier {sup} which is offline: {down_set}"


def test_cleanup_guarantee_on_success_and_exception(memory_session: Session, monkeypatch: pytest.MonkeyPatch):
    """Verify guaranteed rollback of supplier statuses, order counts, and active delays on success and error."""
    # 1. Baseline state
    init_statuses = {
        s.supplier_id: s.status
        for s in memory_session.scalars(select(Supplier)).all()
    }
    init_order_count = memory_session.scalar(select(func.count(Order.order_id)))
    init_delays = dict(call_tool("get_active_delays"))

    engine = ReplanEngine(memory_session)

    # Success run
    engine.run(default_scenario())

    after_statuses = {
        s.supplier_id: s.status
        for s in memory_session.scalars(select(Supplier)).all()
    }
    after_order_count = memory_session.scalar(select(func.count(Order.order_id)))
    after_delays = dict(call_tool("get_active_delays"))

    assert after_statuses == init_statuses
    assert after_order_count == init_order_count
    assert after_delays == init_delays

    # 2. Simulated failure midway on day 6
    orig_apply = apply_event

    def mock_apply(session: Session, event: SimEvent):
        if event.day == 6:
            raise RuntimeError("Simulated failure during day 6 event execution")
        return orig_apply(session, event)

    monkeypatch.setattr("warroom.replanning.engine.apply_event", mock_apply)

    with pytest.raises(RuntimeError, match="Simulated failure during day 6"):
        engine.run(default_scenario())

    # Check cleanup occurred despite error
    err_statuses = {
        s.supplier_id: s.status
        for s in memory_session.scalars(select(Supplier)).all()
    }
    err_order_count = memory_session.scalar(select(func.count(Order.order_id)))
    err_delays = dict(call_tool("get_active_delays"))

    assert err_statuses == init_statuses
    assert err_order_count == init_order_count
    assert err_delays == init_delays


def test_determinism_json_serialization_and_write_outputs(
    memory_session: Session, tmp_path: Path
):
    """Verify two runs produce identical headlines, snapshots serialize to JSON, and write_outputs creates files."""
    engine = ReplanEngine(memory_session)

    snaps1 = engine.run(default_scenario())
    snaps2 = engine.run(default_scenario())

    for s1, s2 in zip(snaps1, snaps2):
        assert s1.headline == s2.headline
        assert s1.status == s2.status
        assert s1.down_suppliers == s2.down_suppliers

    # JSON serialization check
    for s in snaps1:
        dumped = json.dumps(s.model_dump(), default=str)
        assert len(dumped) > 0

    # Test write_outputs
    out_dir = tmp_path / "replan_artifacts"
    timeline_file, replan_log_file = engine.write_outputs(snaps1, out_dir)

    assert timeline_file.exists()
    assert replan_log_file.exists()

    timeline_data = json.loads(timeline_file.read_text(encoding="utf-8"))
    assert len(timeline_data) == 5
    for item in timeline_data:
        assert "a2a_log" not in item
        assert "headline" in item

    log_lines = replan_log_file.read_text(encoding="utf-8").strip().split("\n")
    total_messages = sum(s.a2a_message_count for s in snaps1)
    assert len(log_lines) == total_messages

    for line in log_lines:
        parsed = json.loads(line)
        assert "message_id" in parsed
        assert "plan_version" in parsed


def test_a2a_log_stamped_with_plan_version(memory_session: Session):
    """Verify every message in a2a_log is stamped with the corresponding plan_version."""
    engine = ReplanEngine(memory_session)
    snapshots = engine.run(default_scenario())

    for s in snapshots[:4]:
        assert len(s.a2a_log) > 0
        for msg in s.a2a_log:
            assert msg.get("plan_version") == s.version
