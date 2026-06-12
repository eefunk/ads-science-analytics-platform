"""
ETL pipeline orchestrator: Extract → Transform → Load.

The pipeline is designed around pluggable extractors so the same transform and
load logic works regardless of data source. In this repo the sources are CSV
files and in-memory DataFrames; in production you'd swap in an S3/Parquet
extractor or a Redshift UNLOAD without touching anything downstream.

Each stage is timed and logged. The auction transform does the heavy lifting —
feature engineering, anomaly flagging, bid spread computation — so downstream
analytics and models always get consistently prepared data rather than each
module doing its own ad-hoc cleaning.
"""

import time
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from .extractors import CSVExtractor, InMemoryExtractor
from .transformers import AuctionTransformer, KPITransformer, SupplyTransformer
from .loaders import SQLiteLoader


class AdsPipeline:
    """
    End-to-end ETL pipeline for the Ads Science Analytics Platform.

    Usage:
        pipeline = AdsPipeline(data_dir="data/sample", db_path="warehouse/ads.db")
        pipeline.run()                          # run from CSVs on disk
        pipeline.run(datasets=my_dict)          # run from in-memory DataFrames
        pipeline.warehouse_summary()            # row counts per table
    """

    def __init__(
        self,
        data_dir: Union[str, Path] = "data/sample",
        db_path: Union[str, Path] = "warehouse/ads.db",
        verbose: bool = True,
    ):
        self.data_dir = Path(data_dir)
        self.db_path = Path(db_path)
        self.verbose = verbose
        self.loader = SQLiteLoader(str(self.db_path))
        self.run_stats: dict = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, datasets: Optional[dict] = None) -> "AdsPipeline":
        """
        Execute the full ETL pipeline.

        Args:
            datasets: If provided, use these DataFrames directly (skips CSV extraction).
                      Keys: "auctions", "supply", "advertisers", "campaigns"
        """
        t0 = time.time()
        self._log("[AdsPipeline] Starting ETL run...")

        # ── Extract ───────────────────────────────────────────────────────────
        t1 = time.time()
        raw = self._extract(datasets)
        self._log(f"[AdsPipeline] Extract: {time.time() - t1:.1f}s")

        # ── Transform ─────────────────────────────────────────────────────────
        t2 = time.time()
        transformed = self._transform(raw)
        self._log(f"[AdsPipeline] Transform: {time.time() - t2:.1f}s")

        # ── Load ──────────────────────────────────────────────────────────────
        t3 = time.time()
        self._load(raw, transformed)
        self._log(f"[AdsPipeline] Load: {time.time() - t3:.1f}s")

        total = time.time() - t0
        self._log(f"[AdsPipeline] Done in {total:.1f}s")
        self.run_stats = {
            "duration_sec": round(total, 2),
            "auction_rows": len(transformed["auctions"]),
            "supply_rows": len(transformed["supply"]),
            "kpi_rows": len(transformed["kpi_snapshots"]),
        }
        return self

    def warehouse_summary(self) -> pd.DataFrame:
        """Return row counts for all tables in the warehouse."""
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        tables = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", conn)[
            "name"
        ].tolist()
        rows = []
        for t in tables:
            count = pd.read_sql(f"SELECT COUNT(*) AS n FROM {t}", conn).iloc[0]["n"]
            rows.append({"table": t, "rows": int(count)})
        conn.close()
        return (
            pd.DataFrame(rows)
            .sort_values("rows", ascending=False)
            .reset_index(drop=True)
        )

    # ── Internal stages ───────────────────────────────────────────────────────

    def _extract(self, datasets: Optional[dict]) -> dict:
        """Extract raw data from either in-memory datasets or CSV files."""
        if datasets is not None:
            self._log(
                "[AdsPipeline] Using in-memory datasets (skipping CSV extraction)"
            )
            extractor = InMemoryExtractor(datasets)
            return {
                "auctions": extractor.extract("auctions"),
                "supply": extractor.extract("supply"),
                "advertisers": extractor.extract("advertisers"),
                "campaigns": extractor.extract("campaigns"),
            }

        self._log(f"[AdsPipeline] Extracting CSVs from {self.data_dir}")
        extractor = CSVExtractor(self.data_dir)
        return {
            "auctions": extractor.extract("auctions"),
            "supply": extractor.extract("supply"),
            "advertisers": extractor.extract("advertisers"),
            "campaigns": extractor.extract("campaigns"),
        }

    def _transform(self, raw: dict) -> dict:
        """Apply all transformations to raw DataFrames."""
        self._log("[AdsPipeline] Transforming auction data...")
        auctions = AuctionTransformer().transform(raw["auctions"])

        self._log("[AdsPipeline] Transforming supply data...")
        supply = SupplyTransformer().transform(raw["supply"])

        self._log("[AdsPipeline] Generating KPI snapshots...")
        kpi_daily = KPITransformer().transform(
            auctions, group_by=["date", "placement_type", "device_type", "ad_format"]
        )
        kpi_hourly = KPITransformer().transform(
            auctions, group_by=["date", "hour", "placement_type"]
        )

        return {
            "auctions": auctions,
            "supply": supply,
            "kpi_snapshots": pd.concat([kpi_daily, kpi_hourly], ignore_index=True),
        }

    def _load(self, raw: dict, transformed: dict) -> None:
        """Load all data into SQLite warehouse."""
        self._log(f"[AdsPipeline] Loading to {self.db_path}")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Dimension tables (raw)
        self.loader.load(raw["advertisers"], "dim_advertiser", strategy="replace")
        self.loader.load(raw["campaigns"], "dim_campaign", strategy="replace")

        # Fact tables (transformed)
        self.loader.load(transformed["auctions"], "fact_auctions", strategy="replace")
        self.loader.load(transformed["supply"], "fact_supply", strategy="replace")

        # KPI snapshots
        self.loader.load(transformed["kpi_snapshots"], "kpi_daily", strategy="replace")

        self._log("[AdsPipeline] Load complete.")

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)


# ── CLI entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Run AdsPipeline ETL")
    parser.add_argument(
        "--data-dir", default="data/sample", help="Path to CSV data directory"
    )
    parser.add_argument("--db", default="warehouse/ads.db", help="SQLite output path")
    parser.add_argument(
        "--generate", action="store_true", help="Generate synthetic data first"
    )
    args = parser.parse_args()

    if args.generate:
        sys.path.insert(0, str(Path(__file__).parents[2]))
        from data.generators.auction_data_generator import generate_all  # noqa: E402

        generate_all(output_dir=args.data_dir)

    pipeline = AdsPipeline(data_dir=args.data_dir, db_path=args.db)
    pipeline.run()
    print(pipeline.warehouse_summary().to_string(index=False))
