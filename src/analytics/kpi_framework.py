"""
KPI framework: one definition per metric, referenced everywhere.

The motivation: in a system with multiple teams, dashboards, and reports,
fill_rate tends to get computed slightly differently in each place — some
include unfilled auctions in the denominator, some don't; some filter to
certain placements, some don't. Those small differences compound into
disagreements that waste time in review meetings.

This registry defines each KPI exactly once. The KPIEngine takes a DataFrame
and the registry and produces a standardized output. Every consumer — dashboard,
alert, weekly report — references the same formulas from the same place.

The 8 KPIs here (fill_rate, ecpm, bid_spread, ctr, cvr, auction_depth,
revenue_per_auction, below_floor_rate) cover the core delivery and efficiency
metrics. The below_floor_rate is the one I find most useful for catching
problems — a spike in below-floor bids usually means something upstream broke.
"""

from dataclasses import dataclass, field
from typing import Callable, Optional
import numpy as np
import pandas as pd


# ── KPI Registry ─────────────────────────────────────────────────────────────

@dataclass
class KPIDefinition:
    name: str
    description: str
    unit: str
    target: Optional[float]
    alert_threshold: Optional[float]
    higher_is_better: bool
    category: str  # "delivery", "revenue", "efficiency", "quality"
    compute: Callable[[pd.DataFrame], pd.Series]
    owner: str = "Ads Science"
    notes: str = ""


KPI_REGISTRY: list[KPIDefinition] = [
    KPIDefinition(
        name="fill_rate",
        description="Fraction of auction requests that result in a delivered ad.",
        unit="ratio",
        target=0.85,
        alert_threshold=0.70,
        higher_is_better=True,
        category="delivery",
        compute=lambda df: df["filled"].mean(),
    ),
    KPIDefinition(
        name="ecpm",
        description="Effective CPM — revenue per 1,000 auction requests.",
        unit="USD",
        target=None,
        alert_threshold=None,
        higher_is_better=True,
        category="revenue",
        compute=lambda df: (df["revenue_usd"].sum() / len(df)) * 1000,
    ),
    KPIDefinition(
        name="bid_spread",
        description=(
            "Mean bid spread = (winning_bid − clearing_price) / winning_bid. "
            "Lower spread indicates efficient auction pricing."
        ),
        unit="ratio",
        target=0.08,
        alert_threshold=0.20,
        higher_is_better=False,
        category="efficiency",
        compute=lambda df: df["bid_spread"].mean(),
    ),
    KPIDefinition(
        name="ctr",
        description="Click-through rate among delivered ads.",
        unit="ratio",
        target=0.04,
        alert_threshold=0.01,
        higher_is_better=True,
        category="quality",
        compute=lambda df: (
            df["clicked"].sum() / max(df["filled"].sum(), 1)
        ),
    ),
    KPIDefinition(
        name="cvr",
        description="Conversion rate among clicked ads.",
        unit="ratio",
        target=0.03,
        alert_threshold=0.005,
        higher_is_better=True,
        category="quality",
        compute=lambda df: (
            df["converted"].sum() / max(df["clicked"].sum(), 1)
        ),
    ),
    KPIDefinition(
        name="auction_depth",
        description="Mean number of competing bids per auction. Higher = more competitive.",
        unit="count",
        target=6.0,
        alert_threshold=3.0,
        higher_is_better=True,
        category="efficiency",
        compute=lambda df: df["auction_depth"].mean(),
    ),
    KPIDefinition(
        name="revenue_per_auction",
        description="Mean clearing price per auction request (including unfilled).",
        unit="USD",
        target=None,
        alert_threshold=None,
        higher_is_better=True,
        category="revenue",
        compute=lambda df: df["revenue_usd"].mean(),
    ),
    KPIDefinition(
        name="below_floor_rate",
        description="Fraction of bids that do not meet the bid floor.",
        unit="ratio",
        target=0.05,
        alert_threshold=0.15,
        higher_is_better=False,
        category="delivery",
        compute=lambda df: df.get("below_floor", pd.Series(False, index=df.index)).mean(),
    ),
]

KPI_BY_NAME = {k.name: k for k in KPI_REGISTRY}


# ── KPI Engine ────────────────────────────────────────────────────────────────

class KPIEngine:
    """
    Compute, track, and alert on standardized KPIs.
    """

    def __init__(self, auctions: pd.DataFrame):
        self.auctions = auctions

    def compute_all(self, segment: Optional[dict] = None) -> pd.DataFrame:
        """
        Compute all registered KPIs for the full dataset or a filtered segment.

        Args:
            segment: e.g., {"placement_type": "top_of_search", "device_type": "mobile"}
        """
        df = self.auctions.copy()
        if segment:
            for col, val in segment.items():
                df = df[df[col] == val]

        if len(df) == 0:
            return pd.DataFrame()

        rows = []
        for kpi in KPI_REGISTRY:
            try:
                value = float(kpi.compute(df))
            except Exception as e:
                value = None
                print(f"[KPIEngine] Warning: {kpi.name} failed: {e}")

            status = "ok"
            if value is not None and kpi.alert_threshold is not None:
                if kpi.higher_is_better and value < kpi.alert_threshold:
                    status = "alert"
                elif not kpi.higher_is_better and value > kpi.alert_threshold:
                    status = "alert"
                elif kpi.target is not None:
                    if kpi.higher_is_better and value >= kpi.target:
                        status = "on_target"
                    elif not kpi.higher_is_better and value <= kpi.target:
                        status = "on_target"
                    else:
                        status = "below_target"

            rows.append({
                "kpi": kpi.name,
                "value": round(value, 6) if value is not None else None,
                "unit": kpi.unit,
                "target": kpi.target,
                "alert_threshold": kpi.alert_threshold,
                "status": status,
                "category": kpi.category,
                "higher_is_better": kpi.higher_is_better,
                "description": kpi.description,
                "n_samples": len(df),
            })

        return pd.DataFrame(rows)

    def compute_by_segment(
        self,
        segment_col: str,
        kpi_names: Optional[list[str]] = None,
    ) -> pd.DataFrame:
        """Compute KPIs broken out by a segment column (e.g., placement_type)."""
        kpis = [KPI_BY_NAME[n] for n in kpi_names] if kpi_names else KPI_REGISTRY
        rows = []
        for segment_val, group in self.auctions.groupby(segment_col, observed=True):
            for kpi in kpis:
                try:
                    value = float(kpi.compute(group))
                except Exception:
                    value = None
                rows.append({
                    segment_col: segment_val,
                    "kpi": kpi.name,
                    "value": round(value, 6) if value is not None else None,
                    "unit": kpi.unit,
                    "n_samples": len(group),
                })
        return pd.DataFrame(rows)

    def trend_analysis(
        self,
        kpi_name: str,
        freq: str = "D",
        group_col: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Time-series trend for a single KPI.
        Returns daily/weekly values with 7-period rolling average.
        """
        kpi = KPI_BY_NAME[kpi_name]
        df = self.auctions.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")

        if group_col:
            results = []
            for seg_val, grp in df.groupby(group_col, observed=True):
                agg = grp.resample(freq).apply(
                    lambda x: kpi.compute(x) if len(x) > 0 else np.nan
   