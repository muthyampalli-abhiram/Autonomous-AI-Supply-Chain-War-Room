"""Data persistence and loading utilities for CSV and SQL databases."""

from __future__ import annotations

from pathlib import Path
import pandas as pd
from sqlalchemy import Engine

from warroom.config import get_settings
from warroom.db.session import get_engine

# Topological insertion order to satisfy foreign key constraints
TABLE_INSERTION_ORDER = [
    "suppliers",
    "skus",
    "warehouses",
    "carriers",
    "customers",
    "supplier_skus",
    "inventory",
    "orders",
]


def save_csvs(
    dfs: dict[str, pd.DataFrame],
    output_dir: Path | str | None = None,
) -> list[Path]:
    """Save dictionary of DataFrames to CSV files.

    Args:
        dfs: Mapping of table names to pandas DataFrames.
        output_dir: Destination directory. Defaults to data/csv/ under project data_dir.

    Returns:
        List of created Path objects.
    """
    if output_dir is None:
        output_dir = get_settings().data_dir / "csv"

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    saved_files: list[Path] = []
    for table_name, df in dfs.items():
        csv_file = out_path / f"{table_name}.csv"
        df.to_csv(csv_file, index=False)
        saved_files.append(csv_file)

    return saved_files


def load_to_db(
    dfs: dict[str, pd.DataFrame],
    engine: Engine | None = None,
) -> None:
    """Load dictionary of DataFrames into the database honoring foreign key dependencies.

    Args:
        dfs: Mapping of table names to pandas DataFrames.
        engine: Optional SQLAlchemy Engine. If None, default engine is obtained.
    """
    if engine is None:
        engine = get_engine()

    with engine.begin() as conn:
        # First insert known tables in correct dependency order
        for table_name in TABLE_INSERTION_ORDER:
            if table_name in dfs:
                dfs[table_name].to_sql(
                    name=table_name,
                    con=conn,
                    if_exists="append",
                    index=False,
                )

        # Then insert any additional tables if present
        for table_name, df in dfs.items():
            if table_name not in TABLE_INSERTION_ORDER:
                df.to_sql(
                    name=table_name,
                    con=conn,
                    if_exists="append",
                    index=False,
                )
