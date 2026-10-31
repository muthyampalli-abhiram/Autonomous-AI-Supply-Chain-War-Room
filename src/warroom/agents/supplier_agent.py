"""Supplier Agent evaluating alternative vendors, multi-criteria scoring, and capacity splits."""

from __future__ import annotations

import datetime
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from warroom.agents.base import BaseAgent
from warroom.agents.llm import narrate
from warroom.db.models import Supplier, SupplierSKU
from warroom.graph.analysis import avg_daily_demand
from warroom.orchestrator.state import AgentResult, WarRoomState

SCORING_WEIGHTS = {
    "price": 0.35,
    "lead_time": 0.30,
    "reliability": 0.20,
    "capacity": 0.15,
}


def _norm_higher_better(val: float, min_v: float, max_v: float) -> float:
    """Normalize a value where higher is better. Tie scores 1.0."""
    if max_v == min_v:
        return 1.0
    return (val - min_v) / (max_v - min_v)


def _norm_lower_better(val: float, min_v: float, max_v: float) -> float:
    """Normalize a value where lower is better (inverted). Tie scores 1.0."""
    if max_v == min_v:
        return 1.0
    return (max_v - val) / (max_v - min_v)


class SupplierAgent(BaseAgent):
    """Deterministic agent evaluating and ranking alternative suppliers for disrupted SKUs."""

    def __init__(self, session: Session) -> None:
        super().__init__(name="supplier", result_key="supplier_result")
        self.session = session

    def run(self, state: WarRoomState) -> AgentResult:
        start_time = datetime.datetime.now(datetime.timezone.utc)
        disruption = state.get("disruption") or {}
        failed_supplier = disruption.get("supplier_id", "SUP01")
        disruption_id = disruption.get("event_id") or f"DISR-{failed_supplier}"

        impact = state.get("impact") or {}
        affected_skus: list[str] = impact.get("affected_skus", [])
        alternatives_map: dict[str, list[dict[str, Any]]] = impact.get("alternatives", {})

        # Query database for missing vendor metadata
        suppliers = self.session.scalars(select(Supplier)).all()
        supplier_metadata = {
            s.supplier_id: {"name": s.name, "reliability": s.reliability_score}
            for s in suppliers
        }

        # Query baseline prices of failed supplier
        failed_sku_prices: dict[str, float] = {}
        failed_links = self.session.scalars(
            select(SupplierSKU).where(SupplierSKU.supplier_id == failed_supplier)
        ).all()
        for link in failed_links:
            failed_sku_prices[link.sku_id] = link.unit_price

        per_sku_results: dict[str, Any] = {}
        skus_needing_split: list[str] = []
        total_price_premium_estimate = 0.0

        for sku_id in affected_skus:
            failed_price = failed_sku_prices.get(sku_id, 0.0)
            daily_demand = avg_daily_demand(self.session, sku_id)
            monthly_demand = daily_demand * 30.0

            raw_alts = alternatives_map.get(sku_id, [])
            # Filter out any accidental reference to the failed supplier
            candidate_alts = [
                a for a in raw_alts if a.get("supplier_id") != failed_supplier
            ]

            if not candidate_alts:
                per_sku_results[sku_id] = {
                    "ranked_alternatives": [],
                    "recommended": None,
                    "backup": None,
                    "single_supplier_can_cover": False,
                }
                skus_needing_split.append(sku_id)
                continue

            # Gather metrics across candidates for normalization
            prices = [float(a.get("unit_price", 0.0)) for a in candidate_alts]
            leads = [float(a.get("lead_time_days", 0.0)) for a in candidate_alts]
            reliabilities = [
                float(supplier_metadata.get(a.get("supplier_id"), {}).get("reliability", 0.90))
                for a in candidate_alts
            ]
            capacities = [float(a.get("monthly_capacity", 0.0)) for a in candidate_alts]

            min_p, max_p = min(prices), max(prices)
            min_l, max_l = min(leads), max(leads)
            min_r, max_r = min(reliabilities), max(reliabilities)
            min_c, max_c = min(capacities), max(capacities)

            scored_alternatives: list[dict[str, Any]] = []
            for alt in candidate_alts:
                sup_id = alt.get("supplier_id", "")
                name = alt.get("name") or supplier_metadata.get(sup_id, {}).get("name", sup_id)
                u_price = float(alt.get("unit_price", 0.0))
                l_days = int(alt.get("lead_time_days", 0))
                rel = float(supplier_metadata.get(sup_id, {}).get("reliability", 0.90))
                cap = int(alt.get("monthly_capacity", 0))

                norm_price = _norm_lower_better(u_price, min_p, max_p)
                norm_lead = _norm_lower_better(l_days, min_l, max_l)
                norm_rel = _norm_higher_better(rel, min_r, max_r)
                norm_cap = _norm_higher_better(cap, min_c, max_c)

                score = (
                    SCORING_WEIGHTS["price"] * norm_price
                    + SCORING_WEIGHTS["lead_time"] * norm_lead
                    + SCORING_WEIGHTS["reliability"] * norm_rel
                    + SCORING_WEIGHTS["capacity"] * norm_cap
                )

                prem_pct = (
                    round(((u_price - failed_price) / failed_price) * 100.0, 2)
                    if failed_price > 0
                    else 0.0
                )
                cov_pct = (
                    round((cap / monthly_demand) * 100.0, 2)
                    if monthly_demand > 0
                    else 100.0
                )

                scored_alternatives.append(
                    {
                        "supplier_id": sup_id,
                        "name": name,
                        "unit_price": u_price,
                        "price_premium_pct": prem_pct,
                        "lead_time_days": l_days,
                        "reliability": rel,
                        "monthly_capacity": cap,
                        "capacity_coverage_pct": cov_pct,
                        "score": round(score, 4),
                    }
                )

            # Sort ranked alternatives descending by score
            scored_alternatives.sort(key=lambda x: x["score"], reverse=True)

            recommended = scored_alternatives[0] if scored_alternatives else None
            backup = scored_alternatives[1] if len(scored_alternatives) > 1 else None
            single_supplier_can_cover = any(
                a["capacity_coverage_pct"] >= 100.0 for a in scored_alternatives
            )

            if not single_supplier_can_cover:
                skus_needing_split.append(sku_id)

            if recommended:
                prem_per_unit = max(0.0, recommended["unit_price"] - failed_price)
                total_price_premium_estimate += prem_per_unit * monthly_demand

            per_sku_results[sku_id] = {
                "ranked_alternatives": scored_alternatives,
                "recommended": recommended,
                "backup": backup,
                "single_supplier_can_cover": single_supplier_can_cover,
                "failed_supplier_price": failed_price,
                "monthly_demand": round(monthly_demand, 2),
            }

        finish_time = datetime.datetime.now(datetime.timezone.utc)

        facts = {
            "failed_supplier": failed_supplier,
            "disruption_id": disruption_id,
            "affected_skus_count": len(per_sku_results),
            "skus_needing_split_count": len(skus_needing_split),
            "total_price_premium_estimate": round(total_price_premium_estimate, 2),
        }
        fallback_summary = (
            f"Supplier evaluation for {disruption_id}: Evaluated alternatives across {len(per_sku_results)} SKUs. "
            f"{len(skus_needing_split)} SKUs require order splitting across suppliers. "
            f"Estimated monthly price premium: ${total_price_premium_estimate:,.2f}."
        )
        summary = narrate(role="supplier", facts=facts, fallback=fallback_summary)

        return AgentResult(
            agent_name=self.name,
            status="ok",
            summary=summary,
            data={
                "failed_supplier": failed_supplier,
                "disruption_id": disruption_id,
                "per_sku": per_sku_results,
                "skus_needing_split": skus_needing_split,
                "total_price_premium_estimate": round(total_price_premium_estimate, 2),
            },
            started_at=start_time,
            finished_at=finish_time,
        )
