"""Deterministic simulated logistics API for freight route quotes and transit estimation."""

from __future__ import annotations

import math
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from warroom.db.models import Carrier, SKU, Warehouse

# SKU unit weight in kg by category, with per-SKU overrides
SKU_UNIT_WEIGHT_KG: dict[str, float] = {
    "Semiconductors": 0.02,
    "Energy Storage": 0.5,
    "Sensors": 0.1,
    "Displays": 0.4,
    "Passive Components": 0.01,
    "Electromechanical": 1.5,
    "Optoelectronics": 0.05,
    "Mechanical": 2.0,
    "Connectivity": 0.03,
    "Thermal Management": 0.2,
}
DEFAULT_UNIT_WEIGHT_KG: float = 0.5

SKU_WEIGHT_OVERRIDES: dict[str, float] = {
    "SKU004": 0.5,  # Li-ion Battery Cell 21700
    "SKU005": 6.0,  # Solid-State Battery Pack 48V
}

# Country to geographic region mapping
COUNTRY_REGION: dict[str, str] = {
    "Taiwan": "Asia",
    "Japan": "Asia",
    "China": "Asia",
    "South Korea": "Asia",
    "India": "Asia",
    "Malaysia": "Asia",
    "Singapore": "Asia",
    "Germany": "Europe",
    "Sweden": "Europe",
    "Italy": "Europe",
    "Spain": "Europe",
    "Poland": "Europe",
    "Switzerland": "Europe",
    "Netherlands": "Europe",
    "United States": "North America",
    "Canada": "North America",
    "Mexico": "North America",
}

# Distance multiplier factor by region pair: same=0.4, adjacent=0.7, intercontinental=1.0
DISTANCE_FACTOR: dict[tuple[str, str], float] = {
    ("Asia", "Asia"): 0.4,
    ("Europe", "Europe"): 0.4,
    ("North America", "North America"): 0.4,
    ("Asia", "Europe"): 0.7,
    ("Europe", "Asia"): 0.7,
    ("North America", "Asia"): 1.0,
    ("Asia", "North America"): 1.0,
    ("North America", "Europe"): 1.0,
    ("Europe", "North America"): 1.0,
}

# Fixed shipment handling fees and on-time reliability by mode
MODE_HANDLING_FEE: dict[str, float] = {
    "air": 400.0,
    "road": 150.0,
    "sea": 250.0,
}

MODE_ON_TIME_PROB: dict[str, float] = {
    "air": 0.97,
    "road": 0.93,
    "sea": 0.85,
}


def get_distance_factor(origin_region: str, dest_region: str) -> float:
    """Calculate distance multiplier between regions."""
    if origin_region == dest_region and origin_region != "Other":
        return 0.4
    if (origin_region, dest_region) in DISTANCE_FACTOR:
        return DISTANCE_FACTOR[(origin_region, dest_region)]
    if frozenset({origin_region, dest_region}) == frozenset({"Asia", "Europe"}):
        return 0.7
    return 1.0


class SimulatedLogisticsAPI:
    """Fully deterministic logistics calculation engine."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.active_delays: dict[str, int] = {}

    def list_carriers(self) -> list[dict[str, Any]]:
        """List all carriers from the database."""
        carriers = self.session.scalars(
            select(Carrier).order_by(Carrier.carrier_id)
        ).all()
        return [
            {
                "carrier_id": c.carrier_id,
                "name": c.name,
                "mode": c.mode,
                "cost_per_kg": float(c.cost_per_kg),
                "speed_days": int(c.speed_days),
            }
            for c in carriers
        ]

    def set_mode_delay(self, mode: str, extra_days: int) -> None:
        """Set active delay in days for a transport mode."""
        self.active_delays[mode.lower()] = int(extra_days)

    def clear_delays(self) -> None:
        """Clear all active transport mode delays."""
        self.active_delays.clear()

    def get_active_delays(self) -> dict[str, int]:
        """Return currently active mode delays."""
        return dict(self.active_delays)

    def get_route_quotes(
        self, origin_country: str, warehouse_id: str, sku_id: str, quantity: int
    ) -> list[dict[str, Any]]:
        """Compute deterministic freight quotes across all available carriers."""
        # 1. Lookup warehouse destination country and region
        wh = self.session.scalar(
            select(Warehouse).where(Warehouse.warehouse_id == warehouse_id)
        )
        dest_country = wh.country if wh else "Other"

        origin_region = COUNTRY_REGION.get(origin_country, "Other")
        dest_region = COUNTRY_REGION.get(dest_country, "Other")
        dist_factor = get_distance_factor(origin_region, dest_region)

        # 2. Lookup SKU unit weight
        if sku_id in SKU_WEIGHT_OVERRIDES:
            unit_weight = SKU_WEIGHT_OVERRIDES[sku_id]
        else:
            sku = self.session.scalar(select(SKU).where(SKU.sku_id == sku_id))
            category = sku.category if sku else "Other"
            unit_weight = SKU_UNIT_WEIGHT_KG.get(category, DEFAULT_UNIT_WEIGHT_KG)

        # 3. Calculate quotes for each carrier
        carriers = self.list_carriers()
        quotes: list[dict[str, Any]] = []

        for c in carriers:
            mode = c["mode"].lower()
            cost_per_kg = float(c["cost_per_kg"])
            speed_days = int(c["speed_days"])
            handling_fee = MODE_HANDLING_FEE.get(mode, 200.0)
            on_time_prob = MODE_ON_TIME_PROB.get(mode, 0.90)

            freight_total = (
                cost_per_kg * unit_weight * quantity * dist_factor + handling_fee
            )
            freight_per_unit = (freight_total / quantity) if quantity > 0 else 0.0

            base_transit = max(1, math.ceil(speed_days * dist_factor))
            delay = self.active_delays.get(mode, 0)
            transit_days = base_transit + delay

            quotes.append(
                {
                    "carrier_id": c["carrier_id"],
                    "mode": mode,
                    "freight_total": round(freight_total, 2),
                    "freight_per_unit": round(freight_per_unit, 2),
                    "transit_days": int(transit_days),
                    "on_time_prob": round(on_time_prob, 2),
                }
            )

        return quotes
