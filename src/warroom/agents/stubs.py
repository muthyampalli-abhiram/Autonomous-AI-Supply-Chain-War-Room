"""Stub agent implementations for Autonomous AI Supply Chain War Room.

Each agent is defined in its own isolated class with fixed placeholder outputs
so subsequent prompts can easily replace them with real reasoning and tools
without modifying graph topology.
"""

from __future__ import annotations

import datetime
from typing import Any

from warroom.agents.base import BaseAgent
from warroom.orchestrator.state import AgentResult, WarRoomState


def _get_disruption_id(state: WarRoomState) -> str:
    """Helper to extract or construct a disruption identifier from state."""
    disr = state.get("disruption") or {}
    if "event_id" in disr and disr["event_id"]:
        return str(disr["event_id"])
    if "supplier_id" in disr and disr["supplier_id"]:
        return f"DISR-{disr['supplier_id']}"
    return "DISR-GENERAL"


class SupplierAgent(BaseAgent):
    """Stub agent analyzing supplier operational status and capacity constraints."""

    def __init__(self) -> None:
        super().__init__(name="supplier", result_key="supplier_result")

    def run(self, state: WarRoomState) -> AgentResult:
        disr_id = _get_disruption_id(state)
        summary = f"[STUB] Supplier agent ran for {disr_id}"
        return AgentResult(
            agent_name=self.name,
            status="ok",
            summary=summary,
            data={
                "agent": self.name,
                "disruption_id": disr_id,
                "status": "assessed",
                "notes": "Placeholder supplier evaluation",
            },
            started_at=datetime.datetime.now(datetime.timezone.utc),
            finished_at=datetime.datetime.now(datetime.timezone.utc),
        )


class InventoryAgent(BaseAgent):
    """Stub agent evaluating warehouse stock levels and days of cover."""

    def __init__(self) -> None:
        super().__init__(name="inventory", result_key="inventory_result")

    def run(self, state: WarRoomState) -> AgentResult:
        disr_id = _get_disruption_id(state)
        summary = f"[STUB] Inventory agent ran for {disr_id}"
        return AgentResult(
            agent_name=self.name,
            status="ok",
            summary=summary,
            data={
                "agent": self.name,
                "disruption_id": disr_id,
                "status": "assessed",
                "notes": "Placeholder inventory buffer evaluation",
            },
            started_at=datetime.datetime.now(datetime.timezone.utc),
            finished_at=datetime.datetime.now(datetime.timezone.utc),
        )


class LogisticsAgent(BaseAgent):
    """Stub agent assessing transportation routes, carriers, and freight capacity."""

    def __init__(self) -> None:
        super().__init__(name="logistics", result_key="logistics_result")

    def run(self, state: WarRoomState) -> AgentResult:
        disr_id = _get_disruption_id(state)
        summary = f"[STUB] Logistics agent ran for {disr_id}"
        return AgentResult(
            agent_name=self.name,
            status="ok",
            summary=summary,
            data={
                "agent": self.name,
                "disruption_id": disr_id,
                "status": "assessed",
                "notes": "Placeholder logistics routing evaluation",
            },
            started_at=datetime.datetime.now(datetime.timezone.utc),
            finished_at=datetime.datetime.now(datetime.timezone.utc),
        )


class DemandAgent(BaseAgent):
    """Stub agent projecting customer demand and prioritizing order fulfillment."""

    def __init__(self) -> None:
        super().__init__(name="demand", result_key="demand_result")

    def run(self, state: WarRoomState) -> AgentResult:
        disr_id = _get_disruption_id(state)
        summary = f"[STUB] Demand agent ran for {disr_id}"
        return AgentResult(
            agent_name=self.name,
            status="ok",
            summary=summary,
            data={
                "agent": self.name,
                "disruption_id": disr_id,
                "status": "assessed",
                "notes": "Placeholder demand forecasting evaluation",
            },
            started_at=datetime.datetime.now(datetime.timezone.utc),
            finished_at=datetime.datetime.now(datetime.timezone.utc),
        )


class ProcurementAgent(BaseAgent):
    """Stub agent reallocating purchase orders and contracting alternative suppliers."""

    def __init__(self) -> None:
        super().__init__(name="procurement", result_key="procurement_result")

    def run(self, state: WarRoomState) -> AgentResult:
        disr_id = _get_disruption_id(state)
        summary = f"[STUB] Procurement agent ran for {disr_id}"
        return AgentResult(
            agent_name=self.name,
            status="ok",
            summary=summary,
            data={
                "agent": self.name,
                "disruption_id": disr_id,
                "status": "assessed",
                "notes": "Placeholder procurement split plan",
            },
            started_at=datetime.datetime.now(datetime.timezone.utc),
            finished_at=datetime.datetime.now(datetime.timezone.utc),
        )


class CustomerImpactAgent(BaseAgent):
    """Stub agent calculating client delivery exposure and SLA impacts."""

    def __init__(self) -> None:
        super().__init__(name="customer_impact", result_key="customer_impact_result")

    def run(self, state: WarRoomState) -> AgentResult:
        disr_id = _get_disruption_id(state)
        summary = f"[STUB] Customer Impact agent ran for {disr_id}"
        return AgentResult(
            agent_name=self.name,
            status="ok",
            summary=summary,
            data={
                "agent": self.name,
                "disruption_id": disr_id,
                "status": "assessed",
                "notes": "Placeholder customer SLA impact calculation",
            },
            started_at=datetime.datetime.now(datetime.timezone.utc),
            finished_at=datetime.datetime.now(datetime.timezone.utc),
        )
