"""LangGraph workflow definition for the War Room Orchestrator with A2A bus integration."""

from __future__ import annotations

import datetime
from typing import Any
from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from warroom.a2a.bus import A2ABus
from warroom.a2a.models import AgentCard
from warroom.agents.base import create_agent_node
from warroom.agents.customer_impact_agent import CustomerImpactAgent
from warroom.agents.demand_agent import DemandAgent
from warroom.agents.inventory_agent import InventoryAgent
from warroom.agents.logistics_agent import LogisticsAgent
from warroom.agents.procurement_agent import ProcurementAgent
from warroom.agents.supplier_agent import SupplierAgent
from warroom.graph.analysis import impact_of_supplier_failure
from warroom.graph.builder import build_supply_graph
from warroom.graph.detection import detect_disruptions
from warroom.orchestrator.state import WarRoomState

SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def build_warroom_graph(session: Session) -> Any:
    """Build and compile the LangGraph War Room StateGraph with an in-process A2A message bus.

    The session and A2A bus are captured via closure and never stored in state.

    Node sequence:
      orchestrator_intake -> [conditional: END if nominal, else supplier] ->
      supplier -> inventory -> logistics -> demand -> procurement ->
      customer_impact -> orchestrator_finalize -> END
    """
    workflow = StateGraph(WarRoomState)
    bus = A2ABus()

    # Register A2A Agent Cards
    bus.register(
        AgentCard(
            agent_id="orchestrator",
            name="War Room Orchestrator",
            description="Coordinates domain agents and manages response plans",
            skills=["incident_response", "workflow_orchestration"],
        )
    )
    bus.register(
        AgentCard(
            agent_id="supplier",
            name="Supplier Agent",
            description="Alternative vendor discovery and multicriteria evaluation",
            skills=["alternative_supplier_discovery", "supplier_scoring"],
        )
    )
    bus.register(
        AgentCard(
            agent_id="inventory",
            name="Inventory Agent",
            description="Warehouse stock allocation and shortage assessment",
            skills=["stock_allocation", "shortage_analysis"],
        )
    )
    bus.register(
        AgentCard(
            agent_id="logistics",
            name="Logistics Agent",
            description="Multi-modal freight routing and transit optimization",
            skills=["route_optimization", "freight_quoting"],
        )
    )
    bus.register(
        AgentCard(
            agent_id="demand",
            name="Demand Agent",
            description="Demand trend analysis, uplift forecasting, and stockout projection",
            skills=["demand_forecasting", "stockout_projection"],
        )
    )
    bus.register(
        AgentCard(
            agent_id="procurement",
            name="Procurement Agent",
            description="Purchase order generation and supplier capacity allocation",
            skills=["po_generation", "procurement_planning"],
        )
    )
    bus.register(
        AgentCard(
            agent_id="customer_impact",
            name="Customer Impact Agent",
            description="Order recovery, SLA penalty calculation, and customer risk assessment",
            skills=["sla_penalty_calculation", "customer_risk_assessment"],
        )
    )
    bus.register(
        AgentCard(
            agent_id="human_approver",
            name="Human Executive Approver",
            description="Human authority for financial sign-off and risk governance",
            skills=["executive_approval", "risk_governance"],
        )
    )

    # 1. Orchestrator Intake Node
    def orchestrator_intake(state: WarRoomState) -> dict[str, Any]:
        disruptions = detect_disruptions(session)
        if not disruptions:
            return {
                "status": "nominal",
                "disruption": None,
            }

        # Select highest-severity disruption event
        sorted_disruptions = sorted(
            disruptions,
            key=lambda d: (SEVERITY_RANK.get(d.severity, 0), d.affected_sku_count),
            reverse=True,
        )
        selected = sorted_disruptions[0]
        selected_dict = (
            selected.model_dump() if hasattr(selected, "model_dump") else dict(selected)
        )

        # Compute graph impact of supplier failure
        G = build_supply_graph(session)
        impact = impact_of_supplier_failure(G, session, selected.supplier_id)

        announcement = {
            "from": "orchestrator",
            "to": "all",
            "type": "disruption_announcement",
            "summary": (
                f"Disruption detected for supplier {selected.supplier_id} "
                f"(Severity: {selected.severity.upper()}, Affected SKUs: {selected.affected_sku_count})"
            ),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        # A2A Broadcast announcement
        bus.broadcast(
            sender="orchestrator",
            text=announcement["summary"],
            data=selected_dict,
        )

        return {
            "disruption": selected_dict,
            "impact": impact,
            "status": "responding",
            "plan_version": 1,
            "messages": [announcement],
        }

    # 2. Domain Agent Nodes wired through A2A Bus
    supplier_node = create_agent_node(SupplierAgent(session), bus=bus)
    inventory_node = create_agent_node(InventoryAgent(session), bus=bus)
    logistics_node = create_agent_node(LogisticsAgent(session), bus=bus)
    demand_node = create_agent_node(DemandAgent(session), bus=bus)
    procurement_node = create_agent_node(ProcurementAgent(session), bus=bus)
    customer_impact_node = create_agent_node(CustomerImpactAgent(session), bus=bus)

    # 3. Orchestrator Finalize Node
    def orchestrator_finalize(state: WarRoomState) -> dict[str, Any]:
        disruption = state.get("disruption") or {}
        disruption_id = disruption.get("event_id") or (
            f"DISR-{disruption.get('supplier_id')}"
            if disruption.get("supplier_id")
            else "DISR-NONE"
        )

        agent_keys = [
            ("supplier", "supplier_result"),
            ("inventory", "inventory_result"),
            ("logistics", "logistics_result"),
            ("demand", "demand_result"),
            ("procurement", "procurement_result"),
            ("customer_impact", "customer_impact_result"),
        ]

        agent_summaries = {}
        for agent_name, res_key in agent_keys:
            res = state.get(res_key)
            if isinstance(res, dict) and "summary" in res:
                agent_summaries[agent_name] = res["summary"]
            else:
                agent_summaries[agent_name] = f"[SKIPPED] {agent_name} did not run"

        # A2A Escalations:
        # 1. Procurement approval_required -> human_approver
        proc_res = state.get("procurement_result") or {}
        proc_data = proc_res.get("data", {}) if isinstance(proc_res, dict) else {}
        approval_req = proc_data.get("approval_required", False)
        tot_landed = proc_data.get("totals", {}).get("total_landed_cost", 0.0)
        po_cnt = proc_data.get("totals", {}).get("po_count", 0)

        if approval_req:
            bus.escalate(
                sender="orchestrator",
                recipient="human_approver",
                text=(
                    f"Procurement approval required: Total landed cost ${tot_landed:,.2f} "
                    f"for {po_cnt} purchase orders exceeds approval threshold."
                ),
                data={"total_landed_cost": tot_landed, "po_count": po_cnt},
            )

        # 2. Procurement unsourced_by_sku not empty -> supplier
        unsourced_by_sku = proc_data.get("unsourced_by_sku", {})
        if unsourced_by_sku:
            unsourced_list = list(unsourced_by_sku.keys())
            bus.escalate(
                sender="orchestrator",
                recipient="supplier",
                text=f"additional sourcing needed for SKUs: {unsourced_list}",
                data={"unsourced_by_sku": unsourced_by_sku, "skus": unsourced_list},
            )

        # 3. Customer impact overall_risk in ("critical", "high") -> human_approver
        ci_res = state.get("customer_impact_result") or {}
        ci_data = ci_res.get("data", {}) if isinstance(ci_res, dict) else {}
        overall_risk = ci_data.get("overall_risk", "low")
        top_custs = ci_data.get("top_customers_at_risk", [])

        if overall_risk in ("critical", "high"):
            bus.escalate(
                sender="orchestrator",
                recipient="human_approver",
                text=(
                    f"Customer risk escalated to {overall_risk.upper()}. "
                    f"At-risk customers: {top_custs}"
                ),
                data={"overall_risk": overall_risk, "top_customers": top_custs},
            )

        # Build final plan
        task_states = {t.recipient: t.state for t in bus.tasks.values()}
        escalation_count = sum(
            1 for m in bus._messages if m.msg_type == "escalation"
        )
        financials = ci_data.get("financials", {})
        plan_effect = ci_data.get("plan_effect", {})

        final_plan = {
            "disruption_id": disruption_id,
            "disruption": disruption,
            "plan_version": state.get("plan_version", 1),
            "agent_summaries": agent_summaries,
            "status": "complete",
            "a2a": {
                "message_count": len(bus._messages),
                "task_states": task_states,
                "escalation_count": escalation_count,
            },
            "headline": {
                "overall_risk": overall_risk,
                "revenue_delayed": financials.get("revenue_delayed", 0.0),
                "revenue_lost": financials.get("revenue_lost", 0.0),
                "sla_penalty_total": financials.get("sla_penalty_total", 0.0),
                "response_cost": financials.get("response_cost", 0.0),
                "net_financial_exposure": financials.get(
                    "net_financial_exposure", 0.0
                ),
                "value_protected": plan_effect.get("value_protected", 0.0),
            },
        }

        return {
            "final_plan": final_plan,
            "status": "complete",
            "a2a_log": bus.log,
        }

    # Add all nodes to graph
    workflow.add_node("orchestrator_intake", orchestrator_intake)
    workflow.add_node("supplier", supplier_node)
    workflow.add_node("inventory", inventory_node)
    workflow.add_node("logistics", logistics_node)
    workflow.add_node("demand", demand_node)
    workflow.add_node("procurement", procurement_node)
    workflow.add_node("customer_impact", customer_impact_node)
    workflow.add_node("orchestrator_finalize", orchestrator_finalize)

    # Entry point
    workflow.set_entry_point("orchestrator_intake")

    # Conditional edge after intake
    def route_intake(state: WarRoomState) -> str:
        if state.get("status") == "nominal" or not state.get("disruption"):
            return END
        return "supplier"

    workflow.add_conditional_edges(
        "orchestrator_intake",
        route_intake,
        {
            END: END,
            "supplier": "supplier",
        },
    )

    # Linear workflow sequence
    workflow.add_edge("supplier", "inventory")
    workflow.add_edge("inventory", "logistics")
    workflow.add_edge("logistics", "demand")
    workflow.add_edge("demand", "procurement")
    workflow.add_edge("procurement", "customer_impact")
    workflow.add_edge("customer_impact", "orchestrator_finalize")
    workflow.add_edge("orchestrator_finalize", END)

    return workflow.compile()
