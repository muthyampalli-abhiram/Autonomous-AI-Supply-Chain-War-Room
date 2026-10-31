"""Graph analysis and supply chain disruption impact evaluation."""

from __future__ import annotations

from typing import Any
import networkx as nx
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from warroom.db.models import Order


def avg_daily_demand(session: Session, sku_id: str) -> float:
    """Compute average daily demand for a SKU over the 90-day observation window.

    avg_daily_demand = total ordered quantity in the data / 90.
    """
    total_qty = session.scalar(
        select(func.sum(Order.quantity)).where(Order.sku_id == sku_id)
    )
    if total_qty is None:
        return 0.0
    return float(total_qty) / 90.0


def impact_of_supplier_failure(
    G: nx.DiGraph,
    session: Session,
    supplier_id: str,
) -> dict[str, Any]:
    """Calculate the comprehensive impact of a supplier failure using the supply graph.

    Returns a dict containing:
      - affected_skus: SKUs where this supplier is primary
      - sole_source_skus: affected SKUs with NO other active supplier
      - alternatives: {sku_id: list of other active suppliers with price, lead_time}
      - days_of_cover: {sku_id: total on_hand across warehouses / avg_daily_demand}
      - supply_gap_days: {sku_id: shortest alternative lead time - days_of_cover,
                          floored at 0, or None if sole-sourced}
      - exposed_customers: customers with open orders on affected SKUs, with
                           quantity and max_priority
      - exposed_open_orders: count and total quantity
    """
    if supplier_id not in G:
        raise ValueError(f"Supplier '{supplier_id}' not found in supply graph")

    # 1. Affected SKUs where this supplier is the primary supplier
    affected_skus: list[str] = [
        v
        for _, v, d in G.out_edges(supplier_id, data=True)
        if d.get("relation") == "supplies" and d.get("is_primary") is True
    ]
    affected_skus.sort()

    # 2. Alternatives and sole source identification
    sole_source_skus: list[str] = []
    alternatives: dict[str, list[dict[str, Any]]] = {}

    for sku_id in affected_skus:
        alts: list[dict[str, Any]] = []
        for u, _, d in G.in_edges(sku_id, data=True):
            if (
                d.get("relation") == "supplies"
                and u != supplier_id
                and d.get("active", True) is True
            ):
                alts.append(
                    {
                        "supplier_id": u,
                        "supplier": u,
                        "name": G.nodes[u].get("name", u),
                        "unit_price": d.get("unit_price"),
                        "price": d.get("unit_price"),
                        "lead_time_days": d.get("lead_time_days"),
                        "lead_time": d.get("lead_time_days"),
                        "monthly_capacity": d.get("monthly_capacity"),
                    }
                )
        alternatives[sku_id] = alts
        if not alts:
            sole_source_skus.append(sku_id)

    # 3. Days of cover per SKU
    days_of_cover: dict[str, float] = {}
    for sku_id in affected_skus:
        total_on_hand = sum(
            d.get("on_hand", 0)
            for _, _, d in G.out_edges(sku_id, data=True)
            if d.get("relation") == "stocked_at"
        )
        daily_demand = avg_daily_demand(session, sku_id)
        if daily_demand > 0:
            days_of_cover[sku_id] = round(total_on_hand / daily_demand, 2)
        else:
            days_of_cover[sku_id] = 0.0

    # 4. Supply gap in days
    # Shortest alternative lead time - days_of_cover, floored at 0, or None if sole-sourced
    supply_gap_days: dict[str, float | None] = {}
    for sku_id in affected_skus:
        if sku_id in sole_source_skus or not alternatives[sku_id]:
            supply_gap_days[sku_id] = None
        else:
            min_lead_time = min(a["lead_time_days"] for a in alternatives[sku_id])
            gap = min_lead_time - days_of_cover[sku_id]
            supply_gap_days[sku_id] = max(0.0, round(gap, 2))

    # 5. Exposed customers and exposed open orders
    exposed_customers: dict[str, dict[str, Any]] = {}
    total_open_orders_count = 0
    total_open_orders_quantity = 0

    for sku_id in affected_skus:
        for _, cust_id, d in G.out_edges(sku_id, data=True):
            if d.get("relation") == "ordered_by":
                order_cnt = d.get("open_order_count", 0)
                qty = d.get("open_quantity", 0)
                prio = d.get("max_priority", 1)

                total_open_orders_count += order_cnt
                total_open_orders_quantity += qty

                if cust_id not in exposed_customers:
                    cust_name = G.nodes.get(cust_id, {}).get("name", cust_id)
                    exposed_customers[cust_id] = {
                        "customer_id": cust_id,
                        "name": cust_name,
                        "quantity": qty,
                        "max_priority": prio,
                    }
                else:
                    exposed_customers[cust_id]["quantity"] += qty
                    exposed_customers[cust_id]["max_priority"] = max(
                        exposed_customers[cust_id]["max_priority"], prio
                    )

    exposed_open_orders = {
        "count": total_open_orders_count,
        "total_quantity": total_open_orders_quantity,
        "quantity": total_open_orders_quantity,
    }

    return {
        "affected_skus": affected_skus,
        "sole_source_skus": sole_source_skus,
        "alternatives": alternatives,
        "days_of_cover": days_of_cover,
        "supply_gap_days": supply_gap_days,
        "exposed_customers": exposed_customers,
        "exposed_open_orders": exposed_open_orders,
    }


def single_point_of_failure_report(G: nx.DiGraph) -> pd.DataFrame:
    """Generate a single point of failure (SPOF) report ranking suppliers.

    Suppliers are ranked by number of SKUs they are the only active source for,
    then by primary-SKU count.
    """
    supplier_nodes = [
        n for n, d in G.nodes(data=True) if d.get("node_type") == "supplier"
    ]
    sku_nodes = [
        n for n, d in G.nodes(data=True) if d.get("node_type") == "sku"
    ]

    # Map each SKU to its currently active suppliers
    sku_active_suppliers: dict[str, list[str]] = {}
    for sku_id in sku_nodes:
        active_sups = [
            u
            for u, _, d in G.in_edges(sku_id, data=True)
            if d.get("relation") == "supplies" and d.get("active", True) is True
        ]
        sku_active_suppliers[sku_id] = active_sups

    rows: list[dict[str, Any]] = []
    for sup_id in supplier_nodes:
        node_data = G.nodes[sup_id]

        # SKUs where this supplier is the sole active source
        sole_source_skus = [
            sku_id
            for sku_id, sups in sku_active_suppliers.items()
            if sups == [sup_id]
        ]

        # SKUs where this supplier is marked as primary
        primary_skus = [
            v
            for _, v, d in G.out_edges(sup_id, data=True)
            if d.get("relation") == "supplies" and d.get("is_primary") is True
        ]

        rows.append(
            {
                "supplier_id": sup_id,
                "name": node_data.get("name", sup_id),
                "sole_source_sku_count": len(sole_source_skus),
                "primary_sku_count": len(primary_skus),
                "status": node_data.get("status", "active"),
                "is_key_supplier": node_data.get("is_key_supplier", False),
                "country": node_data.get("country", ""),
            }
        )

    df_report = pd.DataFrame(rows)
    if not df_report.empty:
        df_report = df_report.sort_values(
            by=["sole_source_sku_count", "primary_sku_count", "supplier_id"],
            ascending=[False, False, True],
        ).reset_index(drop=True)

    return df_report
