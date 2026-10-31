"""War Room Orchestrator package."""

from warroom.orchestrator.state import (
    AgentResult,
    WarRoomState,
    create_initial_state,
)

__all__ = [
    "AgentResult",
    "WarRoomState",
    "build_warroom_graph",
    "create_initial_state",
]


def __getattr__(name: str):
    if name == "build_warroom_graph":
        from warroom.orchestrator.graph import build_warroom_graph

        return build_warroom_graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
