"""Shared state definitions and models for the War Room LangGraph orchestrator."""

from __future__ import annotations

import datetime
import operator
from typing import Annotated, Any, Literal, TypedDict
from pydantic import BaseModel, Field


class AgentResult(BaseModel):
    """Execution output from a specialized War Room domain agent."""

    agent_name: str = Field(description="Identifier or name of the executing agent")
    status: Literal["ok", "skipped", "error"] = Field(
        default="ok", description="Status outcome of the agent execution"
    )
    summary: str = Field(description="Human-readable single-line summary of results")
    data: dict[str, Any] = Field(
        default_factory=dict, description="Structured payload produced by the agent"
    )
    started_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc),
        description="Timestamp when agent execution started",
    )
    finished_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc),
        description="Timestamp when agent execution finished",
    )


class WarRoomState(TypedDict, total=False):
    """Shared state dictionary tracked and modified across LangGraph nodes."""

    run_id: str
    disruption: dict[str, Any] | None
    impact: dict[str, Any]
    supplier_result: dict[str, Any] | None
    inventory_result: dict[str, Any] | None
    logistics_result: dict[str, Any] | None
    demand_result: dict[str, Any] | None
    procurement_result: dict[str, Any] | None
    customer_impact_result: dict[str, Any] | None
    plan_version: int
    messages: Annotated[list[dict[str, Any]], operator.add]
    status: str  # "nominal" / "responding" / "complete"
    final_plan: dict[str, Any] | None
    a2a_log: list[dict[str, Any]]


def create_initial_state(run_id: str | None = None) -> WarRoomState:
    """Create a default initialized WarRoomState instance."""
    if run_id is None:
        run_id = f"RUN-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')}"

    return {
        "run_id": run_id,
        "disruption": None,
        "impact": {},
        "supplier_result": None,
        "inventory_result": None,
        "logistics_result": None,
        "demand_result": None,
        "procurement_result": None,
        "customer_impact_result": None,
        "plan_version": 0,
        "messages": [],
        "status": "nominal",
        "final_plan": None,
        "a2a_log": [],
    }
