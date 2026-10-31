"""Customer Impact Agent calculating order recoveries, SLA penalties, and customer exposure."""

from __future__ import annotations

import datetime
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from warroom.agents.base import BaseAgent
from warroom.agents.llm import narrate
from warroom.db.models import Customer, SKU
from warroom.orchestrator.state import AgentResult, WarRoomState

PENALTY_PCT_PER_DAY: dict[str, float] = {
    "gold": 0.02,
    "silver": 0.01,
    "bronze": 0.005,
}
PENALTY_CAP: float = 0.20

RISK_RANK: dict[str, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}


def _parse_date(d: Any) -> datetime.date | None:
    if d is None:
        return None
    if isinstance(d, datetime.date):
        return d
    return datetime.date.fromisoformat(str(d)[:10])


class CustomerImpactAgent(BaseAgent):
    """Deterministic customer impact agent evaluating service levels and revenue protection."""

    def __init__(self, session: Session) -> None:
        super().__init__(name="customer_impact", result_key="customer_impact_result")
        self.session = session

    def run(self, state: WarRoomState) -> AgentResult:
        start_time = datetime.datetime.now(datetime.timezone.utc)
        disruption = state.get("disruption") or {}
        failed_supplier = disruption.get("supplier_id", "SUP01")
        disruption_id = disruption.get("event_id") or f"DISR-{failed_supplier}"

        inv_res = state.get("inventory_result")
        log_res = state.get("logistics_result")
        dem_res = state.get("demand_result")
        proc_res = state.get("procurement_result")

        def _get_status_data(res: Any) -> tuple[str | None, dict[str, Any] | None]:
            if isinstance(res, AgentResult):
                return res.status, res.data
            if isinstance(res, dict):
                return res.get("status"), res.get("data")
            return None, None

        i_status, i_data = _get_status_data(inv_res)
        l_status, l_data = _get_status_data(log_res)
        d_status, d_data = _get_status_data(dem_res)
        p_status, p_data = _get_status_data(proc_res)

        if (
            i_status != "ok"
            or l_status != "ok"
            or d_status != "ok"
            or p_status != "ok"
            or not isinstance(i_data, dict)
            or not isinstance(l_data, dict)
            or not isinstance(d_data, dict)
            or not isinstance(p_data, dict)
        ):
            return AgentResult(
                agent_name=self.name,
                status="error",
                summary=(
                    f"Customer impact assessment for {disruption_id} failed: "
                    "inventory_result, logistics_result, demand_result, and procurement_result are all required."
                ),
                data={},
                started_at=start_time,
                finished_at=datetime.datetime.now(datetime.timezone.utc),
            )

        # 1. Metadata lookups
        sku_prices: dict[str, float] = {
            s.sku_id: float(s.unit_price)
            for s in self.session.scalars(select(SKU)).all()
        }
        customers: dict[str, dict[str, str]] = {
            c.customer_id: {"name": c.name, "tier": c.tier.lower()}
            for c in self.session.scalars(select(Customer)).all()
        }

        inv_per_sku = i_data.get("per_sku", {})
        proc_per_sku = p_data.get("per_sku", {})
        proc_pos = p_data.get("purchase_orders", [])
        dem_per_sku = d_data.get("per_sku", {})

        per_order: list[dict[str, Any]] = []
        total_window_allocations = 0

        # 2. Per-order allocation recovery logic
        for sku_id, inv_info in inv_per_sku.items():
            allocations = inv_info.get("allocations", [])
            total_window_allocations += len(allocations)

            short_orders = [a for a in allocations if a.get("short_qty", 0) > 0]
            supply_pool = int(proc_per_sku.get(sku_id, {}).get("ordered_qty", 0))

            sku_pos = [p for p in proc_pos if p.get("sku_id") == sku_id]
            arrival_dates = [
                _parse_date(p.get("expected_arrival"))
                for p in sku_pos
                if p.get("expected_arrival")
            ]
            valid_dates = [d for d in arrival_dates if d is not None]
            fulfilment_date = min(valid_dates) if valid_dates else None

            for order in short_orders:
                short_qty = int(order.get("short_qty", 0))
                recovered_qty = min(short_qty, supply_pool)
                supply_pool -= recovered_qty
                unrecovered_qty = short_qty - recovered_qty

                due_d = _parse_date(order.get("due_date"))
                if recovered_qty > 0 and fulfilment_date and due_d:
                    delay_days: int | None = max(0, (fulfilment_date - due_d).days)
                else:
                    delay_days = None

                unit_price = sku_prices.get(sku_id, 0.0)
                delayed_value = (
                    round(recovered_qty * unit_price, 2)
                    if (delay_days is not None and delay_days > 0)
                    else 0.0
                )
                lost_value = round(unrecovered_qty * unit_price, 2)

                cust_id = str(order.get("customer_id", ""))
                cust_meta = customers.get(cust_id, {"tier": "bronze"})
                tier = cust_meta.get("tier", "bronze").lower()

                if delay_days is not None and delayed_value > 0:
                    pct_daily = PENALTY_PCT_PER_DAY.get(tier, 0.005)
                    pen_rate = min(PENALTY_CAP, pct_daily * delay_days)
                    delay_penalty = delayed_value * pen_rate
                else:
                    delay_penalty = 0.0

                lost_penalty = lost_value * PENALTY_CAP
                sla_penalty = round(delay_penalty + lost_penalty, 2)
                # Guarantee upper bound: sla_penalty <= PENALTY_CAP * (delayed_value + lost_value)
                max_penalty = round(PENALTY_CAP * (delayed_value + lost_value), 2)
                if sla_penalty > max_penalty:
                    sla_penalty = max_penalty

                due_str = (
                    order.get("due_date")
                    if isinstance(order.get("due_date"), str)
                    else (due_d.isoformat() if due_d else "")
                )

                per_order.append(
                    {
                        "order_id": order.get("order_id"),
                        "customer_id": cust_id,
                        "tier": tier,
                        "sku_id": sku_id,
                        "priority": int(order.get("priority", 1)),
                        "due_date": due_str,
                        "short_qty": short_qty,
                        "recovered_qty": recovered_qty,
                        "unrecovered_qty": unrecovered_qty,
                        "fulfilment_date": (
                            fulfilment_date.isoformat() if fulfilment_date else None
                        ),
                        "delay_days": delay_days,
                        "unit_price": unit_price,
                        "delayed_value": delayed_value,
                        "lost_value": lost_value,
                        "sla_penalty": sla_penalty,
                    }
                )

        # 3. Customer-level aggregation
        per_customer: dict[str, dict[str, Any]] = {}
        orders_by_cust: dict[str, list[dict[str, Any]]] = {}
        for row in per_order:
            orders_by_cust.setdefault(row["customer_id"], []).append(row)

        for cust_id, o_list in orders_by_cust.items():
            c_meta = customers.get(cust_id, {"name": cust_id, "tier": "bronze"})
            c_name = c_meta.get("name", cust_id)
            c_tier = c_meta.get("tier", "bronze").lower()

            c_orders_affected = len(o_list)
            c_short_qty = sum(o["short_qty"] for o in o_list)
            c_delayed_val = round(sum(o["delayed_value"] for o in o_list), 2)
            c_lost_val = round(sum(o["lost_value"] for o in o_list), 2)
            c_delays = [o["delay_days"] for o in o_list if o["delay_days"] is not None]
            c_max_delay = max(c_delays) if c_delays else 0
            c_sla_pen = round(sum(o["sla_penalty"] for o in o_list), 2)

            is_gold = (c_tier == "gold")
            has_lost_or_long = (c_lost_val > 0 or c_max_delay >= 14)

            if is_gold and has_lost_or_long:
                risk_level = "critical"
            elif has_lost_or_long:
                risk_level = "high"
            elif c_max_delay > 0:
                risk_level = "medium"
            else:
                risk_level = "low"

            per_customer[cust_id] = {
                "name": c_name,
                "tier": c_tier,
                "orders_affected": c_orders_affected,
                "short_qty": c_short_qty,
                "delayed_value": c_delayed_val,
                "lost_value": c_lost_val,
                "max_delay_days": c_max_delay,
                "sla_penalty": c_sla_pen,
                "risk_level": risk_level,
            }

        # 4. Forecast exposure calculation
        unsourced_by_sku = p_data.get("unsourced_by_sku", {})
        per_sku_exposure: dict[str, dict[str, Any]] = {}
        by_tier_exposure = {"gold": 0.0, "silver": 0.0, "bronze": 0.0}

        for s_id, u_qty in unsourced_by_sku.items():
            sell_p = sku_prices.get(s_id, 0.0)
            exp_val = round(u_qty * sell_p, 2)
            per_sku_exposure[s_id] = {
                "unsourced_qty": u_qty,
                "exposure_value": exp_val,
            }

            t_mix = dem_per_sku.get(s_id, {}).get("tier_mix_pct", {})
            for t in ["gold", "silver", "bronze"]:
                fraction = float(t_mix.get(t, 0.0)) / 100.0
                by_tier_exposure[t] = round(by_tier_exposure[t] + exp_val * fraction, 2)

        total_exposure = round(sum(d["exposure_value"] for d in per_sku_exposure.values()), 2)
        forecast_exposure = {
            "per_sku": per_sku_exposure,
            "total": total_exposure,
            "by_tier": by_tier_exposure,
        }

        # 5. Financial totals
        orders_at_risk = len(per_order)
        orders_delayed = sum(1 for o in per_order if o["delay_days"] is not None and o["delay_days"] > 0)
        orders_unfulfilled = sum(1 for o in per_order if o["unrecovered_qty"] > 0)

        revenue_delayed = round(sum(o["delayed_value"] for o in per_order), 2)
        revenue_lost = round(sum(o["lost_value"] for o in per_order), 2)
        sla_penalty_total = round(sum(o["sla_penalty"] for o in per_order), 2)

        proc_prem = float(p_data.get("totals", {}).get("total_premium_vs_baseline", 0.0))
        log_expedite = float(l_data.get("totals", {}).get("total_expedite_extra_cost", 0.0))
        response_cost = round(proc_prem + log_expedite, 2)
        net_financial_exposure = round(revenue_lost + sla_penalty_total + response_cost, 2)

        financials = {
            "orders_at_risk": orders_at_risk,
            "orders_delayed": orders_delayed,
            "orders_unfulfilled": orders_unfulfilled,
            "revenue_delayed": revenue_delayed,
            "revenue_lost": revenue_lost,
            "sla_penalty_total": sla_penalty_total,
            "response_cost": response_cost,
            "net_financial_exposure": net_financial_exposure,
        }

        # 6. Service metrics
        overall_fill_rate = float(i_data.get("totals", {}).get("overall_fill_rate_pct", 100.0))
        on_time_orders = max(0, total_window_allocations - orders_delayed - orders_unfulfilled)
        on_time_rate = (
            round((on_time_orders / total_window_allocations) * 100.0, 1)
            if total_window_allocations > 0
            else 100.0
        )
        service = {
            "overall_fill_rate_pct": overall_fill_rate,
            "on_time_rate_pct": on_time_rate,
        }

        # 7. Plan effect
        baseline_lost_value = round(sum(o["short_qty"] * o["unit_price"] for o in per_order), 2)
        plan_lost_value = revenue_lost
        value_protected = round(baseline_lost_value - plan_lost_value, 2)
        plan_effect = {
            "baseline_lost_value": baseline_lost_value,
            "plan_lost_value": plan_lost_value,
            "value_protected": value_protected,
        }

        # 8. Overall risk and top customers
        overall_risk = "low"
        if per_customer:
            overall_risk = max(
                (c["risk_level"] for c in per_customer.values()),
                key=lambda r: RISK_RANK.get(r, 0),
            )

        sorted_custs = sorted(
            per_customer.items(),
            key=lambda x: (x[1]["sla_penalty"] + x[1]["lost_value"]),
            reverse=True,
        )
        top_customers_at_risk = [c[0] for c in sorted_custs[:3]]

        finish_time = datetime.datetime.now(datetime.timezone.utc)

        facts = {
            "disruption_id": disruption_id,
            "orders_at_risk": orders_at_risk,
            "revenue_delayed": revenue_delayed,
            "revenue_lost": revenue_lost,
            "sla_penalty_total": sla_penalty_total,
            "value_protected": value_protected,
            "overall_risk": overall_risk,
            "top_customers_at_risk": top_customers_at_risk,
        }
        fallback_summary = (
            f"Customer impact assessment for {disruption_id}: Evaluated {orders_at_risk} at-risk orders. "
            f"Value protected: ${value_protected:,.2f}; delayed revenue: ${revenue_delayed:,.2f}; "
            f"SLA penalties: ${sla_penalty_total:,.2f}. Overall customer risk: {overall_risk.upper()}."
        )
        summary = narrate(role="customer_impact", facts=facts, fallback=fallback_summary)

        return AgentResult(
            agent_name=self.name,
            status="ok",
            summary=summary,
            data={
                "per_order": per_order,
                "per_customer": per_customer,
                "forecast_exposure": forecast_exposure,
                "financials": financials,
                "service": service,
                "plan_effect": plan_effect,
                "overall_risk": overall_risk,
                "top_customers_at_risk": top_customers_at_risk,
            },
            started_at=start_time,
            finished_at=finish_time,
        )
