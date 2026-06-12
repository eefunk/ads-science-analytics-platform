"""
Transformers: Clean, enrich, and model raw ad auction data.
"""

import numpy as np
import pandas as pd


class AuctionTransformer:
    """
    Clean and enrich auction event data.
    - Parses timestamps
    - Derives time features
    - Computes eCPM, bid spread, margin metrics
    - Flags anomalies
    """

    REQUIRED_COLS = [
        "auction_id", "timestamp", "placement_type", "device_type",
        "winning_bid_usd", "clearing_price_usd", "filled",
    ]

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        self._validate(df)
        df = df.copy()

        # ── Timestamps ───────────────────────────────────────────────────────
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["date"] = df["timestamp"].dt.date
        df["hour"] = df["timestamp"].dt.hour
        df["day_of_week"] = df["timestamp"].dt.day_name()
        df["week"] = df["timestamp"].dt.isocalendar().week.astype(int)
        df["month"] = df["timestamp"].dt.month
        df["is_weekend"] = df["timestamp"].dt.dayofweek >= 5

        # ── Bid metrics ──────────────────────────────────────────────────────
        df["bid_spread"] = (
            (df["winning_bid_usd"] - df["clearing_price_usd"])
            / df["winning_bid_usd"].replace(0, np.nan)
        ).fillna(0).round(4)

        df["margin_usd"] = (
            df["winning_bid_usd"] - df["clearing_price_usd"]
        ).round(4)

        # ── Performance flags ────────────────────────────────────────────────
        df["has_click"] = df.get("clicked", pd.Series(0, index=df.index)).astype(bool)
        df["has_conversion"] = df.get("converted", pd.Series(0, index=df.index)).astype(bool)
        df["ctr"] = np.where(df["filled"] == 1, df["has_click"].astype(float), np.nan)
        df["cvr"] = np.where(
            df["has_click"], df["has_conversion"].astype(float), np.nan
        )

        # ── Anomaly flags ────────────────────────────────────────────────────
        # Bids > 3 std from placement mean = suspicious
        bid_stats = df.groupby("placement_type")["winning_bid_usd"].transform(
            lambda x: (x - x.mean()) / x.std()
        )
        df["bid_z_score"] = bid_stats.round(3)
        df["is_bid_anomaly"] = df["bid_z_score"].abs() > 3

        # Fill bids below floor
        if "bid_floor_usd" in df.columns:
            df["below_floor"] = df["winning_bid_usd"] < df["bid_floor_usd"]

        print(
            f"[AuctionTransformer] Processed {len(df):,} rows | "
            f"fill_rate={df['filled'].mean():.2%} | "
            f"anomalies={df['is_bid_anomaly'].sum()}"
        )
        return df

    def _validate(self, df: pd.DataFrame) -> None:
        missing = [c for c in self.REQUIRED_COLS if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")


class SupplyTransformer:
    """Clean and enrich supply-side event data."""

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["date"] = df["timestamp"].dt.date
        df["hour"] = df["timestamp"].dt.hour
        df["day_of_week"] = df["timestamp"].dt.day_name()

        # Monetized slots
        df["monetized_slots"] = (
            df["available_slots"] * df["fill_rate"]
        ).round(2)

        # Supply health score: fill_rate penalized by floor price sensitivity
        df["supply_health"] = (
            df["fill_rate"] * 0.7 + (1 - df["floor_price_usd"] / df["floor_price_usd"].max()) * 0.3
        ).round(4)

        print(f"[SupplyTransformer] Processed {len(df):,} supply events")
        return df


class KPITransformer:
    """
    Aggregate cleaned auction data into daily KPI snapshots.
    Suitable for loading into a metrics warehouse.
    """

    def transform(
        self,
        auctions: pd.DataFrame,
        group_by: list[str] = None,
    ) -> pd.DataFrame:
        if group_by is None:
            group_by = ["date", "placement_type", "device_type", "ad_format"]

        agg = (
            auctions.groupby(group_by, observed=True)
            .agg(
                total_auctions=("auction_id", "count"),
                filled_auctions=("filled", "sum"),
                total_clicks=("clicked", "sum"),
                total_conversions=("converted", "sum"),
                total_revenue_usd=("revenue_usd", "sum"),
                avg_winning_bid=("winning_bid_usd", "mean"),
                avg_clearing_price=("clearing_price_usd", "mean"),
                avg_bid_spread=("bid_spread", "mean"),
                avg_ecpm=("ecpm", "mean"),
                avg_auction_depth=("auction_depth", "mean"),
                p50_winning_bid=("winning_bid_usd", lambda x: x.quantile(0.5)),
                p90_winning_bid=("winning_bid_usd", lambda x: x.quantile(0.9)),
                p99_winning_bid=("winning_bid_usd", lambda x: x.quantile(0.99)),
            )
            .reset_index()
        )

        # Derived KPIs
        agg["fill_rate"] = (agg["filled_auctions"] / agg["total_auctions"]).round(4)
        agg["ctr"] = (agg["total_clicks"] / agg["filled_auctions"].replace(0, np.nan)).round(4)
        agg["cvr"] = (agg["total_conversions"] / agg["total_clicks"].replace(0, np.nan)).round(4)
        agg["cpc_usd"] = (agg["total_revenue_usd"] / agg["total_clicks"].replace(0, np.nan)).round(4)
        agg["rpm_usd"] = (agg["total_revenue_usd"] / agg["total_auctions"] * 1000).round(4)

        print(f"[KPITransformer] Generated {len(agg):,} KPI rows across {group_by}")
        return agg
