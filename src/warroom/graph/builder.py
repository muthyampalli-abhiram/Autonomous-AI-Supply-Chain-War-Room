"""Supply chain graph builder using NetworkX and SQLAlchemy session."""

from __future__ import annotations

import networkx as nx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from warroom.db.models import (
    Customer,
    Inventory,
    Order,
    SKU,
    Supplier,
    SupplierSKU,
    Warehouse,
)


def build_supply_graph(session: Session) -> nx.DiGraph:
    """Construct a directed NetworkX supply graph from the database.

    Nodes:
      - supplier (status, reliability_score, is_key_supplier, name, country, lead_time_days)
      - sku (name, category, unit_cost, unit_price)
      - warehouse (name, city, country, capacity)
      - customer (name, tier, region)

    Edges:
      - supplier -> sku: relation="supplies" (unit_price, lead_time_days, monthly_capacity,
        is_primary, active=bool)
      - sku -> warehouse: relation="stocked_at" (on_hand, safety_stock, reorder_point)
      - sku -> customer: relation="ordered_by" (open_order_count, open_quantity,
        earliest_due_date, max_priority) built from open orders only

    Edges from suppliers whose status is not "active" are marked active=False.
    """
    G = nx.DiGraph()

    # 1. Add Supplier nodes
    suppliers = session.scalars(select(Supplier)).all()
    supplier_status_map: dict[str, str] = {}
    for sup in suppliers:
        supplier_status_map[sup.supplier_id] = sup.status
        G.add_node(
            sup.supplier_id,
            node_type="supplier",
            name=sup.name,
            country=sup.country,
            reliability_score=sup.reliability_score,
            lead_time_days=sup.lead_time_days,
            status=sup.status,
            is_key_supplier=sup.is_key_supplier,
        )

    # 2. Add SKU nodes
    skus = session.scalars(select(SKU)).all()
    for sku in skus:
        G.add_node(
            sku.sku_id,
            node_type="sku",
            name=sku.name,
            category=sku.category,
            unit_cost=sku.unit_cost,
            unit_price=sku.unit_price,
        )

    # 3. Add Warehouse nodes
    warehouses = session.scalars(select(Warehouse)).all()
    for wh in warehouses:
        G.add_node(
            wh.warehouse_id,
            node_type="warehouse",
            name=wh.name,
            city=wh.city,
            country=wh.country,
            capacity=wh.capacity,
        )

    # 4. Add Customer nodes
    customers = session.scalars(select(Customer)).all()
    for cust in customers:
        G.add_node(
            cust.customer_id,
            node_type="customer",
            name=cust.name,
            tier=cust.tier,
            region=cust.region,
        )

    # 5. Add supplier -> sku edges
    supplier_skus = session.scalars(select(SupplierSKU)).all()
    for ss in supplier_skus:
        sup_status = supplier_status_map.get(ss.supplier_id, "active")
        is_active = (sup_status == "active")
        G.add_edge(
            ss.supplier_id,
            ss.sku_id,
            relation="supplies",
            unit_price=ss.unit_price,
            lead_time_days=ss.lead_time_days,
            monthly_capacity=ss.monthly_capacity,
            is_primary=ss.is_primary,
            active=is_active,
        )

    # 6. Add sku -> warehouse edges
    inventory_items = session.scalars(select(Inventory)).all()
    for inv in inventory_items:
        G.add_edge(
            inv.sku_id,
            inv.warehouse_id,
            relation="stocked_at",
            on_hand=inv.on_hand,
            safety_stock=inv.safety_stock,
            reorder_point=inv.reorder_point,
        )

    # 7. Add sku -> customer edges (built from open orders only)
    open_orders_query = (
        select(
            Order.sku_id,
            Order.customer_id,
            func.count(Order.order_id).label("open_order_count"),
            func.sum(Order.quantity).label("open_quantity"),
            func.min(Order.due_date).label("earliest_due_date"),
            func.max(Order.priority).label("max_priority"),
        )
        .where(func.lower(Order.status) == "open")
        .group_by(Order.sku_id, Order.customer_id)
    )
    open_order_aggregates = session.execute(open_orders_query).all()

    for row in open_order_aggregates:
        G.add_edge(
            row.sku_id,
            row.customer_id,
            relation="ordered_by",
            open_order_count=int(row.open_order_count),
            open_quantity=int(row.open_quantity),
            earliest_due_date=row.earliest_due_date,
            max_priority=int(row.max_priority),
        )

    return G
