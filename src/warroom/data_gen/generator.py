"""Synthetic data generator for Autonomous AI Supply Chain War Room."""

from __future__ import annotations

import datetime
from typing import Any
import numpy as np
import pandas as pd

from warroom.config import get_settings

# Curated reference metadata for realistic entities
SUPPLIER_CATALOG = [
    {"supplier_id": "SUP01", "name": "Apex Precision Semiconductor", "country": "Taiwan", "reliability_score": 0.96, "lead_time_days": 14, "status": "active", "is_key_supplier": True},
    {"supplier_id": "SUP02", "name": "Kyoto Micro-Optics", "country": "Japan", "reliability_score": 0.94, "lead_time_days": 18, "status": "active", "is_key_supplier": False},
    {"supplier_id": "SUP03", "name": "Shenzhen Integrated Circuits", "country": "China", "reliability_score": 0.91, "lead_time_days": 12, "status": "active", "is_key_supplier": False},
    {"supplier_id": "SUP04", "name": "Bavaria Mechatronics AG", "country": "Germany", "reliability_score": 0.97, "lead_time_days": 10, "status": "active", "is_key_supplier": False},
    {"supplier_id": "SUP05", "name": "Nordic Silicon Works", "country": "Sweden", "reliability_score": 0.95, "lead_time_days": 16, "status": "active", "is_key_supplier": False},
    {"supplier_id": "SUP06", "name": "Seoul Advanced Displays", "country": "South Korea", "reliability_score": 0.93, "lead_time_days": 15, "status": "active", "is_key_supplier": False},
    {"supplier_id": "SUP07", "name": "Hindustan Precision Fasteners", "country": "India", "reliability_score": 0.88, "lead_time_days": 21, "status": "active", "is_key_supplier": False},
    {"supplier_id": "SUP08", "name": "Verona Hydraulic Motion", "country": "Italy", "reliability_score": 0.92, "lead_time_days": 14, "status": "active", "is_key_supplier": False},
    {"supplier_id": "SUP09", "name": "Osaka Nanotech Corp", "country": "Japan", "reliability_score": 0.95, "lead_time_days": 17, "status": "active", "is_key_supplier": False},
    {"supplier_id": "SUP10", "name": "Guangdong Polymer Materials", "country": "China", "reliability_score": 0.89, "lead_time_days": 14, "status": "active", "is_key_supplier": False},
    {"supplier_id": "SUP11", "name": "Valencian Dynamics S.L.", "country": "Spain", "reliability_score": 0.90, "lead_time_days": 13, "status": "active", "is_key_supplier": False},
    {"supplier_id": "SUP12", "name": "Silesian Industrial Forge", "country": "Poland", "reliability_score": 0.87, "lead_time_days": 19, "status": "active", "is_key_supplier": False},
    {"supplier_id": "SUP13", "name": "Penang Electronics Assembly", "country": "Malaysia", "reliability_score": 0.92, "lead_time_days": 16, "status": "active", "is_key_supplier": False},
    {"supplier_id": "SUP14", "name": "Austin Micro Technologies", "country": "United States", "reliability_score": 0.96, "lead_time_days": 8, "status": "active", "is_key_supplier": False},
    {"supplier_id": "SUP15", "name": "Zurich Sensor Systems", "country": "Switzerland", "reliability_score": 0.98, "lead_time_days": 9, "status": "active", "is_key_supplier": False},
]

SKU_CATALOG = [
    {"sku_id": "SKU001", "name": "Microcontroller Unit MCU-32", "category": "Semiconductors", "unit_cost": 45.0, "unit_price": 72.0},
    {"sku_id": "SKU002", "name": "Power Management IC PMIC-8", "category": "Semiconductors", "unit_cost": 18.5, "unit_price": 30.0},
    {"sku_id": "SKU003", "name": "FPGA Acceleration Board", "category": "Semiconductors", "unit_cost": 185.0, "unit_price": 295.0},
    {"sku_id": "SKU004", "name": "Li-ion Battery Cell 21700", "category": "Energy Storage", "unit_cost": 12.0, "unit_price": 20.0},
    {"sku_id": "SKU005", "name": "Solid-State Battery Pack 48V", "category": "Energy Storage", "unit_cost": 310.0, "unit_price": 480.0},
    {"sku_id": "SKU006", "name": "6-Axis IMU Motion Sensor", "category": "Sensors", "unit_cost": 22.0, "unit_price": 36.0},
    {"sku_id": "SKU007", "name": "Automotive LiDAR Module", "category": "Sensors", "unit_cost": 420.0, "unit_price": 650.0},
    {"sku_id": "SKU008", "name": "AMOLED Display Panel 6.7-inch", "category": "Displays", "unit_cost": 65.0, "unit_price": 105.0},
    {"sku_id": "SKU009", "name": "E-Paper Display Module 10-inch", "category": "Displays", "unit_cost": 40.0, "unit_price": 68.0},
    {"sku_id": "SKU010", "name": "Ceramic Capacitor Array 100uF", "category": "Passive Components", "unit_cost": 3.5, "unit_price": 6.0},
    {"sku_id": "SKU011", "name": "Ferrite Core Inductor 22uH", "category": "Passive Components", "unit_cost": 2.8, "unit_price": 5.0},
    {"sku_id": "SKU012", "name": "Brushless DC Motor 48V 500W", "category": "Electromechanical", "unit_cost": 75.0, "unit_price": 120.0},
    {"sku_id": "SKU013", "name": "Industrial Rotary Encoder 14-bit", "category": "Electromechanical", "unit_cost": 55.0, "unit_price": 90.0},
    {"sku_id": "SKU014", "name": "Optical Transceiver SFP+ 10Gbps", "category": "Optoelectronics", "unit_cost": 38.0, "unit_price": 62.0},
    {"sku_id": "SKU015", "name": "CNC Milled Aluminum Enclosure", "category": "Mechanical", "unit_cost": 28.0, "unit_price": 48.0},
    {"sku_id": "SKU016", "name": "Titanium Fastener Kit M4-M8", "category": "Mechanical", "unit_cost": 14.0, "unit_price": 24.0},
    {"sku_id": "SKU017", "name": "Wi-Fi 6E / BLE 5.3 RF Module", "category": "Connectivity", "unit_cost": 16.0, "unit_price": 27.0},
    {"sku_id": "SKU018", "name": "Gigabit Ethernet PHY Transceiver", "category": "Connectivity", "unit_cost": 9.5, "unit_price": 16.0},
    {"sku_id": "SKU019", "name": "High-Conductivity Heat Pipe Assembly", "category": "Thermal Management", "unit_cost": 15.0, "unit_price": 26.0},
    {"sku_id": "SKU020", "name": "Graphite Thermal Pad Sheet", "category": "Thermal Management", "unit_cost": 6.0, "unit_price": 11.0},
]

WAREHOUSE_CATALOG = [
    {"warehouse_id": "WH01", "name": "North America Logistics Hub", "city": "Chicago", "country": "United States", "capacity": 150000},
    {"warehouse_id": "WH02", "name": "European Distribution Center", "city": "Rotterdam", "country": "Netherlands", "capacity": 120000},
    {"warehouse_id": "WH03", "name": "Asia-Pacific Gateway", "city": "Singapore", "country": "Singapore", "capacity": 180000},
    {"warehouse_id": "WH04", "name": "East Asia Regional Depot", "city": "Tokyo", "country": "Japan", "capacity": 100000},
]

CARRIER_CATALOG = [
    {"carrier_id": "CAR01", "name": "Skyline Global Air Cargo", "mode": "air", "cost_per_kg": 8.50, "speed_days": 2},
    {"carrier_id": "CAR02", "name": "Pacific Maritime Lines", "mode": "sea", "cost_per_kg": 1.15, "speed_days": 22},
    {"carrier_id": "CAR03", "name": "Continental Freight Express", "mode": "road", "cost_per_kg": 3.25, "speed_days": 5},
]

# 8 customers: exactly 3 gold, 3 silver, 2 bronze
CUSTOMER_CATALOG = [
    {"customer_id": "CUST01", "name": "Quantum Robotics Corp", "tier": "gold", "region": "North America"},
    {"customer_id": "CUST02", "name": "AeroSpace Avionics Ltd", "tier": "gold", "region": "Europe"},
    {"customer_id": "CUST03", "name": "Hyperion Electric Vehicles", "tier": "gold", "region": "North America"},
    {"customer_id": "CUST04", "name": "OmniVision Medical Systems", "tier": "silver", "region": "Europe"},
    {"customer_id": "CUST05", "name": "Pacific Automation Group", "tier": "silver", "region": "Asia-Pacific"},
    {"customer_id": "CUST06", "name": "Solaria Smart Energy", "tier": "silver", "region": "North America"},
    {"customer_id": "CUST07", "name": "Beacon Industrial IoT", "tier": "bronze", "region": "Europe"},
    {"customer_id": "CUST08", "name": "Vanguard Precision Instruments", "tier": "bronze", "region": "Asia-Pacific"},
]

REFERENCE_DATE = datetime.date(2026, 10, 16)
NUM_ORDERS = 600

# Targeted days of cover for the 7 SKUs where SUP01 is primary
KEY_SKU_TARGET_DAYS_OF_COVER = {
    "SKU001": 6.0,
    "SKU002": 10.0,
    "SKU003": 14.0,
    "SKU004": 18.0,
    "SKU005": 22.0,
    "SKU006": 36.0,
    "SKU007": 45.0,
}


def generate_all(
    seed: int | None = None,
    base_date: datetime.date | None = None,
) -> dict[str, pd.DataFrame]:
    """Generate all synthetic supply chain tables as pandas DataFrames.

    Fully deterministic from the provided or configured seed.

    Returns:
        Dictionary mapping table name to pandas DataFrame:
        - suppliers (15 rows)
        - skus (20 rows)
        - supplier_skus
        - warehouses (4 rows)
        - inventory (80 rows: 4 warehouses x 20 SKUs)
        - carriers (3 rows)
        - customers (8 rows)
        - orders (600 rows spread over the last 90 days)
    """
    if seed is None:
        seed = get_settings().random_seed

    if base_date is None:
        base_date = REFERENCE_DATE

    rng = np.random.default_rng(seed)

    # 1. Base catalogs
    df_suppliers = pd.DataFrame(SUPPLIER_CATALOG)
    df_skus = pd.DataFrame(SKU_CATALOG)
    df_warehouses = pd.DataFrame(WAREHOUSE_CATALOG)
    df_carriers = pd.DataFrame(CARRIER_CATALOG)
    df_customers = pd.DataFrame(CUSTOMER_CATALOG)

    # 2. Generate Orders
    # Requirements: About 600 orders spread over the last 90 days.
    # Tier weighting: gold = 3, silver = 2, bronze = 1, with ~15% bumped by one level (max 3).
    tier_weights = {"gold": 0.50 / 3, "silver": 0.35 / 3, "bronze": 0.15 / 2}
    cust_weights = [tier_weights[c["tier"]] for c in CUSTOMER_CATALOG]
    cust_ids = [c["customer_id"] for c in CUSTOMER_CATALOG]
    cust_tiers = {c["customer_id"]: c["tier"] for c in CUSTOMER_CATALOG}
    tier_base_priority = {"gold": 3, "silver": 2, "bronze": 1}

    all_sku_ids = [s["sku_id"] for s in SKU_CATALOG]
    sku_costs = {s["sku_id"]: s["unit_cost"] for s in SKU_CATALOG}

    order_rows: list[dict[str, Any]] = []
    sku_total_ordered: dict[str, int] = {sku_id: 0 for sku_id in all_sku_ids}

    for i in range(NUM_ORDERS):
        order_id = f"ORD{i + 1:04d}"
        cust_id = str(rng.choice(cust_ids, p=cust_weights))
        sku_id = str(rng.choice(all_sku_ids))
        cost = sku_costs[sku_id]

        if cost > 100:
            qty = int(rng.integers(5, 40))
        elif cost > 25:
            qty = int(rng.integers(20, 160))
        else:
            qty = int(rng.integers(50, 500))

        sku_total_ordered[sku_id] += qty

        days_ago = int(rng.integers(0, 90))
        order_date = base_date - datetime.timedelta(days=days_ago)
        lead_days = int(rng.integers(7, 30))
        due_date = order_date + datetime.timedelta(days=lead_days)

        # Priority tied to customer tier: gold=3, silver=2, bronze=1
        base_prio = tier_base_priority[cust_tiers[cust_id]]
        # ~15% of orders bumped up by one level (max 3)
        if float(rng.uniform(0, 1)) < 0.15:
            priority = min(3, base_prio + 1)
        else:
            priority = base_prio

        # Orders due in the past (before yesterday) are fulfilled
        # Overdue orders (due yesterday) and future orders remain open
        if due_date < base_date - datetime.timedelta(days=1):
            status = "fulfilled"
        else:
            status = "open"

        order_rows.append(
            {
                "order_id": order_id,
                "customer_id": cust_id,
                "sku_id": sku_id,
                "quantity": qty,
                "order_date": order_date,
                "due_date": due_date,
                "priority": priority,
                "status": status,
            }
        )

    # Sort orders chronologically
    df_orders = (
        pd.DataFrame(order_rows)
        .sort_values(by=["order_date", "order_id"])
        .reset_index(drop=True)
    )

    # 3. Calculate Demand per SKU
    # Avg daily demand = total ordered quantity in the data / 90
    sku_daily_demand = {
        sku_id: sku_total_ordered[sku_id] / 90.0 for sku_id in all_sku_ids
    }
    # Monthly demand = total ordered quantity / 3
    sku_monthly_demand = {
        sku_id: sku_total_ordered[sku_id] / 3.0 for sku_id in all_sku_ids
    }

    # 4. Generate Supplier SKUs
    # Exactly ONE supplier ("SUP01") has is_key_supplier=True and is primary for 7 SKUs (SKU001..SKU007)
    key_supplier_id = "SUP01"
    key_supplier_lead_time = next(
        s["lead_time_days"] for s in SUPPLIER_CATALOG if s["supplier_id"] == key_supplier_id
    )

    key_sku_ids = [s["sku_id"] for s in SKU_CATALOG[:7]]
    other_sku_ids = [s["sku_id"] for s in SKU_CATALOG[7:]]
    other_supplier_ids = [
        s["supplier_id"] for s in SUPPLIER_CATALOG if s["supplier_id"] != key_supplier_id
    ]
    supplier_base_lead_times = {s["supplier_id"]: s["lead_time_days"] for s in SUPPLIER_CATALOG}

    supplier_sku_rows: list[dict[str, Any]] = []

    # Map key SKUs (SUP01 + alternatives)
    for sku_id in key_sku_ids:
        unit_cost = sku_costs[sku_id]
        m_dem = sku_monthly_demand[sku_id]

        # Primary entry from SUP01: covers demand fully with buffer (e.g. 130-160%)
        sup01_cap = max(100, int(round(m_dem * float(rng.uniform(1.30, 1.60)))))
        supplier_sku_rows.append(
            {
                "supplier_id": key_supplier_id,
                "sku_id": sku_id,
                "unit_price": round(float(unit_cost), 2),
                "lead_time_days": int(key_supplier_lead_time),
                "monthly_capacity": sup01_cap,
                "is_primary": True,
            }
        )

        # At least 2 alternatives (choose 2 or 3 alternatives)
        num_alternatives = int(rng.choice([2, 3]))
        chosen_alternatives = rng.choice(other_supplier_ids, size=num_alternatives, replace=False)

        for alt_sup_id in chosen_alternatives:
            price_multiplier = float(rng.uniform(1.15, 1.35))
            lead_time_add = int(rng.integers(5, 16))

            # Set each alternative's monthly_capacity to 25 to 50 percent of that SKU's monthly demand
            # so no single alternative can cover everything
            alt_capacity = max(1, int(round(m_dem * float(rng.uniform(0.25, 0.50)))))

            supplier_sku_rows.append(
                {
                    "supplier_id": str(alt_sup_id),
                    "sku_id": sku_id,
                    "unit_price": round(unit_cost * price_multiplier, 2),
                    "lead_time_days": key_supplier_lead_time + lead_time_add,
                    "monthly_capacity": alt_capacity,
                    "is_primary": False,
                }
            )

    # Map remaining SKUs: each has 1 to 3 suppliers from other_supplier_ids
    for sku_id in other_sku_ids:
        unit_cost = sku_costs[sku_id]
        m_dem = sku_monthly_demand[sku_id]
        num_suppliers = int(rng.integers(1, 4))  # 1, 2, or 3
        chosen_sups = rng.choice(other_supplier_ids, size=num_suppliers, replace=False)

        for i, sup_id in enumerate(chosen_sups):
            is_primary = (i == 0)
            base_lead = supplier_base_lead_times[str(sup_id)]
            if is_primary:
                unit_price = round(unit_cost * float(rng.uniform(0.95, 1.05)), 2)
                lead_time = max(3, base_lead + int(rng.integers(-2, 3)))
                capacity = max(100, int(round(m_dem * float(rng.uniform(1.15, 1.50)))))
            else:
                unit_price = round(unit_cost * float(rng.uniform(1.08, 1.25)), 2)
                lead_time = base_lead + int(rng.integers(3, 10))
                capacity = max(50, int(round(m_dem * float(rng.uniform(0.30, 0.70)))))

            supplier_sku_rows.append(
                {
                    "supplier_id": str(sup_id),
                    "sku_id": sku_id,
                    "unit_price": unit_price,
                    "lead_time_days": lead_time,
                    "monthly_capacity": capacity,
                    "is_primary": is_primary,
                }
            )

    df_supplier_skus = pd.DataFrame(supplier_sku_rows)

    # 5. Generate Inventory
    # Requirements:
    # 7 key SKUs: days of cover differ per SKU (SKU001 ~6, SKU002 ~10, SKU003 ~14,
    # SKU004 ~18, SKU005 ~22, SKU006 ~30, SKU007 ~45).
    # Stock split unevenly across the 4 warehouses (50/25/15/10 percent, shuffled per SKU).
    # All other SKUs: 40 to 90 days of cover.
    # Safety stock = about 7 days of demand, reorder_point = about 14 days.
    inventory_rows: list[dict[str, Any]] = []

    for sku in SKU_CATALOG:
        sku_id = sku["sku_id"]
        d_dem = sku_daily_demand[sku_id]

        if sku_id in KEY_SKU_TARGET_DAYS_OF_COVER:
            target_days = KEY_SKU_TARGET_DAYS_OF_COVER[sku_id]
        else:
            target_days = float(rng.uniform(45.0, 85.0))

        # Total on-hand across all warehouses
        total_on_hand = max(4, int(round(target_days * d_dem)))
        total_safety = max(4, int(round(7.0 * d_dem)))
        total_reorder = max(total_safety + 4, int(round(14.0 * d_dem)))

        # Split unevenly across the 4 warehouses
        wh_ratios = list(rng.permutation([0.50, 0.25, 0.15, 0.10]))

        # Distribute on_hand, safety_stock, and reorder_point
        on_hand_splits = [int(round(total_on_hand * r)) for r in wh_ratios[:3]]
        on_hand_splits.append(max(0, total_on_hand - sum(on_hand_splits)))

        safety_splits = [max(1, int(round(total_safety * r))) for r in wh_ratios[:3]]
        safety_splits.append(max(1, total_safety - sum(safety_splits)))

        reorder_splits = [
            max(safety_splits[k] + 1, int(round(total_reorder * wh_ratios[k])))
            for k in range(3)
        ]
        reorder_splits.append(
            max(safety_splits[3] + 1, total_reorder - sum(reorder_splits))
        )

        for w_idx, wh in enumerate(WAREHOUSE_CATALOG):
            inventory_rows.append(
                {
                    "warehouse_id": wh["warehouse_id"],
                    "sku_id": sku_id,
                    "on_hand": on_hand_splits[w_idx],
                    "safety_stock": safety_splits[w_idx],
                    "reorder_point": reorder_splits[w_idx],
                }
            )

    df_inventory = pd.DataFrame(inventory_rows)

    return {
        "suppliers": df_suppliers,
        "skus": df_skus,
        "supplier_skus": df_supplier_skus,
        "warehouses": df_warehouses,
        "inventory": df_inventory,
        "carriers": df_carriers,
        "customers": df_customers,
        "orders": df_orders,
    }
