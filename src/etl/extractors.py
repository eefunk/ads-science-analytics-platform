"""
Extractors: Pull raw data from various sources (CSV, database, API stubs).
"""

import sqlite3
import pandas as pd
from pathlib import Path
from typing import Union


class CSVExtractor:
    """Extract data from CSV files (data lake simulation)."""

    def __init__(self, data_dir: Union[str, Path]):
        self.data_dir = Path(data_dir)

    def extract(self, table: str, **read_kwargs) -> pd.DataFrame:
        path = self.data_dir / f"{table}.csv"
        if not path.exists():
            raise FileNotFoundError(f"No CSV found at {path}")
        df = pd.read_csv(path, **read_kwargs)
        print(f"[CSVExtractor] Loaded {len(df):,} rows from {path.name}")
        return df

    def extract_all(self) -> dict[str, pd.DataFrame]:
        tables = {}
        for csv_file in sorted(self.data_dir.glob("*.csv")):
            tables[csv_file.stem] = self.extract(csv_file.stem)
        return tables


class SQLiteExtractor:
    """Extract data from a SQLite warehouse."""

    def __init__(self, db_path: Union[str, Path]):
        self.db_path = str(db_path)

    def extract(self, query: str, params: tuple = ()) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(query, conn, params=params)
        print(f"[SQLiteExtractor] Query returned {len(df):,} rows")
        return df

    def extract_table(self, table: str) -> pd.DataFrame:
        return self.extract(f"SELECT * FROM {table}")

    def list_tables(self) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            return [row[0] for row in cur.fetchall()]


class InMemoryExtractor:
    """Pass DataFrames directly (useful for testing and notebooks)."""

    def __init__(self, datasets: dict[str, pd.DataFrame]):
        self.datasets = datasets

    def extract(self, table: str) -> pd.DataFrame:
        if table not in self.datasets:
            raise KeyError(f"Table '{table}' not in in-memory datasets")
        df = self.datasets[table].copy()
        print(f"[InMemoryExtractor] Loaded {len(df):,} rows for '{table}'")
        return df
