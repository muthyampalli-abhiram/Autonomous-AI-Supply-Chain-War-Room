"""Simulated timeline events and dynamic disruption application."""

from __future__ import annotations

import datetime
from typing import Any, Callable
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from warroom.db.models import Customer, Order
from warroom.graph.detection import restore_supplier, simulate_supplier_outage
from warroom.tools.registry import call_tool, get_logistics_api


class SimEvent(BaseModel):
    """Pydantic model representing a simulated replanning event on the timeline."""

    event_id: str = Field(description="Unique event identifier (e.g. 'EVT-001')")
    day: int = Field(description="Timeline day on which this event occurs")
    event_type: str = Field(
        description="Event type: supplier_outage, supplier_recovery, carrier_delay, demand_surge"
    )
    params: dict[str, Any] = Field(
        default_factory=dict, description="Parameters specific to the event type"
    )
    description: str = Field(description="Human-readable description of the event")


def apply_event(session: Session, event: SimEvent) -> Callable[[], None]:
    """Apply a timeline event to the database or tool registry and return an undo callable.

    Raises:
        ValueError: If event.event_type is unknown.
    """
    evt_type = event.event_type

    if evt_type == "supplier_outage":
        supplier_id = str(event.params["supplier_id"])
        simulate_supplier_outage(session, supplier_id)

        def undo_outage() -> None:
            restore_supplier(session, supplier_id)

        return undo_outage

    elif evt_type == "supplier_recovery":
        supplier_id = str(event.params["supplier_id"])
        restore_supplier(session, supplier_id)

        def undo_recovery() -> None:
            simulate_supplier_outage(session, supplier_id)

        return undo_recovery

    elif evt_type == "carrier_delay":
        mode = str(event.params["mode"]).lower()
        extra_days = int(event.params["extra_days"])

        # Capture current delay prior to mutation
        current_delays = call_tool("get_active_delays")
        prev_delay = current_delays.get(mode, 0)

        call_tool("report_mode_delay", mode=mode, extra_days=extra_days)

        def undo_delay() -> None:
            if prev_delay > 0:
                call_tool("report_mode_delay", mode=mode, extra_days=prev_delay)
            else:
                api = get_logistics_api()
                api.active_delays.pop(mode, None)

        return undo_delay

    elif evt_type == "demand_surge":
        sku_id = str(event.params["sku_id"])
        pct = float(event.params["pct"])
        due_in_days = int(event.params["due_in_days"])

        # Query total baseline ordered quantity for this SKU in the database
        total_baseline = (
            session.scalar(
                select(func.sum(Order.quantity)).where(
                    Order.sku_id == sku_id,
                    ~Order.order_id.like("SURGE-%"),
                )
            )
            or 0
        )

        total_surge_qty = pct * float(total_baseline)
        # Split evenly across 4 orders and round to multiples of 10
        qty_per_order = max(10, int(round((total_surge_qty / 4.0) / 10.0) * 10))

        # Query gold customers
        gold_custs = session.scalars(
            select(Customer.customer_id)
            .where(Customer.tier == "gold")
            .order_by(Customer.customer_id)
        ).all()
        if not gold_custs:
            gold_custs = ["CUST01"]

        # Max order date in the orders table
        max_order_date = (
            session.scalar(select(func.max(Order.order_date)))
            or datetime.date.today()
        )
        due_date = datetime.date.today() + datetime.timedelta(days=due_in_days)

        # Count existing SURGE orders for sequential numbering
        existing_surge = (
            session.scalar(
                select(func.count(Order.order_id)).where(Order.order_id.like("SURGE-%"))
            )
            or 0
        )

        inserted_ids: list[str] = []
        for i in range(4):
            order_id = f"SURGE-{existing_surge + i + 1:03d}"
            cust_id = gold_custs[i % len(gold_custs)]
            surge_order = Order(
                order_id=order_id,
                customer_id=cust_id,
                sku_id=sku_id,
                quantity=qty_per_order,
                order_date=max_order_date,
                due_date=due_date,
                priority=3,
                status="open",
            )
            session.add(surge_order)
            inserted_ids.append(order_id)

        session.commit()

        def undo_surge() -> None:
            session.execute(delete(Order).where(Order.order_id.in_(inserted_ids)))
            session.commit()

        return undo_surge

    else:
        raise ValueError(f"Unknown event type: '{evt_type}'")
