"""Versioned snapshot models and diffing engine for replanning cycles."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class PlanSnapshot(BaseModel):
    """Complete versioned snapshot of the supply chain recovery plan at a point in time."""

    version: int = Field(description="Plan version number (1..n)")
    day: int = Field(description="Timeline day on which this plan was generated")
    trigger_events: list[str] = Field(
        default_factory=list, description="Descriptions of events that triggered this replan"
    )
    status: str = Field(description="Operational status: 'replanned' or 'stand_down'")
    down_suppliers: list[str] = Field(
        default_factory=list, description="List of suppliers currently offline or inactive"
    )
    active_delays: dict[str, int] = Field(
        default_factory=dict, description="Active transit delays by transport mode in days"
    )
    headline: dict[str, Any] = Field(
        default_factory=dict,
        description="High-level plan metrics: risk, exposures, costs, PO count, unsourced volume",
    )
    sku_view: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Per-SKU breakdown of suppliers, mode, demand forecast, coverage, and POs",
    )
    high_risk_skus: list[str] = Field(
        default_factory=list, description="SKUs projected to stock out before replenishment"
    )
    purchase_orders: list[dict[str, Any]] = Field(
        default_factory=list, description="All purchase orders planned under this version"
    )
    a2a_message_count: int = Field(
        default=0, description="Total A2A messages generated in this replanning run"
    )
    escalation_count: int = Field(
        default=0, description="Number of A2A escalation messages sent in this run"
    )
    a2a_log: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Chronological A2A message log, stamped with plan_version",
    )
    narrative: str = Field(
        default="", description="Executive narrative explaining plan adjustments"
    )
    diff: dict[str, Any] | None = Field(
        default=None, description="Structured diff against previous plan version, None for v1"
    )


def build_snapshot(
    version: int,
    day: int,
    events: list[str],
    state: dict[str, Any],
    down_suppliers: list[str],
    active_delays: dict[str, int],
) -> PlanSnapshot:
    """Build a PlanSnapshot from the final state of the War Room LangGraph execution."""
    status = state.get("status", "complete")
    is_stand_down = status in ("nominal", "stand_down")

    # Extract upstream agent results safely
    supplier_res = state.get("supplier_result") or {}
    inventory_res = state.get("inventory_result") or {}
    logistics_res = state.get("logistics_result") or {}
    demand_res = state.get("demand_result") or {}
    procurement_res = state.get("procurement_result") or {}
    customer_res = state.get("customer_impact_result") or {}

    s_data = supplier_res.get("data", {}) if isinstance(supplier_res, dict) else {}
    i_data = inventory_res.get("data", {}) if isinstance(inventory_res, dict) else {}
    l_data = logistics_res.get("data", {}) if isinstance(logistics_res, dict) else {}
    d_data = demand_res.get("data", {}) if isinstance(demand_res, dict) else {}
    p_data = procurement_res.get("data", {}) if isinstance(procurement_res, dict) else {}
    c_data = customer_res.get("data", {}) if isinstance(customer_res, dict) else {}

    final_plan = state.get("final_plan") or {}
    plan_headline = final_plan.get("headline", {})
    pos = p_data.get("purchase_orders", [])
    proc_totals = p_data.get("totals", {})
    unsourced_by_sku = p_data.get("unsourced_by_sku", {})

    if is_stand_down:
        headline = {
            "overall_risk": "low",
            "revenue_delayed": 0.0,
            "revenue_lost": 0.0,
            "sla_penalty_total": 0.0,
            "response_cost": 0.0,
            "net_financial_exposure": 0.0,
            "value_protected": 0.0,
            "total_landed_cost": 0.0,
            "po_count": 0,
            "unsourced_units": 0,
        }
        sku_view: dict[str, dict[str, Any]] = {}
        high_risk_skus: list[str] = []
        stamped_log: list[dict[str, Any]] = []
        snap_status = "stand_down"
    else:
        tot_landed = float(proc_totals.get("total_landed_cost", 0.0))
        po_cnt = int(proc_totals.get("po_count", len(pos)))
        unsourced_total = int(sum(unsourced_by_sku.values()))

        headline = {
            "overall_risk": plan_headline.get("overall_risk", "low"),
            "revenue_delayed": float(plan_headline.get("revenue_delayed", 0.0)),
            "revenue_lost": float(plan_headline.get("revenue_lost", 0.0)),
            "sla_penalty_total": float(plan_headline.get("sla_penalty_total", 0.0)),
            "response_cost": float(plan_headline.get("response_cost", 0.0)),
            "net_financial_exposure": float(plan_headline.get("net_financial_exposure", 0.0)),
            "value_protected": float(plan_headline.get("value_protected", 0.0)),
            "total_landed_cost": tot_landed,
            "po_count": po_cnt,
            "unsourced_units": unsourced_total,
        }

        # Build SKU View
        sup_per_sku = s_data.get("per_sku", {})
        inv_per_sku = i_data.get("per_sku", {})
        log_per_sku = l_data.get("per_sku", {})
        dem_per_sku = d_data.get("per_sku", {})
        proc_per_sku = p_data.get("per_sku", {})

        sku_view = {}
        for sku_id, sup_info in sorted(sup_per_sku.items()):
            rec_sup = sup_info.get("recommended", {}).get("supplier_id")
            back_sup = sup_info.get("backup", {}).get("supplier_id")

            # Recommended mode
            lanes = log_per_sku.get(sku_id, {}).get("lanes", [])
            rec_lane = next((l for l in lanes if l.get("role") == "recommended"), None)
            mode = rec_lane.get("selected", {}).get("mode") if rec_lane else None

            # Forecast and uncovered days
            dem_info = dem_per_sku.get(sku_id, {})
            forecast_daily = float(dem_info.get("forecast_daily", 0.0))
            days_uncovered = float(dem_info.get("days_uncovered", 0.0))

            # Fill rate
            inv_info = inv_per_sku.get(sku_id, {})
            fill_rate_pct = float(inv_info.get("fill_rate_pct", 100.0))

            # PO ordered and unsourced
            ordered_qty = int(proc_per_sku.get(sku_id, {}).get("ordered_qty", 0))
            unsourced_qty = int(unsourced_by_sku.get(sku_id, 0))

            sku_view[sku_id] = {
                "recommended": rec_sup,
                "backup": back_sup,
                "mode": mode,
                "forecast_daily": forecast_daily,
                "days_uncovered": days_uncovered,
                "fill_rate_pct": fill_rate_pct,
                "ordered_qty": ordered_qty,
                "unsourced_qty": unsourced_qty,
            }

        high_risk_skus = list(d_data.get("high_risk_skus", []))

        # Stamped A2A log
        raw_log = state.get("a2a_log", [])
        stamped_log = []
        for m in raw_log:
            m_dict = dict(m)
            m_dict["plan_version"] = version
            stamped_log.append(m_dict)

        snap_status = "replanned"

    msg_count = len(stamped_log)
    esc_count = sum(1 for m in stamped_log if m.get("msg_type") == "escalation")

    return PlanSnapshot(
        version=version,
        day=day,
        trigger_events=list(events),
        status=snap_status,
        down_suppliers=list(down_suppliers),
        active_delays=dict(active_delays),
        headline=headline,
        sku_view=sku_view,
        high_risk_skus=high_risk_skus,
        purchase_orders=list(pos) if not is_stand_down else [],
        a2a_message_count=msg_count,
        escalation_count=esc_count,
        a2a_log=stamped_log,
        narrative="",
        diff=None,
    )


def diff_snapshots(prev: PlanSnapshot, curr: PlanSnapshot) -> dict[str, Any]:
    """Compute structural and metric differences between two consecutive plan versions."""
    metric_deltas = {
        "net_financial_exposure": round(
            float(curr.headline.get("net_financial_exposure", 0.0))
            - float(prev.headline.get("net_financial_exposure", 0.0)),
            2,
        ),
        "total_landed_cost": round(
            float(curr.headline.get("total_landed_cost", 0.0))
            - float(prev.headline.get("total_landed_cost", 0.0)),
            2,
        ),
        "po_count": int(curr.headline.get("po_count", 0)) - int(prev.headline.get("po_count", 0)),
        "unsourced_units": int(curr.headline.get("unsourced_units", 0))
        - int(prev.headline.get("unsourced_units", 0)),
        "revenue_delayed": round(
            float(curr.headline.get("revenue_delayed", 0.0))
            - float(prev.headline.get("revenue_delayed", 0.0)),
            2,
        ),
        "sla_penalty_total": round(
            float(curr.headline.get("sla_penalty_total", 0.0))
            - float(prev.headline.get("sla_penalty_total", 0.0)),
            2,
        ),
    }

    if curr.status == "stand_down":
        return {
            "supplier_changes": [],
            "mode_changes": [],
            "metric_deltas": metric_deltas,
            "new_high_risk_skus": [],
            "resolved_high_risk_skus": list(prev.high_risk_skus),
            "risk_change": {
                "from": prev.headline.get("overall_risk", "low"),
                "to": curr.headline.get("overall_risk", "low"),
            },
        }

    # Supplier changes (recommended supplier)
    all_skus = sorted(set(prev.sku_view.keys()) | set(curr.sku_view.keys()))
    supplier_changes = []
    for sku in all_skus:
        prev_rec = prev.sku_view.get(sku, {}).get("recommended")
        curr_rec = curr.sku_view.get(sku, {}).get("recommended")
        if prev_rec and curr_rec and prev_rec != curr_rec:
            supplier_changes.append({"sku": sku, "from": prev_rec, "to": curr_rec})

    # Mode changes
    mode_changes = []
    for sku in all_skus:
        prev_mode = prev.sku_view.get(sku, {}).get("mode")
        curr_mode = curr.sku_view.get(sku, {}).get("mode")
        if prev_mode and curr_mode and prev_mode != curr_mode:
            mode_changes.append({"sku": sku, "from": prev_mode, "to": curr_mode})

    # High-risk SKUs deltas
    prev_high = set(prev.high_risk_skus)
    curr_high = set(curr.high_risk_skus)
    new_high_risk = sorted(list(curr_high - prev_high))
    resolved_high_risk = sorted(list(prev_high - curr_high))

    risk_change = {
        "from": prev.headline.get("overall_risk", "low"),
        "to": curr.headline.get("overall_risk", "low"),
    }

    return {
        "supplier_changes": supplier_changes,
        "mode_changes": mode_changes,
        "metric_deltas": metric_deltas,
        "new_high_risk_skus": new_high_risk,
        "resolved_high_risk_skus": resolved_high_risk,
        "risk_change": risk_change,
    }
