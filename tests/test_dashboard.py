"""Unit tests for the dashboard data layer, Plotly figures, and network framing."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from warroom.dashboard.data import (
    load_a2a_log,
    load_timeline,
    messages_df,
    network_frame,
    po_df,
    sku_df,
    timeline_df,
)
from warroom.dashboard.figures import (
    agent_timeline,
    exposure_trajectory,
    po_breakdown,
    sku_risk,
    supply_network,
)
from warroom.data_gen.generator import generate_all
from warroom.data_gen.loader import load_to_db
from warroom.db.models import Order, Supplier
from warroom.db.session import init_db
from warroom.replanning.engine import ReplanEngine
from warroom.replanning.scenario import default_scenario


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


def test_import_data_and_figures_without_streamlit():
    """Verify warroom.dashboard.figures and warroom.dashboard.data can be imported without importing streamlit."""
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path('src').resolve()))\n"
        "import warroom.dashboard.data\n"
        "import warroom.dashboard.figures\n"
        "assert 'streamlit' not in sys.modules, 'streamlit was unexpectedly imported by data or figures module!'\n"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, f"Import check failed with output: {res.stderr}"


def test_missing_files_return_empty_lists(tmp_path: Path):
    """Verify load_timeline and load_a2a_log return [] when files do not exist."""
    missing_json = tmp_path / "does_not_exist.json"
    missing_jsonl = tmp_path / "does_not_exist.jsonl"

    assert load_timeline(missing_json) == []
    assert load_a2a_log(missing_jsonl) == []


def test_timeline_and_sku_dfs_generation(memory_session: Session, tmp_path: Path):
    """Verify timeline_df produces 5 rows and sku_df produces 7 rows for v1 and 0 rows for v5."""
    engine = ReplanEngine(memory_session)
    snapshots = engine.run(default_scenario())
    timeline_file, log_file = engine.write_outputs(snapshots, tmp_path)

    loaded_snapshots = load_timeline(timeline_file)
    assert len(loaded_snapshots) == 5

    tdf = timeline_df(loaded_snapshots)
    assert len(tdf) == 5
    assert list(tdf["version"]) == [1, 2, 3, 4, 5]

    # Version 1 SKU breakdown has 7 SKUs
    v1_sku_df = sku_df(loaded_snapshots[0])
    assert len(v1_sku_df) == 7
    assert set(v1_sku_df["sku_id"]) == {f"SKU00{i}" for i in range(1, 8)}

    # Version 5 stand_down SKU breakdown is empty
    v5_sku_df = sku_df(loaded_snapshots[4])
    assert len(v5_sku_df) == 0
    assert v5_sku_df.empty


def test_network_frame_states_and_db_immutability(memory_session: Session):
    """Verify network_frame marks SUP01 failed in v1, no supplier failed in v5, and leaves DB untouched."""
    engine = ReplanEngine(memory_session)
    snapshots = engine.run(default_scenario())
    v1_snap = snapshots[0].model_dump()
    v5_snap = snapshots[4].model_dump()

    # Capture initial DB state
    init_statuses = {
        s.supplier_id: s.status
        for s in memory_session.scalars(select(Supplier)).all()
    }
    init_order_count = memory_session.scalar(select(func.count(Order.order_id)))

    # 1. Version 1 Frame: SUP01 should be marked "failed"
    nodes_v1, edges_v1 = network_frame(memory_session, v1_snap)
    sup01_row = nodes_v1[nodes_v1["node_id"] == "SUP01"]
    assert not sup01_row.empty
    assert sup01_row.iloc[0]["supplier_state"] == "failed"

    # 2. Version 5 Frame (stand_down): no supplier should be marked "failed"
    nodes_v5, edges_v5 = network_frame(memory_session, v5_snap)
    failed_v5 = nodes_v5[nodes_v5["supplier_state"] == "failed"]
    assert len(failed_v5) == 0

    # 3. Verify DB remained completely unchanged
    after_statuses = {
        s.supplier_id: s.status
        for s in memory_session.scalars(select(Supplier)).all()
    }
    after_order_count = memory_session.scalar(select(func.count(Order.order_id)))

    assert after_statuses == init_statuses
    assert after_order_count == init_order_count


def test_figures_serialization_and_trajectory_entries(
    memory_session: Session, tmp_path: Path
):
    """Verify all figure functions produce valid figures that serialize with to_json() for v1 and v5."""
    engine = ReplanEngine(memory_session)
    snapshots = engine.run(default_scenario())
    timeline_file, log_file = engine.write_outputs(snapshots, tmp_path)

    loaded_snapshots = load_timeline(timeline_file)
    loaded_log = load_a2a_log(log_file)
    tdf = timeline_df(loaded_snapshots)

    # 1. Exposure trajectory has one x entry per version
    fig_traj = exposure_trajectory(tdf, selected_version=1)
    assert len(fig_traj.data[0].x) == 5
    assert json.loads(fig_traj.to_json())

    # 2. Test all figures for version 1 (populated)
    v1_snap = loaded_snapshots[0]
    nodes_v1, edges_v1 = network_frame(memory_session, v1_snap)

    fig_net_v1 = supply_network(nodes_v1, edges_v1)
    fig_risk_v1 = sku_risk(sku_df(v1_snap))
    fig_po_v1 = po_breakdown(po_df(v1_snap))
    fig_msg_v1 = agent_timeline(messages_df(loaded_log, version=1))

    for fig in (fig_net_v1, fig_risk_v1, fig_po_v1, fig_msg_v1):
        parsed = json.loads(fig.to_json())
        assert isinstance(parsed, dict)

    # 3. Test all figures for version 5 (stand_down / empty case must not raise)
    v5_snap = loaded_snapshots[4]
    nodes_v5, edges_v5 = network_frame(memory_session, v5_snap)

    fig_net_v5 = supply_network(nodes_v5, edges_v5)
    fig_risk_v5 = sku_risk(sku_df(v5_snap))
    fig_po_v5 = po_breakdown(po_df(v5_snap))
    fig_msg_v5 = agent_timeline(messages_df(loaded_log, version=5))

    for fig in (fig_net_v5, fig_risk_v5, fig_po_v5, fig_msg_v5):
        parsed = json.loads(fig.to_json())
        assert isinstance(parsed, dict)
