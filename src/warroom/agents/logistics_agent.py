"""Logistics Agent evaluating multi-modal shipping quotes, expedited routing, and lane selection."""

from __future__ import annotations

import datetime
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from warroom.agents.base import BaseAgent
from warroom.agents.llm import narrate
from warroom.db.models import Supplier, Warehouse
from warroom.graph.analysis import avg_daily_demand
from warroom.orchestrator.state import AgentResult, WarRoomState
from warroom.tools.logistics_api import SimulatedLogisticsAPI
from warroom.tools.registry import call_tool, set_logistics_api

LOGISTICS_WEIGHTS = {
    "cost": 0.60,
    "time": 0.40,
}


class LogisticsAgent(BaseAgent):
    """Deterministic logistics agent optimizing freight modes across supply disruption lanes."""

    def __init__(self, session: Session) -> None:
        super().__init__(name="logistics", result_key="logistics_result")
        self.session = session
        # Configure tool registry to use this session's API engine
        self.api = SimulatedLogisticsAPI(session)
        set_logistics_api(self.api)

    def run(self, state: WarRoomState) -> AgentResult:
        start_time = datetime.datetime.now(datetime.timezone.utc)
        disruption = state.get("disruption") or {}
        failed_supplier = disruption.get("supplier_id", "SUP01")
        disruption_id = disruption.get("event_id") or f"DISR-{failed_supplier}"

        supplier_res = state.get("supplier_result")
        inventory_res = state.get("inventory_result")

        # Extract data safely from supplier and inventory results
        if isinstance(supplier_res, AgentResult):
            supplier_status = supplier_res.status
            supplier_data = supplier_res.data
        elif isinstance(supplier_res, dict):
            supplier_status = supplier_res.get("status")
            supplier_data = supplier_res.get("data")
        else:
            supplier_status = None
            supplier_data = None

        if isinstance(inventory_res, AgentResult):
            inventory_status = inventory_res.status
            inventory_data = inventory_res.data
        elif isinstance(inventory_res, dict):
            inventory_status = inventory_res.get("status")
            inventory_data = inventory_res.get("data")
        else:
            inventory_status = None
            inventory_data = None

        if (
            not supplier_res
            or not inventory_res
            or supplier_status != "ok"
            or inventory_status != "ok"
            or not isinstance(supplier_data, dict)
            or not isinstance(inventory_data, dict)
        ):
            return AgentResult(
                agent_name=self.name,
                status="error",
                summary=(
                    f"Logistics evaluation for {disruption_id} failed: "
                    "supplier_result and inventory_result are both required."
                ),
                data={},
                started_at=start_time,
                finished_at=datetime.datetime.now(datetime.timezone.utc),
            )

        # 1. Query warehouses and calculate capacity distribution
        warehouses = self.session.scalars(
            select(Warehouse).order_by(Warehouse.warehouse_id)
        ).all()
        total_capacity = sum(w.capacity for w in warehouses)
        wh_splits = {
            w.warehouse_id: (w.capacity / total_capacity if total_capacity > 0 else 0.25)
            for w in warehouses
        }

        # 2. Query suppliers metadata for origin countries
        suppliers = self.session.scalars(select(Supplier)).all()
        supplier_countries = {s.supplier_id: s.country for s in suppliers}

        # 3. Query carriers via registry tool
        carriers_list = call_tool("list_carriers")
        carrier_names = {c["carrier_id"]: c["name"] for c in carriers_list}

        critical_skus_set = set(inventory_data.get("critical_skus", []))
        inv_per_sku = inventory_data.get("per_sku", {})
        expected_duration = int(disruption.get("expected_duration_days") or 30)
        today = datetime.date.today()

        per_sku_supplier = supplier_data.get("per_sku", {})
        per_sku_results: dict[str, Any] = {}

        total_freight_estimate = 0.0
        total_expedite_extra_cost = 0.0
        expedited_skus: list[str] = []
        mode_mix: dict[str, int] = {}

        for sku_id, sup_info in per_sku_supplier.items():
            # Check criticality (fill rate < 100%)
            sku_inv = inv_per_sku.get(sku_id, {})
            is_critical = (
                sku_id in critical_skus_set
                or float(sku_inv.get("fill_rate_pct", 100.0)) < 100.0
            )

            daily_demand = float(
                sku_inv.get("avg_daily_demand") or avg_daily_demand(self.session, sku_id)
            )
            reference_qty = max(1, int(round(daily_demand * expected_duration)))

            candidates: list[tuple[str, dict[str, Any]]] = []
            if sup_info.get("recommended"):
                candidates.append(("recommended", sup_info["recommended"]))
            if sup_info.get("backup"):
                candidates.append(("backup", sup_info["backup"]))

            sku_lanes: list[dict[str, Any]] = []

            for role, cand in candidates:
                sup_id = cand["supplier_id"]
                origin_country = supplier_countries.get(sup_id, "Other")
                ready_lead_time = int(cand.get("lead_time_days", 0))

                # Aggregate quotes across warehouses grouped by carrier/mode
                quotes_by_mode: dict[str, list[dict[str, Any]]] = {}
                qty_by_wh: dict[str, int] = {}

                for wh in warehouses:
                    split_frac = wh_splits.get(wh.warehouse_id, 0.25)
                    wh_qty = max(1, int(round(reference_qty * split_frac)))
                    qty_by_wh[wh.warehouse_id] = wh_qty

                    wh_quotes = call_tool(
                        "get_route_quotes",
                        origin_country=origin_country,
                        warehouse_id=wh.warehouse_id,
                        sku_id=sku_id,
                        quantity=wh_qty,
                    )

                    for q in wh_quotes:
                        m = q["mode"].lower()
                        quotes_by_mode.setdefault(m, []).append(q)

                # Aggregate mode options
                mode_options: list[dict[str, Any]] = []
                for m, q_list in quotes_by_mode.items():
                    m_freight_total = sum(q["freight_total"] for q in q_list)
                    m_freight_per_unit = (
                        round(m_freight_total / reference_qty, 2)
                        if reference_qty > 0
                        else 0.0
                    )
                    m_transit_days = max(q["transit_days"] for q in q_list)
                    m_on_time = q_list[0]["on_time_prob"]
                    m_total_lead_time = ready_lead_time + m_transit_days
                    cid = q_list[0]["carrier_id"]

                    mode_options.append(
                        {
                            "mode": m,
                            "carrier_id": cid,
                            "carrier_name": carrier_names.get(cid, cid),
                            "freight_total": round(m_freight_total, 2),
                            "freight_per_unit": m_freight_per_unit,
                            "transit_days": int(m_transit_days),
                            "on_time_prob": round(m_on_time, 2),
                            "total_lead_time_days": int(m_total_lead_time),
                        }
                    )

                if not mode_options:
                    continue

                # Mode selection logic
                if is_critical:
                    # Fastest total lead time, tie-broken by lowest cost
                    selected_opt = min(
                        mode_options,
                        key=lambda o: (o["total_lead_time_days"], o["freight_total"]),
                    )
                else:
                    # Min-max normalization: 0.6 cost + 0.4 time (cheaper/faster = higher)
                    costs = [o["freight_total"] for o in mode_options]
                    times = [o["total_lead_time_days"] for o in mode_options]
                    min_c, max_c = min(costs), max(costs)
                    min_t, max_t = min(times), max(times)

                    for opt in mode_options:
                        c_score = (
                            1.0
                            if max_c == min_c
                            else (max_c - opt["freight_total"]) / (max_c - min_c)
                        )
                        t_score = (
                            1.0
                            if max_t == min_t
                            else (max_t - opt["total_lead_time_days"]) / (max_t - min_t)
                        )
                        opt["score"] = round(
                            LOGISTICS_WEIGHTS["cost"] * c_score
                            + LOGISTICS_WEIGHTS["time"] * t_score,
                            4,
                        )

                    selected_opt = max(
                        mode_options,
                        key=lambda o: (
                            o.get("score", 0.0),
                            -o["freight_total"],
                            -o["total_lead_time_days"],
                        ),
                    )

                cheapest_opt = min(mode_options, key=lambda o: o["freight_total"])
                expedited = bool(selected_opt["freight_total"] > cheapest_opt["freight_total"])
                expedite_extra = round(
                    max(0.0, selected_opt["freight_total"] - cheapest_opt["freight_total"]),
                    2,
                )
                days_saved = max(
                    0,
                    cheapest_opt["total_lead_time_days"]
                    - selected_opt["total_lead_time_days"],
                )
                eta = (
                    today
                    + datetime.timedelta(days=selected_opt["total_lead_time_days"])
                ).isoformat()

                selected_info = {
                    "mode": selected_opt["mode"],
                    "carrier_id": selected_opt["carrier_id"],
                    "carrier_name": selected_opt["carrier_name"],
                    "freight_total": selected_opt["freight_total"],
                    "freight_per_unit": selected_opt["freight_per_unit"],
                    "transit_days": selected_opt["transit_days"],
                    "total_lead_time_days": selected_opt["total_lead_time_days"],
                    "on_time_prob": selected_opt["on_time_prob"],
                    "eta_date": eta,
                    "expedited": expedited,
                    "expedite_extra_cost": expedite_extra,
                    "days_saved_vs_cheapest": days_saved,
                }

                lane_record = {
                    "supplier_id": sup_id,
                    "role": role,
                    "options": mode_options,
                    "selected": selected_info,
                }
                sku_lanes.append(lane_record)

                if role == "recommended":
                    total_freight_estimate += selected_info["freight_total"]
                    total_expedite_extra_cost += selected_info["expedite_extra_cost"]
                    if expedited:
                        expedited_skus.append(sku_id)
                    sel_mode = selected_info["mode"]
                    mode_mix[sel_mode] = mode_mix.get(sel_mode, 0) + 1

            per_sku_results[sku_id] = {
                "lanes": sku_lanes,
                "is_critical": is_critical,
                "reference_qty": reference_qty,
            }

        active_delays = call_tool("get_active_delays")
        finish_time = datetime.datetime.now(datetime.timezone.utc)

        totals = {
            "total_freight_estimate": round(total_freight_estimate, 2),
            "total_expedite_extra_cost": round(total_expedite_extra_cost, 2),
            "expedited_skus": expedited_skus,
            "mode_mix": mode_mix,
            "active_delays": active_delays,
        }

        facts = {
            "disruption_id": disruption_id,
            "affected_skus_count": len(per_sku_results),
            "total_freight_estimate": round(total_freight_estimate, 2),
            "total_expedite_extra_cost": round(total_expedite_extra_cost, 2),
            "expedited_skus_count": len(expedited_skus),
            "mode_mix": mode_mix,
        }
        fallback_summary = (
            f"Logistics route plan for {disruption_id}: Evaluated multi-modal lanes for "
            f"{len(per_sku_results)} SKUs. Total estimated freight is ${total_freight_estimate:,.2f} "
            f"({len(expedited_skus)} expedited lanes with ${total_expedite_extra_cost:,.2f} extra cost; "
            f"mode mix: {mode_mix})."
        )
        summary = narrate(role="logistics", facts=facts, fallback=fallback_summary)

        return AgentResult(
            agent_name=self.name,
            status="ok",
            summary=summary,
            data={
                "disruption_id": disruption_id,
                "per_sku": per_sku_results,
                "totals": totals,
            },
            started_at=start_time,
            finished_at=finish_time,
        )
