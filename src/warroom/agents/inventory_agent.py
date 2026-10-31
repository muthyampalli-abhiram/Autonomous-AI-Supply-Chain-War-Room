"""Inventory Agent allocating warehouse on-hand stock against at-risk orders."""

from __future__ import annotations

import datetime
from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from warroom.agents.base import BaseAgent
from warroom.agents.llm import narrate
from warroom.db.models import Inventory, Order
from warroom.graph.analysis import avg_daily_demand
from warroom.orchestrator.state import AgentResult, WarRoomState


class InventoryAgent(BaseAgent):
    """Deterministic agent evaluating inventory stock and allocating on-hand stock to at-risk orders."""

    def __init__(self, session: Session) -> None:
        super().__init__(name="inventory", result_key="inventory_result")
        self.session = session

    def run(self, state: WarRoomState) -> AgentResult:
        start_time = datetime.datetime.now(datetime.timezone.utc)
        disruption = state.get("disruption") or {}
        failed_supplier = disruption.get("supplier_id", "SUP01")
        disruption_id = disruption.get("event_id") or f"DISR-{failed_supplier}"

        supplier_res = state.get("supplier_result")
        if isinstance(supplier_res, AgentResult):
            status_val = supplier_res.status
            supplier_data = supplier_res.data
        elif isinstance(supplier_res, dict):
            status_val = supplier_res.get("status")
            supplier_data = supplier_res.get("data")
        else:
            status_val = None
            supplier_data = None

        if not supplier_res or status_val != "ok" or not isinstance(supplier_data, dict):
            return AgentResult(
                agent_name=self.name,
                status="error",
                summary=f"Inventory evaluation for {disruption_id} failed: supplier_result is missing or invalid.",
                data={},
                started_at=start_time,
                finished_at=datetime.datetime.now(datetime.timezone.utc),
            )

        per_sku_supplier: dict[str, Any] = supplier_data.get("per_sku", {})
        affected_skus: list[str] = (
            list(per_sku_supplier.keys())
            if per_sku_supplier
            else (state.get("impact") or {}).get("affected_skus", [])
        )

        today = datetime.date.today()
        per_sku_results: dict[str, Any] = {}
        shortfall_by_customer: dict[str, int] = {}

        for sku_id in affected_skus:
            # 1. Warehouse inventory
            inv_records = self.session.scalars(
                select(Inventory).where(Inventory.sku_id == sku_id)
            ).all()
            stock_by_warehouse = {inv.warehouse_id: inv.on_hand for inv in inv_records}
            total_on_hand = sum(inv.on_hand for inv in inv_records)
            total_safety_stock = sum(inv.safety_stock for inv in inv_records)

            daily_demand = avg_daily_demand(self.session, sku_id)
            days_of_cover = (
                round(total_on_hand / daily_demand, 2) if daily_demand > 0 else 999.0
            )

            # 2. Recommended replenishment lead time & window
            rec = per_sku_supplier.get(sku_id, {}).get("recommended")
            replenishment_lead_time = (
                int(rec["lead_time_days"]) if rec and "lead_time_days" in rec else 0
            )
            window_end = today + datetime.timedelta(days=replenishment_lead_time)

            # 3. Open orders due within window (including overdue)
            orders = self.session.scalars(
                select(Order).where(
                    Order.sku_id == sku_id,
                    func.lower(Order.status) == "open",
                    Order.due_date <= window_end,
                )
            ).all()

            # Sort by priority DESC, then due_date ASC, then order_id ASC
            sorted_orders = sorted(
                orders,
                key=lambda o: (-o.priority, o.due_date, o.order_id),
            )

            # 4. Greedy on-hand allocation
            remaining_stock = total_on_hand
            allocations: list[dict[str, Any]] = []
            total_allocated_sku = 0
            total_short_sku = 0

            for order in sorted_orders:
                qty = order.quantity
                allocated = min(qty, remaining_stock)
                short = qty - allocated
                remaining_stock -= allocated
                total_allocated_sku += allocated
                total_short_sku += short

                due_date_str = (
                    order.due_date.isoformat()
                    if hasattr(order.due_date, "isoformat")
                    else str(order.due_date)
                )

                allocations.append(
                    {
                        "order_id": order.order_id,
                        "customer_id": order.customer_id,
                        "priority": order.priority,
                        "due_date": due_date_str,
                        "quantity": qty,
                        "allocated_qty": allocated,
                        "short_qty": short,
                    }
                )

                if short > 0:
                    cid = order.customer_id
                    shortfall_by_customer[cid] = (
                        shortfall_by_customer.get(cid, 0) + short
                    )

            window_demand = sum(o.quantity for o in sorted_orders)
            projected_demand = round(daily_demand * replenishment_lead_time, 2)
            fill_rate_pct = (
                round((total_allocated_sku / window_demand) * 100.0, 2)
                if window_demand > 0
                else 100.0
            )
            safety_stock_breached = (total_on_hand - total_allocated_sku) < total_safety_stock
            stockout_day_estimate = int(round(days_of_cover))

            per_sku_results[sku_id] = {
                "stock_by_warehouse": stock_by_warehouse,
                "on_hand": total_on_hand,
                "safety_stock": total_safety_stock,
                "avg_daily_demand": round(daily_demand, 2),
                "days_of_cover": round(days_of_cover, 2),
                "replenishment_lead_time": replenishment_lead_time,
                "window_demand": window_demand,
                "projected_demand": projected_demand,
                "allocated_qty": total_allocated_sku,
                "shortfall_qty": total_short_sku,
                "fill_rate_pct": fill_rate_pct,
                "safety_stock_breached": safety_stock_breached,
                "stockout_day_estimate": stockout_day_estimate,
                "allocations": allocations,
            }

        # 5. Overall aggregation
        window_demand_total = sum(s["window_demand"] for s in per_sku_results.values())
        allocated_total = sum(s["allocated_qty"] for s in per_sku_results.values())
        shortfall_total = sum(s["shortfall_qty"] for s in per_sku_results.values())
        overall_fill_rate_pct = (
            round((allocated_total / window_demand_total) * 100.0, 2)
            if window_demand_total > 0
            else 100.0
        )

        critical_skus = [
            sku_id
            for sku_id, data in per_sku_results.items()
            if data["fill_rate_pct"] < 100.0
        ]
        critical_skus.sort(
            key=lambda s: per_sku_results[s]["shortfall_qty"], reverse=True
        )

        totals = {
            "window_demand": window_demand_total,
            "allocated": allocated_total,
            "shortfall": shortfall_total,
            "overall_fill_rate_pct": overall_fill_rate_pct,
        }

        finish_time = datetime.datetime.now(datetime.timezone.utc)

        facts = {
            "disruption_id": disruption_id,
            "affected_skus_count": len(per_sku_results),
            "critical_skus_count": len(critical_skus),
            "critical_skus": critical_skus,
            "window_demand": window_demand_total,
            "allocated": allocated_total,
            "shortfall": shortfall_total,
            "overall_fill_rate_pct": overall_fill_rate_pct,
            "shortfall_by_customer_count": len(shortfall_by_customer),
        }
        fallback_summary = (
            f"Inventory assessment for {disruption_id}: Analyzed stock across {len(per_sku_results)} affected SKUs. "
            f"Overall fill rate is {overall_fill_rate_pct:.1f}% with {shortfall_total:,} units shortfall across {len(critical_skus)} critical SKUs."
        )
        summary = narrate(role="inventory", facts=facts, fallback=fallback_summary)

        return AgentResult(
            agent_name=self.name,
            status="ok",
            summary=summary,
            data={
                "disruption_id": disruption_id,
                "per_sku": per_sku_results,
                "shortfall_by_customer": shortfall_by_customer,
                "totals": totals,
                "critical_skus": critical_skus,
            },
            started_at=start_time,
            finished_at=finish_time,
        )
