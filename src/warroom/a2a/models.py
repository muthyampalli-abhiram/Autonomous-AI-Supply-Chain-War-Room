"""A2A (Agent-to-Agent) communication protocol data models."""

from __future__ import annotations

import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field


class AgentCard(BaseModel):
    """Metadata card describing an agent and its capabilities."""

    agent_id: str = Field(description="Unique identifier for the agent (e.g. 'supplier')")
    name: str = Field(description="Human-readable name of the agent")
    description: str = Field(default="", description="Summary of responsibilities")
    skills: list[str] = Field(default_factory=list, description="List of capability keywords")
    version: str = Field(default="1.0", description="Card schema or agent version")


class A2AMessage(BaseModel):
    """Standardized message exchanged over the A2A bus."""

    message_id: str = Field(description="Sequential identifier (e.g. 'MSG-0001')")
    task_id: str | None = Field(default=None, description="Associated task identifier if any")
    sender: str = Field(description="Agent ID of the sender")
    recipient: str = Field(description="Agent ID of the recipient, 'all', or 'human_approver'")
    msg_type: Literal[
        "task_request", "status_update", "task_result", "broadcast", "escalation"
    ] = Field(description="Type of A2A message")
    parts: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Payload parts containing text or structured data",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat(),
        description="UTC timestamp of the message",
    )


class A2ATask(BaseModel):
    """Lifecycle tracking for an asynchronous or delegated agent task."""

    task_id: str = Field(description="Sequential identifier (e.g. 'TASK-0001')")
    sender: str = Field(description="Agent ID that requested the task")
    recipient: str = Field(description="Agent ID assigned to execute the task")
    state: Literal["submitted", "working", "completed", "failed"] = Field(
        default="submitted", description="Current execution state"
    )
    state_history: list[dict[str, Any]] = Field(
        default_factory=list, description="Chronological log of state transitions"
    )
    artifact: dict[str, Any] | None = Field(
        default=None, description="Task completion artifact (status and summary)"
    )
    error: str | None = Field(default=None, description="Error message if task failed")
