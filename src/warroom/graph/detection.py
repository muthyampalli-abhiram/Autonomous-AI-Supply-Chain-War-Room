"""Disruption detection and outage simulation for supply chain war room."""

from __future__ import annotations

import datetime
from typing import Literal
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from warroom.db.models import Supplier, SupplierSKU


class DisruptionEvent(BaseModel):
    """Pydantic model representing a detected supply chain disruption event."""

    event_id: str = Field(description="Unique disruption event identifier")
    event_type: str = Field(
        default="supplier_outage", description="Type of disruption event"
    )
    supplier_id: str = Field(description="Identifier of disrupted supplier")
    severity: Literal["low", "medium", "high", "critical"] = Field(
        description="Assessed severity level"
    )
    detected_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc),
        description="Timestamp when event was detected",
    )
    expected_duration_days: int = Field(
        default=30, description="Estimated duration of outage in days"
    )
    affected_sku_count: int = Field(
        description="Number of SKUs where disrupted supplier is primary"
    )


def detect_disruptions(
    session: Session,
    default_duration_days: int = 30,
) -> list[DisruptionEvent]:
    """Scan database for suppliers whose status is not 'active'.

    Severity rules:
      - 'critical': if is_key_supplier or any sole-source SKU
      - 'high': if 5+ affected SKUs
      - 'medium': if 2-4 affected SKUs
      - 'low': otherwise
    """
    disrupted_suppliers = session.scalars(
        select(Supplier).where(func.lower(Supplier.status) != "active")
    ).all()

    events: list[DisruptionEvent] = []

    for sup in disrupted_suppliers:
        # Find primary SKUs affected by this supplier
        primary_skus = session.scalars(
            select(SupplierSKU.sku_id).where(
                SupplierSKU.supplier_id == sup.supplier_id,
                SupplierSKU.is_primary == True,  # noqa: E712
            )
        ).all()

        affected_sku_count = len(primary_skus)

        # Check if any affected SKU has no other active supplier (sole-sourced)
        has_sole_source = False
        for sku_id in primary_skus:
            other_active_count = session.scalar(
                select(func.count(SupplierSKU.supplier_id))
                .join(Supplier, SupplierSKU.supplier_id == Supplier.supplier_id)
                .where(
                    SupplierSKU.sku_id == sku_id,
                    SupplierSKU.supplier_id != sup.supplier_id,
                    func.lower(Supplier.status) == "active",
                )
            )
            if other_active_count is None or other_active_count == 0:
                has_sole_source = True
                break

        # Apply severity rule
        if sup.is_key_supplier or has_sole_source:
            severity: Literal["low", "medium", "high", "critical"] = "critical"
        elif affected_sku_count >= 5:
            severity = "high"
        elif 2 <= affected_sku_count <= 4:
            severity = "medium"
        else:
            severity = "low"

        event = DisruptionEvent(
            event_id=f"DISR-{sup.supplier_id}",
            event_type="supplier_outage",
            supplier_id=sup.supplier_id,
            severity=severity,
            detected_at=datetime.datetime.now(datetime.timezone.utc),
            expected_duration_days=default_duration_days,
            affected_sku_count=affected_sku_count,
        )
        events.append(event)

    return events


def simulate_supplier_outage(
    session: Session,
    supplier_id: str,
    duration_days: int = 30,
) -> None:
    """Simulate a supplier outage by setting status to 'unavailable' and committing."""
    sup = session.get(Supplier, supplier_id)
    if sup is None:
        raise ValueError(f"Supplier '{supplier_id}' not found in database")

    sup.status = "unavailable"
    session.commit()


def restore_supplier(
    session: Session,
    supplier_id: str,
) -> None:
    """Restore a supplier by setting status back to 'active' and committing."""
    sup = session.get(Supplier, supplier_id)
    if sup is None:
        raise ValueError(f"Supplier '{supplier_id}' not found in database")

    sup.status = "active"
    session.commit()
