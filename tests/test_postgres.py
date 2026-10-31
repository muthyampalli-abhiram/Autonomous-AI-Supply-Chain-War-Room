"""Integration tests verifying full system execution on PostgreSQL when available."""

from __future__ import annotations

import os
from typing import Any
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from warroom.data_gen.generator import generate_all
from warroom.data_gen.loader import load_to_db
from warroom.db.models import (
    Base,
    Carrier,
    Customer,
    Inventory,
    Order,
    SKU,
    Supplier,
    SupplierSKU,
    Warehouse,
)
from warroom.db.session import init_db
from warroom.graph.detection import restore_supplier, simulate_supplier_outage
from warroom.orchestrator.graph import build_warroom_graph
from warroom.orchestrator.state import create_initial_state

EXPECTED_ROW_COUNTS = {
    "suppliers": 15,
    "skus": 20,
    "supplier_skus": 51,
    "warehouses": 4,
    "inventory": 80,
    "carriers": 3,
    "customers": 8,
    "orders": 600,
}


def _get_postgres_engine():
    """Retrieve and validate PostgreSQL connection from POSTGRES_TEST_URL, skipping if not available."""
    pg_url = os.getenv("POSTGRES_TEST_URL")
    if not pg_url:
        pytest.skip(
            "POSTGRES_TEST_URL environment variable is not set (skipping PostgreSQL tests)"
        )
    try:
        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1;"))
        return engine
    except Exception as exc:
        pytest.skip(
            f"PostgreSQL server unreachable at '{pg_url}': {exc} (skipping PostgreSQL tests)"
        )


@pytest.mark.postgres
def test_postgres_table_counts_and_outage_parity():
    """Verify PostgreSQL table creation, row counts, and LangGraph headline parity vs SQLite."""
    pg_engine = _get_postgres_engine()

    # 1. Initialize schema and populate data in separate Postgres database/schema
    init_db(engine=pg_engine, drop=True)
    dfs = generate_all(seed=42)
    load_to_db(dfs, engine=pg_engine)

    try:
        with Session(pg_engine) as pg_session:
            # 2. Verify exact row counts in PostgreSQL
            assert pg_session.scalar(select(func.count()).select_from(Supplier)) == EXPECTED_ROW_COUNTS["suppliers"]
            assert pg_session.scalar(select(func.count()).select_from(SKU)) == EXPECTED_ROW_COUNTS["skus"]
            assert pg_session.scalar(select(func.count()).select_from(SupplierSKU)) == EXPECTED_ROW_COUNTS["supplier_skus"]
            assert pg_session.scalar(select(func.count()).select_from(Warehouse)) == EXPECTED_ROW_COUNTS["warehouses"]
            assert pg_session.scalar(select(func.count()).select_from(Inventory)) == EXPECTED_ROW_COUNTS["inventory"]
            assert pg_session.scalar(select(func.count()).select_from(Carrier)) == EXPECTED_ROW_COUNTS["carriers"]
            assert pg_session.scalar(select(func.count()).select_from(Customer)) == EXPECTED_ROW_COUNTS["customers"]
            assert pg_session.scalar(select(func.count()).select_from(Order)) == EXPECTED_ROW_COUNTS["orders"]

            # 3. Execute SUP01 outage pipeline on PostgreSQL
            simulate_supplier_outage(pg_session, "SUP01")
            pg_graph = build_warroom_graph(pg_session)
            pg_result = pg_graph.invoke(create_initial_state())

            # 4. Execute reference SQLite pipeline
            sqlite_engine = create_engine("sqlite:///:memory:")
            init_db(engine=sqlite_engine, drop=True)
            load_to_db(generate_all(seed=42), engine=sqlite_engine)

            with Session(sqlite_engine) as sqlite_session:
                simulate_supplier_outage(sqlite_session, "SUP01")
                sqlite_graph = build_warroom_graph(sqlite_session)
                sqlite_result = sqlite_graph.invoke(create_initial_state())

            # 5. Assert parity: same recommended supplier per SKU and identical net_financial_exposure
            pg_sup = pg_result["supplier_result"]["data"]["per_sku"]
            sql_sup = sqlite_result["supplier_result"]["data"]["per_sku"]

            for sku_id, pg_info in pg_sup.items():
                sql_info = sql_sup[sku_id]
                assert pg_info["recommended"]["supplier_id"] == sql_info["recommended"]["supplier_id"], (
                    f"Recommended supplier mismatch for {sku_id}: PG={pg_info['recommended']['supplier_id']} "
                    f"vs SQLite={sql_info['recommended']['supplier_id']}"
                )

            pg_fin = pg_result["customer_impact_result"]["data"]["financials"]
            sql_fin = sqlite_result["customer_impact_result"]["data"]["financials"]

            assert pg_fin["net_financial_exposure"] == sql_fin["net_financial_exposure"], (
                f"Net financial exposure mismatch: PG={pg_fin['net_financial_exposure']} "
                f"vs SQLite={sql_fin['net_financial_exposure']}"
            )
            assert pg_fin["revenue_delayed"] == sql_fin["revenue_delayed"]
            assert pg_fin["sla_penalty_total"] == sql_fin["sla_penalty_total"]

            # 6. Restore supplier and assert Postgres database is unchanged
            restore_supplier(pg_session, "SUP01")

            disrupted = pg_session.scalars(
                select(Supplier).where(func.lower(Supplier.status) != "active")
            ).all()
            assert len(disrupted) == 0, f"Expected 0 disrupted suppliers after restore, found: {disrupted}"

            # Verify row counts unchanged across all tables
            assert pg_session.scalar(select(func.count()).select_from(Supplier)) == EXPECTED_ROW_COUNTS["suppliers"]
            assert pg_session.scalar(select(func.count()).select_from(SKU)) == EXPECTED_ROW_COUNTS["skus"]
            assert pg_session.scalar(select(func.count()).select_from(SupplierSKU)) == EXPECTED_ROW_COUNTS["supplier_skus"]
            assert pg_session.scalar(select(func.count()).select_from(Warehouse)) == EXPECTED_ROW_COUNTS["warehouses"]
            assert pg_session.scalar(select(func.count()).select_from(Inventory)) == EXPECTED_ROW_COUNTS["inventory"]
            assert pg_session.scalar(select(func.count()).select_from(Carrier)) == EXPECTED_ROW_COUNTS["carriers"]
            assert pg_session.scalar(select(func.count()).select_from(Customer)) == EXPECTED_ROW_COUNTS["customers"]
            assert pg_session.scalar(select(func.count()).select_from(Order)) == EXPECTED_ROW_COUNTS["orders"]

    finally:
        # Drop tables in test Postgres instance to keep environment clean
        try:
            Base.metadata.drop_all(pg_engine)
        except Exception:
            pass
        pg_engine.dispose()
