"""Unit tests for auction analytics, supply analytics, and KPI framework."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from data.generators.auction_data_generator import generate_all
from src.etl.transformers import AuctionTransformer, SupplyTransformer
from src.analytics.auction_analytics import AuctionAnalyzer, FeatureReleaseAnalyzer
from src.analytics.supply_analytics import SupplyAnalyzer
from src.analytics.kpi_framework import KPIEngine, KPI_REGISTRY


@pytest.fixture(scope="module")
def datasets():
    return generate_all(n_advertisers=80, n_auctions=10_000, n_supply=5_000, days=60)


@pytest.fixture(scope="module")
def auctions(datasets):
    return AuctionTransformer().transform(datasets["auctions"])


@pytest.fixture(scope="module")
def supply(datasets):
    return SupplyTransformer().transform(datasets["supply"])


# ── AuctionAnalyzer ───────────────────────────────────────────────────────────


class TestAuctionAnalyzer:
    def test_bid_spread_summary_columns(self, auctions):
        analyzer = AuctionAnalyzer(auctions)
        result = analyzer.bid_spread_summary()
        assert "mean_spread" in result.columns
        assert "median_spread" in result.columns
        assert len(result) > 0

    def test_bid_spread_over_time_has_timestamp(self, auctions):
        analyzer = AuctionAnalyzer(auctions)
        result = analyzer.bid_spread_over_time(freq="W")
        assert "timestamp" in result.columns
        assert len(result) > 0

    def test_auction_depth_analysis(self, auctions):
        analyzer = AuctionAnalyzer(auctions)
        result = analyzer.auction_depth_analysis()
        assert "summary" in result
        assert "by_depth_bucket" in result
        assert result["summary"]["mean_depth"] > 0

    def test_fill_rate_all_placements(self, auctions):
        analyzer = AuctionAnalyzer(auctions)
        result = analyzer.fill_rate_analysis()
        assert len(result) > 0
        assert result["fill_rate"].between(0, 1).all()

    def test_simulate_floor_price_change(self, auctions):
        analyzer = AuctionAnalyzer(auctions)
        sim = analyzer.simulate_floor_price_change(new_floor_multiplier=1.20)
        assert "revenue_delta_pct" in sim
        assert "fill_rate_delta" in sim
        # Raising floors should reduce fill rate
        assert sim["fill_rate_delta"] <= 0.01  # slight tolerance for synthetic data

    def test_simulate_auction_format_change(self, auctions):
        analyzer = AuctionAnalyzer(auctions)
        sim = analyzer.simulate_auction_format_change()
        assert sim["revenue_lift_pct"] > 0  # first-price always collects more

    def test_ecpm_percentiles(self, auctions):
        analyzer = AuctionAnalyzer(auctions)
        result = analyzer.ecpm_percentiles()
        assert "p50" in result.columns
        assert (result["p50"] > 0).all()


# ── FeatureReleaseAnalyzer ────────────────────────────────────────────────────


class TestFeatureReleaseAnalyzer:
    def test_diff_in_diff_keys(self, auctions):
        analyzer = FeatureReleaseAnalyzer(auctions)
        result = analyzer.diff_in_diff(metric="fill_rate")
        for key in [
            "did_estimate",
            "p_value",
            "significant_at_5pct",
            "relative_lift_pct",
        ]:
            assert key in result, f"Missing key: {key}"

    def test_diff_in_diff_numeric(self, auctions):
        analyzer = FeatureReleaseAnalyzer(auctions)
        result = analyzer.diff_in_diff(metric="ecpm")
        assert isinstance(result["did_estimate"], float)
        # p_value may be None if insufficient samples in a period
        if result["p_value"] is not None:
            assert 0 <= result["p_value"] <= 1

    def test_adoption_curve(self, auctions):
        analyzer = FeatureReleaseAnalyzer(auctions)
        result = analyzer.adoption_curve(freq="W")
        assert "adoption_rate" in result.columns
        assert result["adoption_rate"].between(0, 1).all()


# ── SupplyAnalyzer ────────────────────────────────────────────────────────────


class TestSupplyAnalyzer:
    def test_inventory_health(self, supply, auctions):
        analyzer = SupplyAnalyzer(supply, auctions)
        result = analyzer.inventory_health()
        assert len(result) > 0
        assert "avg_fill_rate" in result.columns
        assert result["avg_fill_rate"].between(0, 1).all()

    def test_supply_demand_balance(self, supply, auctions):
        analyzer = SupplyAnalyzer(supply, auctions)
        result = analyzer.supply_demand_balance()
        assert len(result) > 0
        assert "demand_supply_ratio" in result.columns

    def test_floor_price_sensitivity(self, supply, auctions):
        analyzer = SupplyAnalyzer(supply, auctions)
        result = analyzer.floor_price_sensitivity("top_of_search")
        assert "fill_rate" in result.columns
        assert "is_optimal_floor" in result.columns
        assert result["is_optimal_floor"].sum() == 1  # exactly one optimal floor


# ── KPIEngine ─────────────────────────────────────────────────────────────────


class TestKPIEngine:
    def test_compute_all_returns_all_kpis(self, auctions):
        engine = KPIEngine(auctions)
        result = engine.compute_all()
        registered_kpi_names = {k.name for k in KPI_REGISTRY}
        result_kpi_names = set(result["kpi"])
        assert registered_kpi_names == result_kpi_names

    def test_kpi_values_non_null(self, auctions):
        engine = KPIEngine(auctions)
        result = engine.compute_all()
        assert result["value"].notna().all()

    def test_kpi_statuses_valid(self, auctions):
        engine = KPIEngine(auctions)
        result = engine.compute_all()
        valid = {"ok", "alert", "on_target", "below_target"}
        assert set(result["status"]).issubset(valid)

    def test_segment_filter(self, auctions):
        engine = KPIEngine(auctions)
        result = engine.compute_all(segment={"placement_type": "top_of_search"})
        # Should only reflect top_of_search auctions
        fill_rate_kpi = result.loc[result["kpi"] == "fill_rate", "value"].iloc[0]
        expected = auctions[auctions["placement_type"] == "top_of_search"][
            "filled"
        ].mean()
        assert abs(fill_rate_kpi - expected) < 0.01

    def test_alerts_subset_of_all(self, auctions):
        engine = KPIEngine(auctions)
        all_kpis = engine.compute_all()
        alerts = engine.alerts()
        assert len(alerts) <= len(all_kpis)
        assert all(alerts["status"] == "alert")

    def test_compute_by_segment(self, auctions):
        engine = KPIEngine(auctions)
        result = engine.compute_by_segment(
            "placement_type", kpi_names=["fill_rate", "ecpm"]
        )
        assert set(result["kpi"]) == {"fill_rate", "ecpm"}
        assert (
            result["placement_type"].nunique() == auctions["placement_type"].nunique()
        )

    def test_trend_analysis(self, auctions):
        engine = KPIEngine(auctions)
        result = engine.trend_analysis("fill_rate", freq="W")
        assert "value" in result.columns
        assert "rolling_avg" in result.columns
        assert len(result) > 0
