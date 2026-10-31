"""Base agent interface and LangGraph node wrapping helper."""

from __future__ import annotations

import abc
import datetime
from typing import TYPE_CHECKING, Any, Callable

from warroom.orchestrator.state import AgentResult

if TYPE_CHECKING:
    from warroom.orchestrator.state import WarRoomState


class BaseAgent(abc.ABC):
    """Abstract base class for all War Room domain agents."""

    def __init__(self, name: str, result_key: str | None = None) -> None:
        self.name = name
        self.result_key = result_key or f"{name.lower().replace(' ', '_')}_result"

    @abc.abstractmethod
    def run(self, state: WarRoomState) -> AgentResult:
        """Execute agent analysis or planning logic and return an AgentResult."""
        pass

    def to_node(self) -> Callable[[WarRoomState], dict[str, Any]]:
        """Convert this agent instance into a callable LangGraph node."""
        return create_agent_node(self)


def create_agent_node(
    agent: BaseAgent, bus: Any = None
) -> Callable[[WarRoomState], dict[str, Any]]:
    """Wrap a BaseAgent.run() method into a LangGraph node function.

    Calls run(state), saves the AgentResult dictionary under agent.result_key,
    and appends a structured result message to the state messages list.
    If bus is provided, coordinates through the A2A bus.
    """

    def agent_node(state: WarRoomState) -> dict[str, Any]:
        task = None
        if bus is not None:
            task = bus.send_task(
                sender="orchestrator",
                recipient=agent.name,
                text=f"Execute domain analysis for agent {agent.name}",
            )
            bus.update_task(task.task_id, "working")

        try:
            result = agent.run(state)
        except Exception as exc:
            if bus is not None and task is not None:
                bus.fail_task(task.task_id, error=str(exc))
            raise

        if bus is not None and task is not None:
            if result.status == "error":
                bus.fail_task(task.task_id, error=result.summary)
            else:
                artifact = {
                    "status": result.status,
                    "summary": result.summary,
                }
                bus.complete_task(
                    task.task_id, artifact=artifact, text=result.summary
                )

        result_dict = (
            result.model_dump() if hasattr(result, "model_dump") else dict(result)
        )

        message = {
            "from": agent.name,
            "to": "orchestrator",
            "type": "result",
            "summary": result.summary,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        return {
            agent.result_key: result_dict,
            "messages": [message],
        }

    return agent_node
