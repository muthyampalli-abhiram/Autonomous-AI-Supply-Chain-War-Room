"""Script to generate synthetic supply chain data, save to CSV, and load into database."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure src/ is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from warroom.config import get_settings
from warroom.data_gen.generator import generate_all
from warroom.data_gen.loader import load_to_db, save_csvs
from warroom.db.session import get_engine, init_db
from sqlalchemy import text


def main() -> None:
    settings = get_settings()
    print("=" * 70)
    print("Autonomous AI Supply Chain War Room - Data Generation Pipeline")
    print("=" * 70)
    print(f"Project Root: {settings.project_root}")
    print(f"Database URL: {settings.db_url}")
    print(f"Random Seed:  {settings.random_seed}")
    print()

    # 1. Initialize database (drop and recreate tables)
    print("[1/4] Initializing database tables (drop=True)...")
    engine = get_engine()
    init_db(engine=engine, drop=True)
    print("      Database schema initialized successfully.")

    # 2. Generate synthetic data
    print("[2/4] Generating synthetic supply chain data...")
    dfs = generate_all(seed=settings.random_seed)
    print("      Data generation completed.")

    # 3. Save to CSVs
    csv_dir = settings.data_dir / "csv"
    print(f"[3/4] Saving CSV files to '{csv_dir}'...")
    saved_files = save_csvs(dfs, output_dir=csv_dir)
    for p in saved_files:
        print(f"      Saved {p.name} ({len(dfs[p.stem])} rows)")

    # 4. Load into database
    print("[4/4] Loading data into database...")
    load_to_db(dfs, engine=engine)
    print("      Data inserted into database successfully.")
    print()

    # Verify and print row counts from database
    print("-" * 70)
    print("DATABASE ROW COUNTS")
    print("-" * 70)
    with engine.connect() as conn:
        for table_name in [
            "suppliers",
            "skus",
            "supplier_skus",
            "warehouses",
            "inventory",
            "carriers",
            "customers",
            "orders",
        ]:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
            print(f"  {table_name:<16}: {count:>5} rows")

    # Analyze and print key supplier dependencies
    print()
    print("-" * 70)
    print("KEY SUPPLIER DEPENDENCIES")
    print("-" * 70)

    df_suppliers = dfs["suppliers"]
    df_skus = dfs["skus"]
    df_supplier_skus = dfs["supplier_skus"]

    key_sups = df_suppliers[df_suppliers["is_key_supplier"] == True]
    if key_sups.empty:
        print("  WARNING: No key supplier marked.")
        return

    for _, key_sup in key_sups.iterrows():
        sup_id = key_sup["supplier_id"]
        print(f"Key Supplier: {sup_id} - {key_sup['name']} ({key_sup['country']})")
        print(f"Reliability:  {key_sup['reliability_score']:.2f} | Lead Time: {key_sup['lead_time_days']} days")
        print()

        # Find SKUs where this supplier is primary
        primary_skus = df_supplier_skus[
            (df_supplier_skus["supplier_id"] == sup_id) & (df_supplier_skus["is_primary"] == True)
        ]

        print(f"Dependent SKUs ({len(primary_skus)} items where {sup_id} is primary supplier):")
        for _, link in primary_skus.iterrows():
            sku_id = link["sku_id"]
            sku_info = df_skus[df_skus["sku_id"] == sku_id].iloc[0]

            # Find alternative suppliers
            alts = df_supplier_skus[
                (df_supplier_skus["sku_id"] == sku_id) & (df_supplier_skus["supplier_id"] != sup_id)
            ]
            alt_summary = []
            for _, alt_row in alts.iterrows():
                alt_sup = df_suppliers[df_suppliers["supplier_id"] == alt_row["supplier_id"]].iloc[0]
                alt_summary.append(
                    f"{alt_row['supplier_id']} ({alt_sup['name']}: ${alt_row['unit_price']:.2f}, {alt_row['lead_time_days']}d)"
                )

            print(f"  - [{sku_id}] {sku_info['name']} ({sku_info['category']})")
            print(f"      Primary Price: ${link['unit_price']:.2f} | Lead Time: {link['lead_time_days']}d | Capacity: {link['monthly_capacity']}/mo")
            print(f"      Alternatives ({len(alts)}): {'; '.join(alt_summary)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
