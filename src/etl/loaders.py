"""
Loaders: Persist transformed data to SQLite data warehouse.
"""

import sqlite3
import pandas as pd
from pathlib import Path
from typing import Union


class SQLiteLoader:
    """
    Load DataFrames into a SQLite warehouse.
    Supports append, replace, and upsert strategies.
    """

    def __init__(self, db_path: Union[str, Path]):
        self.db_path = str(db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def load(
        self,
        df: pd.DataFrame,
        table: str,
        if_exists: str = "replace",
        index: bool = False,
        chunksize: int = 10_000,
    ) -> int:
        """
        Load a DataFrame into a SQLite table.

        Args:
            df: DataFrame to load.
            table: Target table name.
            if_exists: 'replace' (default), 'append', or 'fail'.
            index: Include DataFrame index as a column.
            chunksize: Rows per batch.

        Returns:
            Number of rows written.
        """
        with sqlite3.connect(self.db_path) as conn:
            df.to_sql(
                table, conn, if_exists=if_exists, index=index, chunksize=chunksize
            )
        print(f"[SQLiteLoader] Wrote {len(df):,} rows → {table} ({if_exists})")
        return len(df)

    def load_many(self, datasets: dict[str, pd.DataFrame], **kwargs) -> dict[str, int]:
        """Load multiple DataFrames in one call."""
        return {name: self.load(df, name, **kwargs) for name, df in datasets.items()}

    def execute(self, sql: str) -> None:
        """Execute arbitrary DDL/DML."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(sql)
            conn.commit()

    def execute_script(self, sql_path: Union[str, Path]) -> None:
        """Execute a SQL script file."""
        with open(sql_path) as f:
            script = f.read()
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(script)
        print(f"[SQLiteLoader] Executed script: {sql_path}")

    def table_info(self) -> pd.DataFrame:
        """Return row counts for all tables."""
        with sqlite3.connect(self.db_path) as conn:
            tables = pd.read_sql_query(
                "SELECT name FROM sqlite_master WHERE type='table'", conn
            )["name"].tolist()
            rows = []
            for t in tables:
                count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                rows.append({"table": t, "row_count": count})
        return pd.DataFrame(rows)
