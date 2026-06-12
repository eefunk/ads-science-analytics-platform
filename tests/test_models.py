"""Unit tests for ML models: FillRatePredictor, ECPMPredictor, AnomalyDetectors."""

import pytest
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from data.generators.auction_data_generator import generate_all
from src.etl.transformers import AuctionTransformer
from src.models.auction_predictor import FillRatePredictor, ECPMPredictor
from src.models.anomaly_detector import (
    MLAnomalyDetector, StatisticalAnomalyDetector, BidAnomalyMonitor
)


@pytest.fixture(scope="module")
def auctions():
    raw = generate_all(n_advertisers=60, n_auctions=8_000, n_supply=2_000, days=30)
    return AuctionTransformer().transform(raw["auctions"])


# ── FillRatePredictor ─────────────────────────────────────────────────────────

class TestFillRatePredictor:
    def test_fit_and_metrics(self, auctions):
        model = FillRatePredictor()
        model.fit(auctions)
        assert model._is_fitted
        assert "roc_auc" in model.metrics
        assert model.metrics["roc_auc"] > 0.5, "ROC-AUC should beat random"

    def test_predict_proba_range(self, auctions):
        model = FillRatePredictor()
        model.fit(auctions)
        probs = model.predict_proba(auctions.head(100))
        assert probs.min() >= 0.0
        assert probs.max() <= 1.0
        assert len(probs) == 100

    def test_predict_binary(self, auctions):
        model = FillRatePredictor()
        model.fit(auctions)
        preds = model.predict(auctions.head(50))
        assert set(preds).issubset({0, 1})

    def test_feature_importance_has_all_features(self, auctions):
        model = FillRatePredictor()
        model.fit(auctions)
        fi = model.feature_importance()
        assert len(fi) > 0
        assert "feature" in fi.columns
        assert "importance" in fi.columns
        assert fi["importance"].sum() == pytest.approx(1.0, abs=0.01)

    def test_save_and_load(self, auctions, tmp_path):
        model = FillRatePredictor()
        model.fit(auctions)
        path = tmp_path / "fill_rate_model.pkl"
        model.save(path)
        loaded = FillRatePredictor.load(path)
        original_probs = model.predict_proba(auctions.head(20))
        loaded_probs = loaded.predict_proba(auctions.head(20))
        np.testing.assert_array_almost_equal(original_probs, loaded_probs)

    def test_unfitted_raises(self):
        model = FillRatePredictor()
        # Not fitted at all → RuntimeError
        with pytest.raises(RuntimeError):
            model._check_fitted()


# ── ECPMPredictor ─────────────────────────────────────────────────────────────

class TestECPMPredictor:
    def test_fit_and_r2(self, auctions):
        model = ECPMPredictor()
        model.fit(auctions)
        assert model._is_fitted
        assert "r2" in model.metrics
        assert model.metrics["r2"] > 0.0, "R² should be positive"

    def test_predict_positive(self, auctions):
        model = ECPMPredictor()
        model.fit(auctions)
        preds = model.predict(auctions.head(50))
        assert (preds > 0).all(), "eCPM predictions must be positive"

    def test_predict_shape(self, auctions):
        model = ECPMPredictor()
        model.fit(auctions)
        preds = model.predict(auctions.head(100))
        assert len(preds) == 100


# ── MLAnomalyDetector ─────────────────────────────────────────────────────────

class TestMLAnomalyDetector:
    def test_fit_and_predict(self, auctions):
        detector = MLAnomalyDetector(contamination=0.02)
        detector.fit(auctions)
        result = detector.predict(auctions)
        assert "is_anomaly" in result.columns
        assert "anomaly_score" in result.columns

    def test_contamination_rate(self, auctions):
        contamination = 0.02
        detector = MLAnomalyDetector(contamination=contamination)
        detector.fit(auctions)
        result = detector.predict(auctions)
        # Actual anomaly rate should be close to contamination
        actual_rate = result["is_anomaly"].mean()
        assert abs(actual_rate - contamination) < 0.01

    def test_anomaly_summary(self, auctions):
        detector = MLAnomalyDetector(contamination=0.02)
        detector.fit(auctions)
        summary = detector.anomaly_summary(auctions)
        assert "anomaly_rate" in summary.columns
        assert summary["anomaly_rate"].between(0, 1).all()

    def test_unfitted_raises(self, auctions):
        detector = MLAnomalyDetector()
        with pytest.raises(RuntimeError):
            detector.predict(auctions.head(5))


# ── StatisticalAnomalyDetector ────────────────────────────────────────────────

class TestStatisticalAnomalyDetector:
    def test_zscore_detection(self, auctions):
        detector = StatisticalAnomalyDetector(z_threshold=2.5)
        series = auctions["winning_bid_usd"]
        anomalies = detector.detect(series, method="zscore")
        assert anomalies.dtype == bool
        assert 0 < anomalies.sum() < len(series)

    def test_iqr_detection(self, auctions):
        detector = StatisticalAnomalyDetector()
        series = auctions["ecpm"]
        anomalies = detector.detect(series, method="iqr")
        assert anomalies.dtype == bool

    def test_invalid_method_raises(self, auctions):
        detector = StatisticalAnomalyDetector()
        with pytest.raises(ValueError):
            detector.detect(auctions["ecpm"], method="unknown")


# ── BidAnomalyMonitor ─────────────────────────────────────────────────────────

class TestBidAnomalyMonitor:
    def test_fit_learns_baselines(self, auctions):
        monitor = BidAnomalyMonitor()
        monitor.fit(auctions)
        assert len(monitor._baselines) == auctions["placement_type"].nunique()

    def test_score_adds_columns(self, auctions):
        monitor = BidAnomalyMonitor(z_threshold=3.0)
        monitor.fit(auctions)
        result = monitor.score(auctions)
        assert "bid_z_score" in result.columns
        assert "bid_is_anomaly" in result.columns

    def test_anomaly_count_reasonable(self, auctions):
        monitor = BidAnomalyMonitor(z_threshold=3.0)
        monitor.fit(auctions)
        result = monitor.score(auctions)
        anomaly_rate = result["bid_is_anomaly"].mean()
        # At 3σ, normal data → ~0.27% anomalies; realistic data may be slightly higher
        assert anomaly_rate < 0.10, f"Anomaly rate too high: {anomaly_rate:.2%}"
