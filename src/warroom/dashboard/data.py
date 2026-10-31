"""Pure data loading, transformation, and network framing functions for the War Room dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import networkx as nx
import pandas as pd
from sqlalchemy.orm import Session

from warroom.db.session import get_session
from warroom.graph.builder import build_supply_graph
from warroom.replanning.engine import ReplanEngine
from warroom.replanning.scenario import default_scenario


def load_timeline(path: str | Path) -> list[dict[str, Any]]:
    """Load the versioned plan snapshots timeline from JSON; return [] if missing."""
    file_path = Path(path)
    if not file_path.exists():
        return []
    try:
        content = file_path.read_text(encoding="utf-8")
        return json.loads(content)
    except Exception:
        return []


def load_a2a_log(path: str | Path) -> list[dict[str, Any]]:
    """Load stamped A2A messages from a JSONL file; return [] if missing."""
    file_path = Path(path)
    if not file_path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records
    except Exception:
        return []


def ensure_data(out_dir: str | Path) -> tuple[Path, Path]:
    """Ensure timeline and A2A log files exist in out_dir, generating them via ReplanEngine if needed."""
    out_path = Path(out_dir)
    timeline_path = out_path / "timeline.json"
    log_path = out_path / "a2a_replan_log.jsonl"

    if not timeline_path.exists() or not log_path.exists():
        session = get_session()
        try:
            engine = ReplanEngine(session)
            events = default_scenario()
            snapshots = engine.run(events)
            engine.write_outputs(snapshots, out_path)
        finally:
            session.close()

    return timeline_path, log_path


def timeline_df(snapshots: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert a list of plan snapshots into a DataFrame with one row per version."""
    columns = [
        "version",
        "day",
        "status",
        "overall_risk",
        "net_financial_exposure",
        "sla_penalty_total",
        "response_cost",
        "revenue_lost",
        "revenue_delayed",
        "value_protected",
        "total_landed_cost",
        "po_count",
        "unsourced_units",
        "escalation_count",
        "down_suppliers",
        "trigger",
    ]
    if not snapshots:
        return pd.DataFrame(columns=columns)

    rows = []
    for s in snapshots:
        hl = s.get("headline", {})
        down = s.get("down_suppliers", [])
        triggers = s.get("trigger_events", [])
        trig_str = "; ".join(triggers) if triggers else "Baseline"

        row = {
            "version": int(s.get("version", 0)),
            "day": int(s.get("day", 0)),
            "status": str(s.get("status", "")),
            "overall_risk": str(hl.get("overall_risk", "low")),
            "net_financial_exposure": float(hl.get("net_financial_exposure", 0.0)),
            "sla_penalty_total": float(hl.get("sla_penalty_total", 0.0)),
            "response_cost": float(hl.get("response_cost", 0.0)),
            "revenue_lost": float(hl.get("revenue_lost", 0.0)),
            "revenue_delayed": float(hl.get("revenue_delayed", 0.0)),
            "value_protected": float(hl.get("value_protected", 0.0)),
            "total_landed_cost": float(hl.get("total_landed_cost", 0.0)),
            "po_count": int(hl.get("po_count", 0)),
            "unsourced_units": int(hl.get("unsourced_units", 0)),
            "escalation_count": int(s.get("escalation_count", 0)),
            "down_suppliers": ", ".join(down) if down else "None",
            "trigger": trig_str,
        }
        rows.append(row)

    return pd.DataFrame(rows, columns=columns)


def sku_df(snapshot: dict[str, Any]) -> pd.DataFrame:
    """Extract per-SKU risk and replenishment metrics from a snapshot.

    Returns an empty DataFrame for stand_down snapshots.
    """
    columns = [
        "sku_id",
        "recommended",
        "backup",
        "mode",
        "forecast_daily",
        "days_uncovered",
        "fill_rate_pct",
        "ordered_qty",
        "unsourced_qty",
    ]
    if not snapshot or snapshot.get("status") == "stand_down":
        return pd.DataFrame(columns=columns)

    sku_view = snapshot.get("sku_view", {})
    if not sku_view:
        return pd.DataFrame(columns=columns)

    rows = []
    for sku_id, info in sorted(sku_view.items()):
        row = {
            "sku_id": sku_id,
            "recommended": info.get("recommended"),
            "backup": info.get("backup"),
            "mode": info.get("mode"),
            "forecast_daily": float(info.get("forecast_daily", 0.0)),
            "days_uncovered": float(info.get("days_uncovered", 0.0)),
            "fill_rate_pct": float(info.get("fill_rate_pct", 100.0)),
            "ordered_qty": int(info.get("ordered_qty", 0)),
            "unsourced_qty": int(info.get("unsourced_qty", 0)),
        }
        rows.append(row)

    return pd.DataFrame(rows, columns=columns)


def po_df(snapshot: dict[str, Any]) -> pd.DataFrame:
    """Extract purchase order details from a snapshot into a DataFrame."""
    columns = [
        "po_id",
        "supplier_id",
        "sku_id",
        "role",
        "quantity",
        "unit_price",
        "freight_mode",
        "freight_cost",
        "line_cost",
        "expected_arrival",
        "urgency",
        "premium_vs_baseline",
    ]
    if not snapshot or snapshot.get("status") == "stand_down":
        return pd.DataFrame(columns=columns)

    pos = snapshot.get("purchase_orders", [])
    if not pos:
        return pd.DataFrame(columns=columns)

    rows = []
    for po in pos:
        row = {
            "po_id": po.get("po_id", ""),
            "supplier_id": po.get("supplier_id", ""),
            "sku_id": po.get("sku_id", ""),
            "role": str(po.get("role", "")).upper(),
            "quantity": int(po.get("quantity", 0)),
            "unit_price": float(po.get("unit_price", 0.0)),
            "freight_mode": str(po.get("freight_mode", "")).upper(),
            "freight_cost": float(po.get("freight_cost", 0.0)),
            "line_cost": float(po.get("line_cost", 0.0)),
            "expected_arrival": str(po.get("expected_arrival", "")),
            "urgency": str(po.get("urgency", "")).upper(),
            "premium_vs_baseline": float(po.get("premium_vs_baseline", 0.0)),
        }
        rows.append(row)

    return pd.DataFrame(rows, columns=columns)


def messages_df(
    log: list[dict[str, Any]], version: int | None = None
) -> pd.DataFrame:
    """Extract A2A messages into a DataFrame, optionally filtered by plan_version."""
    columns = [
        "message_id",
        "plan_version",
        "sender",
        "recipient",
        "msg_type",
        "task_id",
        "text",
        "timestamp",
    ]
    if not log:
        return pd.DataFrame(columns=columns)

    filtered = log
    if version is not None:
        filtered = [m for m in log if m.get("plan_version") == version]

    rows = []
    for m in filtered:
        parts = m.get("parts", [])
        text = next(
            (p.get("text", "") for p in parts if p.get("kind") == "text"), ""
        )
        row = {
            "message_id": m.get("message_id", ""),
            "plan_version": m.get("plan_version", 1),
            "sender": m.get("sender", ""),
            "recipient": m.get("recipient", ""),
            "msg_type": m.get("msg_type", ""),
            "task_id": m.get("task_id") or "-",
            "text": text,
            "timestamp": m.get("timestamp", ""),
        }
        rows.append(row)

    return pd.DataFrame(rows, columns=columns)


def network_frame(
    session: Session, snapshot: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build supply chain network node and edge DataFrames under snapshot conditions.

    Read-only: does not mutate or simulate any database records.
    """
    G = build_supply_graph(session)

    col_mapping = {
        "supplier": 0,
        "sku": 1,
        "warehouse": 2,
        "customer": 3,
    }

    nodes_by_col: dict[int, list[str]] = {0: [], 1: [], 2: [], 3: []}
    for node_id, data in G.nodes(data=True):
        nt = data.get("node_type", "other")
        col = col_mapping.get(nt, 0)
        nodes_by_col[col].append(node_id)

    max_count = max(len(nds) for nds in nodes_by_col.values()) if nodes_by_col else 1
    step = 1.0 / (max_count - 1) if max_count > 1 else 1.0

    pos: dict[str, tuple[float, float]] = {}
    for col, nds in nodes_by_col.items():
        sorted_nds = sorted(nds)
        n = len(sorted_nds)
        if n == 0:
            continue
        start_y = (1.0 - (n - 1) * step) / 2.0
        for i, node_id in enumerate(sorted_nds):
            pos[node_id] = (float(col), float(start_y + i * step))

    is_stand_down = snapshot.get("status") == "stand_down"
    # If the plan is stood down, all primary disruptions are cleared -> no supplier failed
    down_suppliers: set[str] = set() if is_stand_down else set(snapshot.get("down_suppliers", []))

    sku_view = snapshot.get("sku_view", {})
    rec_suppliers = {
        info.get("recommended") for info in sku_view.values() if info.get("recommended")
    }
    backup_suppliers = {
        info.get("backup") for info in sku_view.values() if info.get("backup")
    }

    # 1. Build Nodes DataFrame
    node_rows = []
    for node_id, data in G.nodes(data=True):
        x, y = pos[node_id]
        node_type = data.get("node_type", "unknown")
        name = data.get("name", node_id)
        status = data.get("status", "active")
        reliability = data.get("reliability_score")

        if node_type == "supplier":
            if node_id in down_suppliers:
                supplier_state = "failed"
            elif node_id in rec_suppliers:
                supplier_state = "recommended"
            elif node_id in backup_suppliers:
                supplier_state = "backup"
            else:
                supplier_state = "other"
            hover = (
                f"<b>Supplier: {node_id} ({name})</b><br>"
                f"State in Plan: {supplier_state.upper()}<br>"
                f"Status in DB: {status}<br>"
                f"Country: {data.get('country', 'N/A')}<br>"
                f"Reliability: {reliability if reliability is not None else 'N/A'}<br>"
                f"Lead Time: {data.get('lead_time_days', 0)}d"
            )
        elif node_type == "sku":
            supplier_state = "sku"
            sku_info = sku_view.get(node_id, {})
            hover = (
                f"<b>SKU: {node_id} ({name})</b><br>"
                f"Category: {data.get('category', 'N/A')}<br>"
                f"Unit Price: ${data.get('unit_price', 0.0):.2f}<br>"
                f"Fill Rate: {sku_info.get('fill_rate_pct', 100.0):.1f}%<br>"
                f"Days Uncovered: {sku_info.get('days_uncovered', 0.0):.1f}d"
            )
        elif node_type == "warehouse":
            supplier_state = "warehouse"
            hover = (
                f"<b>Warehouse: {node_id} ({name})</b><br>"
                f"Location: {data.get('city', '')}, {data.get('country', '')}<br>"
                f"Capacity: {data.get('capacity', 0):,} units"
            )
        elif node_type == "customer":
            supplier_state = "customer"
            hover = (
                f"<b>Customer: {node_id} ({name})</b><br>"
                f"Tier: {str(data.get('tier', '')).upper()}<br>"
                f"Region: {data.get('region', '')}"
            )
        else:
            supplier_state = "other"
            hover = f"<b>{node_id}</b>"

        node_rows.append(
            {
                "node_id": node_id,
                "node_type": node_type,
                "label": name if len(name) <= 18 else node_id,
                "x": float(x),
                "y": float(y),
                "supplier_state": supplier_state,
                "status": status,
                "reliability": float(reliability) if reliability is not None else None,
                "hover_text": hover,
            }
        )

    nodes_df = pd.DataFrame(node_rows)

    # 2. Build Edges DataFrame
    edge_rows = []
    for u, v, data in G.edges(data=True):
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        relation = data.get("relation", "")

        if relation == "supplies":
            is_primary = bool(data.get("is_primary", False))
            sku_rec = sku_view.get(v, {}).get("recommended")

            if u in down_suppliers and is_primary:
                edge_class = "primary_lost"
            elif sku_rec == u:
                edge_class = "active_plan"
            else:
                edge_class = "other"

            hover = (
                f"Supply Lane: {u} -> {v}<br>"
                f"Class: {edge_class.upper()}<br>"
                f"Primary: {is_primary}<br>"
                f"Unit Price: ${data.get('unit_price', 0.0):.2f}<br>"
                f"Lead Time: {data.get('lead_time_days', 0)}d"
            )
        elif relation == "stocked_at":
            edge_class = "other"
            hover = (
                f"Inventory: {u} stocked at {v}<br>"
                f"On Hand: {data.get('on_hand', 0):,}<br>"
                f"Safety Stock: {data.get('safety_stock', 0):,}"
            )
        elif relation == "ordered_by":
            edge_class = "other"
            hover = (
                f"Order Demand: {u} ordered by {v}<br>"
                f"Open Orders: {data.get('open_order_count', 0)}<br>"
                f"Open Qty: {data.get('open_quantity', 0):,}"
            )
        else:
            edge_class = "other"
            hover = f"{u} -> {v}"

        edge_rows.append(
            {
                "source": u,
                "target": v,
                "relation": relation,
                "edge_class": edge_class,
                "x0": float(x0),
                "y0": float(y0),
                "x1": float(x1),
                "y1": float(y1),
                "hover_text": hover,
            }
        )

    edges_df = pd.DataFrame(edge_rows)

    return nodes_df, edges_df
