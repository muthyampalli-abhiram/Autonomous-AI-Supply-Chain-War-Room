"""Procurement Agent generating purchase orders, landed cost calculations, and approval routing."""

from __future__ import annotations

import datetime
import math
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from warroom.agents.base import BaseAgent
from warroom.agents.llm import narrate
from warroom.db.models import SupplierSKU
from warroom.orchestrator.state import AgentResult, WarRoomState

ORDER_MULTIPLE: int = 10
APPROVAL_THRESHOLD_USD: float = 100000.0


class ProcurementAgent(BaseAgent):
    """Deterministic procurement agent creating purchase orders across evaluated supply lanes."""

    def __init__(self, session: Session) -> None:
        super().__init__(name="procurement", result_key="procurement_result")
        self.session = session

    def run(self, state: WarRoomState) -> AgentResult:
        start_time = datetime.datetime.now(datetime.timezone.utc)
        disruption = state.get("disruption") or {}
        failed_supplier = disruption.get("supplier_id", "SUP01")
        disruption_id = disruption.get("event_id") or f"DISR-{failed_supplier}"

        supplier_res = state.get("supplier_result")
        inventory_res = state.get("inventory_result")
        logistics_res = state.get("logistics_result")
        demand_res = state.get("demand_result")

        def _get_status_data(res: Any) -> tuple[str | None, dict[str, Any] | None]:
            if isinstance(res, AgentResult):
                return res.status, res.data
            if isinstance(res, dict):
                return res.get("status"), res.get("data")
            return None, None

        s_status, s_data = _get_status_data(supplier_res)
        i_status, i_data = _get_status_data(inventory_res)
        l_status, l_data = _get_status_data(logistics_res)
        d_status, d_data = _get_status_data(demand_res)

        if (
            s_status != "ok"
            or i_status != "ok"
            or l_status != "ok"
            or d_status != "ok"
            or not isinstance(s_data, dict)
            or not isinstance(i_data, dict)
            or not isinstance(l_data, dict)
            or not isinstance(d_data, dict)
        ):
            return AgentResult(
                agent_name=self.name,
                status="error",
                summary=(
                    f"Procurement planning for {disruption_id} failed: "
                    "supplier_result, inventory_result, logistics_result, and demand_result are all required."
                ),
                data={},
                started_at=start_time,
                finished_at=datetime.datetime.now(datetime.timezone.utc),
            )

        coverage_days = int(disruption.get("expected_duration_days") or 30)

        # Baseline prices of the disrupted supplier
        baseline_prices: dict[str, float] = {}
        links = self.session.scalars(
            select(SupplierSKU).where(SupplierSKU.supplier_id == failed_supplier)
        ).all()
        for link in links:
            baseline_prices[link.sku_id] = float(link.unit_price)

        critical_skus = set(i_data.get("critical_skus", []))
        high_risk_skus = set(d_data.get("high_risk_skus", []))

        per_sku_supplier = s_data.get("per_sku", {})
        inv_per_sku = i_data.get("per_sku", {})
        log_per_sku = l_data.get("per_sku", {})
        demand_per_sku = d_data.get("per_sku", {})

        purchase_orders: list[dict[str, Any]] = []
        per_sku_summary: dict[str, Any] = {}
        po_counter = 1

        for sku_id in sorted(per_sku_supplier.keys()):
            on_hand = int(inv_per_sku.get(sku_id, {}).get("on_hand", 0))
            total_safety_stock = int(inv_per_sku.get(sku_id, {}).get("safety_stock", 0))
            forecast_daily = float(demand_per_sku.get(sku_id, {}).get("forecast_daily", 0.0))

            sku_lanes = log_per_sku.get(sku_id, {}).get("lanes", [])
            rec_lane = next(
                (l for l in sku_lanes if l.get("role") == "recommended"),
                sku_lanes[0] if sku_lanes else {},
            )
            eta_days = int(rec_lane.get("selected", {}).get("total_lead_time_days", 30))

            # Net requirement calculation
            leftover_at_arrival = max(0.0, on_hand - forecast_daily * eta_days)
            raw_net = forecast_daily * coverage_days + total_safety_stock - leftover_at_arrival
            raw_net = max(0.0, raw_net)
            net_requirement = int(math.ceil(raw_net / ORDER_MULTIPLE) * ORDER_MULTIPLE)

            # Sourcing candidates: recommended before backup
            sup_info = per_sku_supplier[sku_id]
            candidates: list[tuple[str, dict[str, Any]]] = []
            if sup_info.get("recommended"):
                candidates.append(("recommended", sup_info["recommended"]))
            if sup_info.get("backup"):
                candidates.append(("backup", sup_info["backup"]))

            remaining_req = net_requirement
            sku_ordered_qty = 0

            for role, cand in candidates:
                sup_id = cand["supplier_id"]
                unit_price = float(cand.get("unit_price", 0.0))
                monthly_cap = float(cand.get("monthly_capacity", 0))

                effective_cap = monthly_cap * (coverage_days / 30.0)
                supplier_max_cap = int(
                    math.floor(effective_cap / ORDER_MULTIPLE) * ORDER_MULTIPLE
                )

                alloc_qty = min(remaining_req, supplier_max_cap)
                if alloc_qty > 0:
                    # Find logistics lane for this supplier
                    lane = next(
                        (l for l in sku_lanes if l.get("role") == role or l.get("supplier_id") == sup_id),
                        rec_lane,
                    )
                    sel_logistics = lane.get("selected", {})
                    freight_mode = sel_logistics.get("mode", "road")
                    frt_per_unit = float(sel_logistics.get("freight_per_unit", 0.0))
                    expected_arrival = sel_logistics.get("eta_date", "")

                    freight_cost = round(frt_per_unit * alloc_qty, 2)
                    line_cost = round(alloc_qty * unit_price + freight_cost, 2)

                    urgency = (
                        "urgent"
                        if (sku_id in critical_skus or sku_id in high_risk_skus)
                        else "standard"
                    )

                    baseline_p = baseline_prices.get(sku_id, unit_price)
                    prem_vs_base = round(alloc_qty * (unit_price - baseline_p), 2)

                    po_id = f"PO-{disruption_id}-{po_counter:03d}"
                    po_counter += 1

                    purchase_orders.append(
                        {
                            "po_id": po_id,
                            "supplier_id": sup_id,
                            "sku_id": sku_id,
                            "role": role,
                            "quantity": alloc_qty,
                            "unit_price": unit_price,
                            "freight_mode": freight_mode,
                            "freight_cost": freight_cost,
                            "line_cost": line_cost,
                            "expected_arrival": expected_arrival,
                            "urgency": urgency,
                            "baseline_unit_price": baseline_p,
                            "premium_vs_baseline": prem_vs_base,
                        }
                    )

                    remaining_req -= alloc_qty
                    sku_ordered_qty += alloc_qty

            unsourced_qty = max(0, net_requirement - sku_ordered_qty)
            coverage_pct = (
                round((sku_ordered_qty / net_requirement) * 100.0, 1)
                if net_requirement > 0
                else 100.0
            )

            per_sku_summary[sku_id] = {
                "net_requirement": net_requirement,
                "ordered_qty": sku_ordered_qty,
                "unsourced_qty": unsourced_qty,
                "coverage_pct": coverage_pct,
                "needs_additional_sourcing": unsourced_qty > 0,
            }

        po_count = len(purchase_orders)
        total_po_value = round(
            sum(po["quantity"] * po["unit_price"] for po in purchase_orders), 2
        )
        total_freight = round(
            sum(po["freight_cost"] for po in purchase_orders), 2
        )
        total_landed_cost = round(
            sum(po["line_cost"] for po in purchase_orders), 2
        )
        total_premium_vs_baseline = round(
            sum(po["premium_vs_baseline"] for po in purchase_orders), 2
        )

        unsourced_by_sku = {
            sku: d["unsourced_qty"]
            for sku, d in per_sku_summary.items()
            if d["unsourced_qty"] > 0
        }
        approval_required = bool(total_landed_cost > APPROVAL_THRESHOLD_USD)

        totals = {
            "po_count": po_count,
            "total_po_value": total_po_value,
            "total_freight": total_freight,
            "total_landed_cost": total_landed_cost,
            "total_premium_vs_baseline": total_premium_vs_baseline,
        }

        finish_time = datetime.datetime.now(datetime.timezone.utc)

        facts = {
            "disruption_id": disruption_id,
            "po_count": po_count,
            "total_landed_cost": total_landed_cost,
            "total_freight": total_freight,
            "total_premium_vs_baseline": total_premium_vs_baseline,
            "unsourced_skus_count": len(unsourced_by_sku),
            "approval_required": approval_required,
        }
        fallback_summary = (
            f"Procurement plan for {disruption_id}: Generated {po_count} PO lines with total landed cost "
            f"${total_landed_cost:,.2f} (freight: ${total_freight:,.2f}, premium: ${total_premium_vs_baseline:,.2f}). "
            f"Approval required: {approval_required}. Unsourced volume across {len(unsourced_by_sku)} SKUs."
        )
        summary = narrate(role="procurement", facts=facts, fallback=fallback_summary)

        return AgentResult(
            agent_name=self.name,
            status="ok",
            summary=summary,
            data={
                "purchase_orders": purchase_orders,
                "per_sku": per_sku_summary,
                "totals": totals,
                "unsourced_by_sku": unsourced_by_sku,
                "approval_required": approval_required,
            },
            started_at=start_time,
            finished_at=finish_time,
        )
