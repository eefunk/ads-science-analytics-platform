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

    Stages:
    ┌─────────────┐    ┌──────────────┐    ┌──────────────┐
    │  Extract    │ →  │  Transform   │ →  │    Load      │
    │  (CSV/DB)   │    │  (clean/     │    │  (SQLite DW) │
    │             │    │   enrich)    │    │              │
    └─────────────┘    └──────────────┘    └──────────────┘
    """

    def __init__(
        self,
        data_dir: Union[str, Path],
        db_path: Union[str, Path],
        verbose: bool = True,
    ):
        self.data_dir = Path(data_dir)
        self.db_path = Path(db_path)
        self.verbose = verbose

        self._loader = SQLiteLoader(db_path)
        self._auction_tx = AuctionTransformer()
        self._supply_tx = SupplyTransformer()
        self._kpi_tx = KPITransformer()

        # Will hold datasets after extraction
        self.raw: dict[str, pd.DataFrame] = {}
        self.transformed: dict[str, pd.DataFrame] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, datasets: Optional[dict] = None) -> "AdsPipeline":
        """
        Run full pipeline.

        Args:
            datasets: Optional pre-loaded DataFrames. If None, reads CSVs from data_dir.
        """
        t0 = time.perf_counter()
        self._log("── Starting AdsPipeline ──────────────────────────")

        self._extract(datasets)
        self._transform()
        self._load()

        elapsed = time.perf_counter() - t0
        self._log(f"── Pipeline complete in {elapsed:.1f}s ───────────────")
        return self

    def warehouse_summary(self) -> pd.DataFrame:
        """Return row counts for all tables in the DW."""
        return self._loader.table_info()

    # ── Private stages ────────────────────────────────────────────────────────

    def _extract(self, datasets: Optional[dict]) -> None:
        self._log("[1/3] Extracting...")
        if datasets is not None:
            extractor = InMemoryExtractor(datasets)
            for name in datasets:
                self.raw[name] = extractor.extract(name)
        else:
            extractor = CSVExtractor(self.data_dir)
            self.raw = extractor.extract_all()

    def _transform(self) -> None:
        self._log("[2/3] Transforming...")

        if "auctions" in self.raw:
            self.transformed["auctions"] = self._auction_tx.transform(self.raw["auctions"])

        if "supply" in self.raw:
            self.transformed["supply"] = self._supply_tx.transform(self.raw["supply"])

        if "advertisers" in self.raw:
            self.transformed["advertisers"] = self.raw["advertisers"].copy()

        if "campaigns" in self.raw:
            self.transformed["campaigns"] = self.raw["campaigns"].copy()

        # KPI snapshots
        if "auctions" in self.transformed:
            self.transformed["kpi_daily"] = self._kpi_tx.transform(
                self.transformed["auctions"],
                group_by=["date", "placement_type", "device_type", "ad_format"],
            )
            self.transformed["kpi_hourly"] = self._kpi_tx.transform(
                self.transformed["auctions"],
                group_by=["date", "hour", "placement_type"],
            )

    def _load(self) -> None:
        self._log("[3/3] Loading to warehouse...")
        for name, df in self.transformed.items():
            # Coerce date objects to strings for SQLite compatibility
            for col in df.select_dtypes(include=["object"]).columns:
                try:
                    df[col] = df[col].astype(str)
                except Exception:
                    pass
            self._loader.load(df, name, if_exists="replace")

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)


# ── CLI entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Run AdsPipeline ETL")
    parser.add_argument("--data-dir", default="data/sample", help="Path to CSV data directory")
    parser.add_argument("--db", default="warehouse/ads.db", he