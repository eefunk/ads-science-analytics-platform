"""Unit tests for ETL pipeline components."""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

from data.generators.auction_data_generator import (
    generate_advertisers, generate_campaigns, generate_auction_events
)
from src.etl.transformers import AuctionTransformer, KPITransformer
from src.etl.loaders import SQLiteLoader
from src.etl.pipeline import AdsPipeline


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def small_advertisers():
    return generate_advertisers(50)

@pytest.fixture(scope="module")
def small_campaigns(small_advertisers):
    return generate_campaigns(small_advertisers, campaigns_per_adv=2)

@pytest.fixture(scope="module")
def small_auctions(small_campaigns):
    return generate_auction_events(small_campaigns, n_auctions=5_000, days=30)


# ── Generator tests ───────────────────────────────────────────────────────────

class TestDataGenerators:
    def test_advertisers_shape(self, small_advertisers):
        assert len(small_advertisers) == 50
        assert "advertiser_id" in small_advertisers.columns
        assert "daily_budget_usd" in small_advertisers.columns

    def test_advertiser_ids_unique(self, small_advertisers):
        assert small_advertisers["advertiser_id"].is_unique

    def test_campaign_links_to_advertiser(self, small_advertisers, small_campaigns):
        adv_ids = set(small_advertisers["advertiser_id"])
        camp_adv_ids = set(small_campaigns["advertiser_id"])
        assert camp_adv_ids.issubset(adv_ids)

    def test_auctions_have_required_columns(self, small_auctions):
        required = [
            "auction_id", "timestamp", "placement_type", "device_type",
            "winning_bid_usd", "clearing_price_usd", "filled", "ecpm",
        ]
        for col in required:
            assert col in small_auctions.columns, f"Missing column: {col}"

    def test_auctions_bid_floor_respected(self, small_auctions):
        # Filled auctions must have winning_bid >= floor
        filled = small_auctions[small_auctions["filled"] == 1]
        assert (filled["winning_bid_usd"] >= filled["bid_floor_usd"] * 0.99).all()

    def test_auctions_no_negative_bids(self, small_auctions):
        assert (small_auctions["winning_bid_usd"] >= 0).all()
        assert (small_auctions["clearing_price_usd"] >= 0).all()

    def test_fill_rate_in_range(self, small_auctions):
        fill_rate = small_auctions["filled"].mean()
        assert 0.3 < fill_rate < 0.99, f"Unexpected fill rate: {fill_rate}"


# ── Transformer tests ─────────────────────────────────────────────────────────

class TestAuctionTransformer:
    def test_transform_adds_time_features(self, small_auctions):
        tx = AuctionTransformer()
        result = tx.transform(small_auctions)
        assert "day_of_week" in result.columns
        assert "is_weekend" in result.columns
        assert "bid_spread" in result.columns

    def test_bid_spread_in_range(self, small_auctions):
        tx = AuctionTransformer()
        result = tx.transform(small_auctions)
        assert result["bid_spread"].between(-0.5, 1.0).all()

    def test_anomaly_flag_is_boolean(self, small_auctions):
        tx = AuctionTransformer()
        result = tx.transform(small_auctions)
        assert result["is_bid_anomaly"].dtype == bool

    def test_missing_required_col_raises(self, small_auctions):
        tx = AuctionTransformer()
        with pytest.raises(ValueError, match="Missing required columns"):
            tx.transform(small_auctions.drop(columns=["filled"]))


class TestKPITransformer:
    def test_kpi_fill_rate_matches_raw(self, small_auctions):
        tx = AuctionTransformer()
        auctions = tx.transform(small_auctions)
        kpi_tx = KPITransformer()
        kpi = kpi_tx.transform(auctions)
        assert "fill_rate" in kpi.columns
        # Platform-level fill rate sanity check
        total = kpi["total_auctions"].sum()
        filled = kpi["filled_auctions"].sum()
        expected = filled / total
        actual = (kpi["fill_rate"] * kpi["total_auctions"]).sum() / total
        assert abs(expected - actual) < 0.01

    def test_kpi_no_nulls_in_key_columns(self, small_auctions):
        tx = AuctionTransformer()
        auctions = tx.transform(small_auctions)
        kpi = KPITransformer().transform(auctions)
        for col in ["fill_rate", "total_auctions", "total_revenue_usd"]:
            assert kpi[col].notna().all(), f"Nulls found in {col}"


# ── Loader tests ──────────────────────────────────────────────────────────────

class TestSQLiteLoader:
    def test_load_and_read_back(self, small_auctions, tmp_path):
        db = tmp_path / "test.db"
        loader = SQLiteLoader(db)
        n = loader.load(small_auctions.head(100), "test_auctions")
        assert n == 100
        info = loader.table_info()
        assert "test_auctions" in info["table"].values
        assert info.loc[info["table"] == "test_auctions", "row_count"].iloc[0] == 100

    def test_append_mode(self, small_auctions, tmp_path):
        db = tmp_path / "append_test.db"
        loader = SQLiteLoader(db)
        loader.load(small_auctions.head(50), "auctions", if_exists="replace")
        loader.load(small_auctions.head(50), "auctions", if_exists="append")
        info = loader.table_info()
        count = info.loc[info["table"] == "auctions", "row_count"].iloc[0]
        assert count == 100


# ── Pipeline integration test ─────────────────────────────────────────────────

class TestAdsPipeline:
    def test_full_pipeline(self, small_advertisers, small_campaigns, small_auctions, tmp_path):
        datasets = {
            "advertisers": small_advertisers,
            "campaigns": small_campaigns,
            "auctions": small_auctions,
        }
        db = tmp_path / "pipeline_test.db"
        pipeline = AdsPipeline(data_dir=tmp_path / "data", db_path=db, verbose=False)
        pipeline.run(datasets=datasets)

        summary = pipeline.warehouse_summary()
        assert "auctions" in summary["table"].values
        assert "kpi_daily" in summary["table"].values

        rows = summary.loc[summary["table"] == "auctions", "row_count"].iloc[0]
        assert rows == len(small_auctions)
