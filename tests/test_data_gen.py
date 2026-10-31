"""Unit and integration tests for data generation and database loading."""

from __future__ import annotations

import datetime
from pathlib import Path
import pandas as pd
from pandas.testing import assert_frame_equal
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from warroom.data_gen.generator import (
    NUM_ORDERS,
    REFERENCE_DATE,
    generate_all,
)
from warroom.data_gen.loader import load_to_db, save_csvs
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


@pytest.fixture
def sample_dfs() -> dict[str, pd.DataFrame]:
    """Fixture returning generated dataframes with fixed seed 42."""
    return generate_all(seed=42)


@pytest.fixture
def memory_engine():
    """Fixture providing a fresh in-memory SQLite database with foreign keys enabled."""
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    init_db(engine=engine, drop=True)
    return engine


def test_seed_determinism():
    """Verify same seed produces identical data twice and different seeds differ."""
    dfs_a = generate_all(seed=42)
    dfs_b = generate_all(seed=42)

    for table_name in dfs_a:
        assert_frame_equal(
            dfs_a[table_name],
            dfs_b[table_name],
            check_exact=True,
            obj=f"Table {table_name}",
        )

    # Different seed should produce variation
    dfs_c = generate_all(seed=999)
    assert not dfs_a["orders"].equals(dfs_c["orders"])
    assert not dfs_a["inventory"].equals(dfs_c["inventory"])


def test_row_counts_match_specification(sample_dfs):
    """Verify row counts match specification requirements."""
    # 15 suppliers, 20 SKUs, 4 warehouses, 3 carriers, 8 customers, about 600 orders
    assert len(sample_dfs["suppliers"]) == 15
    assert len(sample_dfs["skus"]) == 20
    assert len(sample_dfs["warehouses"]) == 4
    assert len(sample_dfs["carriers"]) == 3
    assert len(sample_dfs["customers"]) == 8
    assert len(sample_dfs["orders"]) == 600
    assert len(sample_dfs["inventory"]) == 80  # 4 warehouses x 20 SKUs


def test_orders_spread_over_last_90_days(sample_dfs):
    """Verify orders are spread over the last 90 days relative to reference date."""
    df_orders = sample_dfs["orders"]
    min_date = REFERENCE_DATE - datetime.timedelta(days=90)

    for _, row in df_orders.iterrows():
        order_date = row["order_date"]
        due_date = row["due_date"]
        assert min_date <= order_date <= REFERENCE_DATE
        assert due_date >= order_date
        assert row["priority"] in (1, 2, 3)
        assert row["status"] in ("open", "fulfilled")


def test_foreign_key_integrity(sample_dfs):
    """Verify every foreign key resolves without orphan rows."""
    supplier_ids = set(sample_dfs["suppliers"]["supplier_id"])
    sku_ids = set(sample_dfs["skus"]["sku_id"])
    warehouse_ids = set(sample_dfs["warehouses"]["warehouse_id"])
    customer_ids = set(sample_dfs["customers"]["customer_id"])

    # 1. supplier_skus -> suppliers & skus
    df_supp_skus = sample_dfs["supplier_skus"]
    assert set(df_supp_skus["supplier_id"]).issubset(supplier_ids)
    assert set(df_supp_skus["sku_id"]).issubset(sku_ids)

    # Check composite PK uniqueness
    assert not df_supp_skus.duplicated(subset=["supplier_id", "sku_id"]).any()

    # 2. inventory -> warehouses & skus
    df_inv = sample_dfs["inventory"]
    assert set(df_inv["warehouse_id"]).issubset(warehouse_ids)
    assert set(df_inv["sku_id"]).issubset(sku_ids)
    assert not df_inv.duplicated(subset=["warehouse_id", "sku_id"]).any()

    # Check complete cross-product
    expected_pairs = {(w, s) for w in warehouse_ids for s in sku_ids}
    actual_pairs = set(zip(df_inv["warehouse_id"], df_inv["sku_id"]))
    assert actual_pairs == expected_pairs

    # 3. orders -> customers & skus
    df_orders = sample_dfs["orders"]
    assert set(df_orders["customer_id"]).issubset(customer_ids)
    assert set(df_orders["sku_id"]).issubset(sku_ids)
    assert not df_orders.duplicated(subset=["order_id"]).any()


def test_key_supplier_rules(sample_dfs):
    """Verify exactly ONE key supplier (SUP01) is primary for 6-8 SKUs with >=2 alternatives."""
    df_suppliers = sample_dfs["suppliers"]
    df_supp_skus = sample_dfs["supplier_skus"]

    key_suppliers = df_suppliers[df_suppliers["is_key_supplier"] == True]
    assert len(key_suppliers) == 1
    key_sup_id = key_suppliers.iloc[0]["supplier_id"]
    assert key_sup_id == "SUP01"

    # Find SKUs where SUP01 is the primary supplier
    sup01_primary_skus = df_supp_skus[
        (df_supp_skus["supplier_id"] == "SUP01") & (df_supp_skus["is_primary"] == True)
    ]
    assert 6 <= len(sup01_primary_skus) <= 8

    # Each of SUP01's SKUs must have at least 2 alternative suppliers
    for _, primary_row in sup01_primary_skus.iterrows():
        sku_id = primary_row["sku_id"]
        primary_price = primary_row["unit_price"]
        primary_lead = primary_row["lead_time_days"]

        alts = df_supp_skus[
            (df_supp_skus["sku_id"] == sku_id) & (df_supp_skus["supplier_id"] != "SUP01")
        ]
        assert len(alts) >= 2, f"SKU {sku_id} has fewer than 2 alternatives"

        # Each alternative must have higher price or longer lead time
        for _, alt in alts.iterrows():
            assert (
                alt["unit_price"] > primary_price or alt["lead_time_days"] > primary_lead
            ), f"Alternative {alt['supplier_id']} for {sku_id} does not have higher price or longer lead time"

    # Every other SKU has 1 to 3 suppliers
    key_sku_set = set(sup01_primary_skus["sku_id"])
    all_skus = set(sample_dfs["skus"]["sku_id"])
    other_skus = all_skus - key_sku_set

    for sku_id in other_skus:
        sku_sups = df_supp_skus[df_supp_skus["sku_id"] == sku_id]
        assert 1 <= len(sku_sups) <= 3, f"Non-key SKU {sku_id} has {len(sku_sups)} suppliers"
        # Exactly one primary
        assert sku_sups["is_primary"].sum() == 1
        # SUP01 should not supply non-key SKUs
        assert "SUP01" not in set(sku_sups["supplier_id"])


def test_realistic_names_and_countries(sample_dfs):
    """Verify entities use realistic names and countries, not generic placeholders."""
    df_suppliers = sample_dfs["suppliers"]
    for _, sup in df_suppliers.iterrows():
        assert not sup["name"].startswith("Supplier ")
        assert len(sup["country"]) > 2
        assert 0.0 <= sup["reliability_score"] <= 1.0

    df_warehouses = sample_dfs["warehouses"]
    for _, wh in df_warehouses.iterrows():
        assert not wh["name"].startswith("Warehouse ")
        assert len(wh["city"]) > 2

    df_customers = sample_dfs["customers"]
    for _, cust in df_customers.iterrows():
        assert not cust["name"].startswith("Customer ")
        assert cust["tier"] in ("gold", "silver", "bronze")

    df_carriers = sample_dfs["carriers"]
    assert set(df_carriers["mode"]) == {"air", "sea", "road"}


def test_save_csvs_and_readback(sample_dfs, tmp_path: Path):
    """Verify save_csvs writes one valid CSV file per table."""
    saved_files = save_csvs(sample_dfs, output_dir=tmp_path)
    assert len(saved_files) == len(sample_dfs)

    for p in saved_files:
        assert p.exists()
        table_name = p.stem
        df_read = pd.read_csv(p)
        assert len(df_read) == len(sample_dfs[table_name])


def test_database_load_and_orm_navigation(sample_dfs, memory_engine):
    """Verify load_to_db inserts all records and ORM models/relationships query properly."""
    load_to_db(sample_dfs, engine=memory_engine)

    with Session(memory_engine) as session:
        # Check row counts
        assert session.scalar(select(func.count()).select_from(Supplier)) == 15
        assert session.scalar(select(func.count()).select_from(SKU)) == 20
        assert session.scalar(select(func.count()).select_from(Warehouse)) == 4
        assert session.scalar(select(func.count()).select_from(Carrier)) == 3
        assert session.scalar(select(func.count()).select_from(Customer)) == 8
        assert session.scalar(select(func.count()).select_from(Inventory)) == 80
        assert session.scalar(select(func.count()).select_from(Order)) == 600

        # Check ORM relationships
        sup01 = session.get(Supplier, "SUP01")
        assert sup01 is not None
        assert sup01.is_key_supplier is True
        assert len(sup01.supplier_skus) >= 6

        # Check Order -> Customer and Order -> SKU relationship
        first_order = session.scalar(select(Order).limit(1))
        assert first_order is not None
        assert first_order.customer is not None
        assert first_order.customer.customer_id == first_order.customer_id
        assert first_order.sku is not None
        assert first_order.sku.sku_id == first_order.sku_id

        # Check Warehouse -> Inventory relationship
        wh01 = session.get(Warehouse, "WH01")
        assert wh01 is not None
        assert len(wh01.inventory_items) == 20


def test_days_of_cover_range(sample_dfs):
    """Verify SKU001 days of cover is less than 10 and SKU007 is greater than 40."""
    df_orders = sample_dfs["orders"]
    df_inv = sample_dfs["inventory"]

    # SKU001
    ord_qty_001 = df_orders[df_orders["sku_id"] == "SKU001"]["quantity"].sum()
    daily_dem_001 = ord_qty_001 / 90.0
    on_hand_001 = df_inv[df_inv["sku_id"] == "SKU001"]["on_hand"].sum()
    doc_001 = on_hand_001 / daily_dem_001
    assert doc_001 < 10.0, f"Expected SKU001 days of cover < 10, got {doc_001}"

    # SKU007
    ord_qty_007 = df_orders[df_orders["sku_id"] == "SKU007"]["quantity"].sum()
    daily_dem_007 = ord_qty_007 / 90.0
    on_hand_007 = df_inv[df_inv["sku_id"] == "SKU007"]["on_hand"].sum()
    doc_007 = on_hand_007 / daily_dem_007
    assert doc_007 > 40.0, f"Expected SKU007 days of cover > 40, got {doc_007}"


def test_sup01_skus_below_alternative_lead_time(sample_dfs):
    """Verify at least 4 of the 7 SUP01 SKUs have days of cover below shortest alternative lead time."""
    df_orders = sample_dfs["orders"]
    df_inv = sample_dfs["inventory"]
    df_supp_skus = sample_dfs["supplier_skus"]

    key_skus = [f"SKU{i:03d}" for i in range(1, 8)]
    below_count = 0

    for sku_id in key_skus:
        ord_qty = df_orders[df_orders["sku_id"] == sku_id]["quantity"].sum()
        daily_dem = ord_qty / 90.0
        on_hand = df_inv[df_inv["sku_id"] == sku_id]["on_hand"].sum()
        doc = on_hand / daily_dem if daily_dem > 0 else 0

        alts = df_supp_skus[
            (df_supp_skus["sku_id"] == sku_id) & (df_supp_skus["supplier_id"] != "SUP01")
        ]
        min_lead_time = alts["lead_time_days"].min()
        if doc < min_lead_time:
            below_count += 1

    assert below_count >= 4, f"Expected >= 4 SKUs with doc < shortest alt lead time, got {below_count}"


def test_alternative_capacity_cannot_cover_full_demand(sample_dfs):
    """Verify for each of the 7 SKUs, no single alternative covers 100% of monthly demand."""
    df_orders = sample_dfs["orders"]
    df_supp_skus = sample_dfs["supplier_skus"]

    key_skus = [f"SKU{i:03d}" for i in range(1, 8)]

    for sku_id in key_skus:
        total_ord = df_orders[df_orders["sku_id"] == sku_id]["quantity"].sum()
        monthly_demand = total_ord / 3.0

        alts = df_supp_skus[
            (df_supp_skus["sku_id"] == sku_id) & (df_supp_skus["supplier_id"] != "SUP01")
        ]
        assert len(alts) >= 2

        for _, alt in alts.iterrows():
            cap = alt["monthly_capacity"]
            assert cap < monthly_demand, (
                f"Alternative {alt['supplier_id']} for {sku_id} has monthly capacity {cap} "
                f"which covers >= 100% of monthly demand {monthly_demand:.1f}"
            )


def test_customer_tiers_and_priority_distribution(sample_dfs):
    """Verify customers have all three tiers and priorities are not all equal."""
    df_customers = sample_dfs["customers"]
    df_orders = sample_dfs["orders"]

    # All three tiers represented
    tiers = set(df_customers["tier"])
    assert tiers == {"gold", "silver", "bronze"}

    # Priorities not all equal
    priorities = set(df_orders["priority"])
    assert len(priorities) > 1
    assert priorities == {1, 2, 3}

