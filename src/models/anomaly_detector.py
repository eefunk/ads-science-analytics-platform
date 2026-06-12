"""
Anomaly Detector for Ad Serving Metrics
Detects unusual patterns in KPIs: sudden fill rate drops, bid price spikes,
revenue anomalies, and auction depth changes.

Uses statistical (Z-score, IQR) and ML-based (Isolation Forest) methods.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import warnings

warnings.filterwarnings("ignore")


class StatisticalAnomalyDetector:
    """
    Detects anomalies in time-series KPI data using Z-score and IQR methods.
    Suitable for monitoring daily/hourly metrics dashboards.
    """

    def __init__(self, z_threshold: float = 2.5, iqr_multiplier: float = 2.0):
        self.z_threshold = z_threshold
        self.iqr_multiplier = iqr_multiplier

    def detect(self, series: pd.Series, method: str = "zscore") -> pd.Series:
        """
        Return boolean mask: True = anomaly.

        Args:
            series: Time-series of metric values.
            method: 'zscore' or 'iqr'
        """
        if method == "zscore":
            z = (series - series.mean()) / series.std()
            return z.abs() > self.z_threshold
        elif method == "iqr":
            q1, q3 = series.quantile(0.25), series.quantile(0.75)
            iqr = q3 - q1
            lower, upper = q1 - self.iqr_multiplier * iqr, q3 + self.iqr_multiplier * iqr
            return (series < lower) | (series > upper)
        else:
            raise ValueError(f"Unknown method: {method}. Use 'zscore' or 'iqr'.")

    def scan_kpis(
        self, kpi_df: pd.DataFrame, value_col: str = "value", method: str = "zscore"
    ) -> pd.DataFrame:
        """
        Scan a KPI time-series DataFrame for anomalies.

        Args:
            kpi_df: DataFrame with at minimum [timestamp, kpi, value_col] columns.
            value_col: Name of the metric column.
            method: Detection method.
        """
        result = kpi_df.copy()
        result["is_anomaly"] = False
        for kpi_name, group in result.groupby("kpi", observed=True):
            mask = self.detect(group[value_col].fillna(group[value_col].median()), method)
            result.loc[group.index, "is_anomaly"] = mask.values

        result[result["is_anomaly"]].copy()  # noqa: local used below
        result["anomaly_score"] = (
            (result[value_col] - result.groupby("kpi")[value_col].transform("mean"))
            / result.groupby("kpi")[value_col].transform("std")
        ).abs().round(3)

        print(f"[StatisticalAnomalyDetector] Found {result['is_anomaly'].sum()} anomalies "
              f"across {result['kpi'].nunique()} KPIs")
        return result


class MLAnomalyDetector:
    """
    Isolation Forest-based anomaly detection on auction event features.
    Identifies unusual bid patterns, device mixes, or placement distributions.
    """

    FEATURE_COLS = [
        "winning_bid_usd", "clearing_price_usd", "bid_spread",
        "ecpm", "auction_depth", "bid_floor_usd",
    ]

    def __init__(self, contamination: float = 0.02, random_state: int = 42):
        self.contamination = contamination
        self._scaler = StandardScaler()
        self._model = IsolationForest(
            contamination=contamination,
            n_estimators=100,
            random_state=random_state,
            n_jobs=-1,
        )
        self._is_fitted = False

    def fit(self, df: pd.DataFrame) -> "MLAnomalyDetector":
        features = self._get_features(df)
        X = self._scaler.fit_transform(features)
        self._model.fit(X)
        self._is_fitted = True
        print(f"[MLAnomalyDetector] Fitted on {len(df):,} samples "
              f"(contamination={self.contamination})")
        return self

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return DataFrame with anomaly flags and scores."""
        self._check_fitted()
        features = self._get_features(df)
        X = self._scaler.transform(features)
        scores = self._model.score_samples(X)  # Higher = more normal
        labels = self._model.predict(X)  # -1 = anomaly, 1 = normal

        result = df.copy()
        result["anomaly_score"] = (-scores).round(4)  # Flip: higher = more anomalous
        result["is_anomaly"] = labels == -1

        n_anomalies = result["is_anomaly"].sum()
        print(f"[MLAnomalyDetector] Flagged {n_anomalies:,} anomalies "
              f"({n_anomalies / len(df):.2%} of {len(df):,})")
        return result

    def anomaly_summary(self, df: pd.DataFrame) -> pd.DataFrame:
        """Summarize anomaly distribution by placement and device."""
        result = self.predict(df)
        summary = (
            result.groupby(["placement_type", "device_type"], observed=True)
            .agg(
                total=("auction_id", "count"),
                anomalies=("is_anomaly", "sum"),
                anomaly_rate=("is_anomaly", "mean"),
                avg_anomaly_score=("anomaly_score", "mean"),
            )
            .round(4)
            .reset_index()
            .sort_values("anomaly_rate", ascending=False)
        )
        return summary

    def _get_features(self, df: pd.DataFrame) -> pd.DataFrame:
        available = [c for c in self.FEATURE_COLS if c in df.columns]
        return df[available].fillna(df[available].median())

    def _check_fitted(self):
        if not self._is_fitted:
            raise RuntimeError("Detector not fitted. Call .fit() first.")


class BidAnomalyMonitor:
    """
    Real-time bid anomaly monitor for individual auction events.
    Flags bids that deviate significantly from placement-level baselines.
    Uses rolling statistics for adaptive thresholding.
    """

    def __init__(self, window: int = 1000, z_threshold: float = 3.0):
        self.window = window
        self.z_threshold = z_threshold
        self._baselines: dict = {}

    def fit(self, df: pd.DataFrame) -> "BidAnomalyMonitor":
        """Learn per-placement bid distributions."""
        for placement, group in df.groupby("placement_type", observed=True):
            bids = group["winning_bid_usd"]
            self._baselines[placement] = {
                "mean": float(bids.mean()),
                "std": float(bids.std()),
                "p99": float(bids.quantile(0.99)),
            }
        print(f"[BidAnomalyMonitor] Learned baselines for {len(self._baselines)} placements")
        return self

    def score(self, df: pd.DataFrame) -> pd.DataFrame:
        """Score incoming bids against baselines."""
        result = df.copy()
        result["bid_z_score"] = np.nan
        result["bid_is_anomaly"] = False

        for placement, stats in self._baselines.items():
            mask = result["placement_type"] == placement
            if mask.sum() == 0:
                continue
            z = (result.loc[mask, "winning_bid_usd"] - stats["mean"]) / max(stats["std"], 1e-9)
            result.loc[mask, "bid_z_score"] = z.round(3)
            result.loc[mask, "bid_is_anomaly"] = z.abs() > self.z_threshold

        return result
