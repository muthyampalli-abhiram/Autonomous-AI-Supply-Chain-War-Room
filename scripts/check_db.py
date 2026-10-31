"""Database diagnostics script verifying connection, dialect, server version, and table row counts."""

from __future__ import annotations

from pathlib import Path
import sys

# Ensure src/ is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sqlalchemy import create_engine, func, select, text

from warroom.config import get_settings
from warroom.db.models import (
    Carrier,
    Customer,
    Inventory,
    Order,
    SKU,
    Supplier,
    SupplierSKU,
    Warehouse,
)

TABLE_MODELS = [
    ("suppliers", Supplier),
    ("skus", SKU),
    ("supplier_skus", SupplierSKU),
    ("warehouses", Warehouse),
    ("inventory", Inventory),
    ("carriers", Carrier),
    ("customers", Customer),
    ("orders", Order),
]


def check_database() -> None:
    settings = get_settings()
    db_url = settings.db_url
    print("=" * 60)
    print("Autonomous AI Supply Chain War Room - Database Diagnostics")
    print("=" * 60)
    print(f"[*] Target Database URL : {db_url}")

    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            dialect_name = engine.dialect.name
            print(f"[*] Dialect             : {dialect_name}")

            # Query server version
            server_version = "Unknown"
            try:
                if dialect_name == "postgresql":
                    server_version = conn.execute(text("SHOW server_version;")).scalar() or "Unknown"
                elif dialect_name == "sqlite":
                    server_version = conn.execute(text("SELECT sqlite_version();")).scalar() or "Unknown"
                else:
                    server_version = conn.execute(text("SELECT version();")).scalar() or "Unknown"
            except Exception as v_err:
                server_version = f"Error retrieving version: {v_err}"

            print(f"[*] Server Version       : {server_version}")
            print("-" * 60)
            print(f"  {'TABLE NAME':<25} | {'ROW COUNT'}")
            print("  " + "-" * 40)

            total_rows = 0
            for table_name, model in TABLE_MODELS:
                try:
                    count = conn.scalar(select(func.count()).select_from(model)) or 0
                except Exception:
                    count = conn.scalar(text(f"SELECT COUNT(*) FROM {table_name};")) or 0
                print(f"  {table_name:<25} | {count:,}")
                total_rows += count

            print("  " + "-" * 40)
            print(f"  {'TOTAL ROWS':<25} | {total_rows:,}")
            print("=" * 60)
            print("[+] Database connection and table verification successful.")

    except Exception as exc:
        print(f"\n[-] ERROR: Database connection failed for '{db_url}': {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    check_database()
