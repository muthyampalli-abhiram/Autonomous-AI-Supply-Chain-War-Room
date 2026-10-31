"""In-process tool registry mapping tool names to callable implementations."""

from __future__ import annotations

from typing import Any, Callable
from sqlalchemy.orm import Session

from warroom.tools.logistics_api import SimulatedLogisticsAPI

_active_api: SimulatedLogisticsAPI | None = None


def get_logistics_api(session: Session | None = None) -> SimulatedLogisticsAPI:
    """Retrieve or initialize the active SimulatedLogisticsAPI instance."""
    global _active_api
    if session is not None:
        _active_api = SimulatedLogisticsAPI(session)
        return _active_api
    if _active_api is None:
        from warroom.db.session import get_session
        _active_api = SimulatedLogisticsAPI(get_session())
    return _active_api


def set_logistics_api(api: SimulatedLogisticsAPI) -> None:
    """Explicitly set the active SimulatedLogisticsAPI instance."""
    global _active_api
    _active_api = api


def list_carriers() -> list[dict[str, Any]]:
    """List all available freight carriers."""
    return get_logistics_api().list_carriers()


def get_route_quotes(
    origin_country: str, warehouse_id: str, sku_id: str, quantity: int
) -> list[dict[str, Any]]:
    """Get freight quotes across all carriers for a given lane."""
    return get_logistics_api().get_route_quotes(
        origin_country=origin_country,
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        quantity=quantity,
    )


def report_mode_delay(mode: str, extra_days: int) -> dict[str, Any]:
    """Wrap set_mode_delay to record transit delay for a mode."""
    get_logistics_api().set_mode_delay(mode, extra_days)
    return {"status": "ok", "mode": mode, "extra_days": extra_days}


def get_active_delays() -> dict[str, int]:
    """Get all currently active mode transit delays."""
    return get_logistics_api().get_active_delays()


def clear_delays() -> dict[str, Any]:
    """Clear all active transit delays."""
    get_logistics_api().clear_delays()
    return {"status": "ok", "message": "All delays cleared"}


REGISTRY: dict[str, Callable[..., Any]] = {
    "list_carriers": list_carriers,
    "get_route_quotes": get_route_quotes,
    "report_mode_delay": report_mode_delay,
    "get_active_delays": get_active_delays,
}


def call_tool(name: str, **kwargs: Any) -> Any:
    """Invoke a registered tool by name with keyword arguments."""
    if name == "clear_delays":
        return clear_delays()
    if name not in REGISTRY:
        raise ValueError(
            f"Unknown tool '{name}'. Available tools: {list(REGISTRY.keys())}"
        )
    return REGISTRY[name](**kwargs)
