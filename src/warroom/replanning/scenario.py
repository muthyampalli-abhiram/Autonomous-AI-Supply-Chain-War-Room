"""Default timeline scenario definitions for supply chain replanning."""

from __future__ import annotations

from warroom.replanning.events import SimEvent


def default_scenario() -> list[SimEvent]:
    """Return the canonical 5-event supply disruption timeline sorted by day.

    Timeline:
      day 0:  supplier_outage SUP01 (Primary supplier catastrophic failure)
      day 3:  carrier_delay air +6 days (Global air freight bottleneck)
      day 6:  supplier_outage SUP07 (Backup supplier failure, primary for no SKU)
      day 10: demand_surge SKU004, pct 0.5, due_in_days 7 (Critical customer order spike)
      day 14: supplier_recovery SUP01 (Primary supplier restoration)
    """
    events = [
        SimEvent(
            event_id="EVT-001",
            day=0,
            event_type="supplier_outage",
            params={"supplier_id": "SUP01"},
            description="Primary supplier SUP01 outage declared across 7 critical SKUs",
        ),
        SimEvent(
            event_id="EVT-002",
            day=3,
            event_type="carrier_delay",
            params={"mode": "air", "extra_days": 6},
            description="Air freight capacity crunch adds +6 days transit delay to all air shipments",
        ),
        SimEvent(
            event_id="EVT-003",
            day=6,
            event_type="supplier_outage",
            params={"supplier_id": "SUP07"},
            description="Secondary supplier SUP07 goes offline (backup source for SKU005)",
        ),
        SimEvent(
            event_id="EVT-004",
            day=10,
            event_type="demand_surge",
            params={"sku_id": "SKU004", "pct": 0.5, "due_in_days": 7},
            description="Sudden demand surge for SKU004 (+50% volume from Gold customers due in 7 days)",
        ),
        SimEvent(
            event_id="EVT-005",
            day=14,
            event_type="supplier_recovery",
            params={"supplier_id": "SUP01"},
            description="Primary supplier SUP01 fully restored to active operations",
        ),
    ]

    return sorted(events, key=lambda e: e.day)
