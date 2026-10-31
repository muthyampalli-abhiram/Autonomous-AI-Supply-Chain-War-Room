"""Demand Agent forecasting demand shift, disruption uplift, and stockout risk."""

from __future__ import annotations

import datetime
from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from warroom.agents.base import BaseAgent
from warroom.agents.llm import narrate
from warroom.db.models import Customer, Order
from warroom.graph.analysis import avg_daily_demand
from warroom.orchestrator.state import AgentResult, WarRoomState

TREND_CLAMP: tuple[float, float] = (0.8, 1.5)
RECENT_WINDOW_DAYS: int = 14
DISRUPTION_UPLIFT: dict[str, float] = {
    "low": 0.0,
    "medium": 0.05,
    "high": 0.10,
    "critical": 0.15,
}


class DemandAgent(BaseAgent):
    """Deterministic demand forecasting agent calculating uplift and stockout horizons."""

    def __init__(self, session: Session) -> None:
        super().__init__(name="demand", result_key="demand_result")
        self.session = session

    def run(self, state: WarRoomState) -> AgentResult:
        start_time = datetime.datetime.now(datetime.timezone.utc)
        disruption = state.get("disruption") or {}
        failed_supplier = disruption.get("supplier_id", "SUP01")
        disruption_id = disruption.get("event_id") or f"DISR-{failed_supplier}"

        supplier_res = state.get("supplier_result")
        inventory_res = state.get("inventory_result")
        logistics_res = state.get("logistics_result")

        # Validate upstream results
        def _get_status_data(res: Any) -> tuple[str | None, dict[str, Any] | None]:
            if isinstance(res, AgentResult):
                return res.status, res.data
            if isinstance(res, dict):
                return res.get("status"), res.get("data")
            return None, None

        s_status, s_data = _get_status_data(supplier_res)
        i_status, i_data = _get_status_data(inventory_res)
        l_status, l_data = _get_status_data(logistics_res)

        if (
            s_status != "ok"
            or i_status != "ok"
            or l_status != "ok"
            or not isinstance(s_data, dict)
            or not isinstance(i_data, dict)
            or not isinstance(l_data, dict)
        ):
            return AgentResult(
                agent_name=self.name,
                status="error",
                summary=(
                    f"Demand forecasting for {disruption_id} failed: "
                    "supplier_result, inventory_result, and logistics_result are all required."
                ),
                data={},
                started_at=start_time,
                finished_at=datetime.datetime.now(datetime.timezone.utc),
            )

        # Disruption severity uplift
        severity = str(disruption.get("severity", "medium")).lower()
        uplift = DISRUPTION_UPLIFT.get(severity, 0.05)

        # Max order date across all orders
        max_order_date = self.session.scalar(select(func.max(Order.order_date)))
        if max_order_date is None:
            max_order_date = datetime.date.today()
        recent_cutoff = max_order_date - datetime.timedelta(days=RECENT_WINDOW_DAYS)

        per_sku_supplier = s_data.get("per_sku", {})
        inv_per_sku = i_data.get("per_sku", {})
        log_per_sku = l_data.get("per_sku", {})

        per_sku_results: dict[str, Any] = {}

        for sku_id in per_sku_supplier.keys():
            # 1. Baseline daily demand
            baseline_daily = avg_daily_demand(self.session, sku_id)

            # 2. Recent daily demand in the last 14 days up to reference_date
            recent_qty = (
                self.session.scalar(
                    select(func.sum(Order.quantity)).where(
                        Order.sku_id == sku_id,
                        Order.order_date > recent_cutoff,
                        Order.order_date <= max_order_date,
                    )
                )
                or 0
            )
            recent_daily = float(recent_qty) / float(RECENT_WINDOW_DAYS)

            # 3. Trend factor and uplift
            raw_trend = (
                (recent_daily / baseline_daily) if baseline_daily > 0 else 1.0
            )
            trend_factor = min(TREND_CLAMP[1], max(TREND_CLAMP[0], raw_trend))
            forecast_daily = baseline_daily * trend_factor * (1.0 + uplift)

            # 4. Replenishment horizon from logistics recommended lane
            sku_lanes = log_per_sku.get(sku_id, {}).get("lanes", [])
            rec_lane = next(
                (l for l in sku_lanes if l.get("role") == "recommended"),
                sku_lanes[0] if sku_lanes else {},
            )
            horizon_days = int(
                rec_lane.get("selected", {}).get("total_lead_time_days", 30)
            )

            # 5. Inventory and gap
            on_hand = int(inv_per_sku.get(sku_id, {}).get("on_hand", 0))
            forecast_demand = forecast_daily * horizon_days
            projected_gap_qty = max(0.0, forecast_demand - on_hand)
            stockout_day_forecast = (
                round(on_hand / forecast_daily, 1) if forecast_daily > 0 else 999.0
            )
            days_uncovered = max(0.0, round(horizon_days - stockout_day_forecast, 1))
            demand_shift_pct = (
                round(((forecast_daily / baseline_daily) - 1.0) * 100.0, 1)
                if baseline_daily > 0
                else 0.0
            )

            # 6. Customer tier mix (summing to 100.0)
            tier_rows = self.session.execute(
                select(Customer.tier, func.sum(Order.quantity))
                .join(Customer, Order.customer_id == Customer.customer_id)
                .where(Order.sku_id == sku_id)
                .group_by(Customer.tier)
            ).all()

            tier_quantities: dict[str, int] = {
                str(r[0]).lower(): int(r[1]) for r in tier_rows
            }
            total_tier_qty = sum(tier_quantities.values())

            tier_mix_pct: dict[str, float] = {}
            if total_tier_qty > 0:
                for t in ["gold", "silver", "bronze"]:
                    tier_mix_pct[t] = round(
                        (tier_quantities.get(t, 0) / total_tier_qty) * 100.0, 1
                    )
                # Adjust rounding difference to guarantee sum == 100.0
                diff = round(100.0 - sum(tier_mix_pct.values()), 1)
                if diff != 0.0:
                    largest_tier = max(tier_mix_pct, key=tier_mix_pct.get)
                    tier_mix_pct[largest_tier] = round(
                        tier_mix_pct[largest_tier] + diff, 1
                    )
            else:
                tier_mix_pct = {"gold": 0.0, "silver": 0.0, "bronze": 0.0}

            per_sku_results[sku_id] = {
                "baseline_daily": round(baseline_daily, 2),
                "recent_daily": round(recent_daily, 2),
                "trend_factor": round(trend_factor, 2),
                "uplift_pct": round(uplift * 100.0, 1),
                "forecast_daily": round(forecast_daily, 2),
                "horizon_days": horizon_days,
                "forecast_demand": round(forecast_demand, 1),
                "on_hand": on_hand,
                "projected_gap_qty": round(projected_gap_qty, 1),
                "stockout_day_forecast": stockout_day_forecast,
                "days_uncovered": days_uncovered,
                "demand_shift_pct": demand_shift_pct,
                "tier_mix_pct": tier_mix_pct,
            }

        # Overall totals and high-risk SKUs
        total_forecast_demand = round(
            sum(d["forecast_demand"] for d in per_sku_results.values()), 1
        )
        total_projected_gap = round(
            sum(d["projected_gap_qty"] for d in per_sku_results.values()), 1
        )

        high_risk_skus = [
            sku_id
            for sku_id, data in per_sku_results.items()
            if data["days_uncovered"] > 0
        ]
        high_risk_skus.sort(
            key=lambda s: per_sku_results[s]["days_uncovered"], reverse=True
        )

        totals = {
            "forecast_demand": total_forecast_demand,
            "projected_gap_qty": total_projected_gap,
        }

        finish_time = datetime.datetime.now(datetime.timezone.utc)

        facts = {
            "disruption_id": disruption_id,
            "affected_skus_count": len(per_sku_results),
            "high_risk_skus_count": len(high_risk_skus),
            "high_risk_skus": high_risk_skus,
            "total_forecast_demand": total_forecast_demand,
            "total_projected_gap": total_projected_gap,
        }
        fallback_summary = (
            f"Demand forecast for {disruption_id}: Analyzed {len(per_sku_results)} SKUs with "
            f"{uplift * 100.0:.0f}% disruption uplift. Projected demand: {total_forecast_demand:,.0f} units "
            f"with {total_projected_gap:,.0f} units gap across {len(high_risk_skus)} high-risk SKUs "
            f"({high_risk_skus})."
        )
        summary = narrate(role="demand", facts=facts, fallback=fallback_summary)

        return AgentResult(
            agent_name=self.name,
            status="ok",
            summary=summary,
            data={
                "disruption_id": disruption_id,
                "per_sku": per_sku_results,
                "totals": totals,
                "high_risk_skus": high_risk_skus,
            },
            started_at=start_time,
            finished_at=finish_time,
        )
