"""
Supply Analytics
Analyzes ad supply dynamics: inventory availability, monetization efficiency,
floor price optimization, and supply-demand balance.
"""

import numpy as np
import pandas as pd
from typing import Optional


class SupplyAnalyzer:
    """Analyzes supply-side metrics and inventory health."""

    def __init__(self, supply: pd.DataFrame, auctions: Optional[pd.DataFrame] = None):
        self.supply = supply.copy()
        self.supply["timestamp"] = pd.to_datetime(self.supply["timestamp"])
        self.auctions = auctions.copy() if auctions is not None else None
        if self.auctions is not None:
            self.auctions["timestamp"] = pd.to_datetime(self.auctions["timestamp"])

    def inventory_health(self) -> pd.DataFrame:
        """
        Supply health score by placement and device.
        Combines fill rate, slot availability, and floor price sensitivity.
        """
        return (
            self.supply.groupby(["placement_type", "device_type"], observed=True)
            .agg(
                total_supply_events=("supply_event_id", "count"),
                avg_fill_rate=("fill_rate", "mean"),
                avg_available_slots=("available_slots", "mean"),
                avg_monetized_slots=("monetized_slots", "mean"),
                avg_floor_price=("floor_price_usd", "mean"),
                avg_supply_health=("supply_health", "mean"),
                p50_fill_rate=("fill_rate", "median"),
                p10_fill_rate=("fill_rate", lambda x: x.quantile(0.1)),
            )
            .round(4)
            .reset_index()
            .sort_values("avg_supply_health", ascending=False)
        )

    def supply_demand_balance(self) -> pd.DataFrame:
        """
        Cross-reference supply availability with auction demand.
        Identifies under-monetized and over-requested slots.
        """
        if self.auctions is None:
            raise ValueError(
                "Auctions data required for supply-demand balance analysis."
            )

        supply_daily = (
            self.supply.groupby(["date", "placement_type"], observed=True)
            .agg(
                supply_events=("supply_event_id", "count"),
                available_slots=("available_slots", "sum"),
                monetized_slots=("monetized_slots", "sum"),
            )
            .reset_index()
        )

        demand_daily = (
            self.auctions.groupby(["date", "placement_type"], observed=True)
            .agg(
                auction_requests=("auction_id", "count"),
                filled_requests=("filled", "sum"),
                revenue_usd=("revenue_usd", "sum"),
            )
            .reset_index()
        )

        merged = supply_daily.merge(
            demand_daily, on=["date", "placement_type"], how="outer"
        )
        merged["fill_rate"] = (
            merged["filled_requests"] / merged["auction_requests"]
        ).round(4)
        merged["monetization_rate"] = (
            merged["revenue_usd"] / merged["available_slots"].replace(0, np.nan)
        ).round(4)
        merged["demand_supply_ratio"] = (
            merged["auction_requests"] / merged["supply_events"].replace(0, np.nan)
        ).round(2)

        return merged.sort_values(["date", "placement_type"])

    def floor_price_sensitivity(self, placement: str = "top_of_search") -> pd.DataFrame:
        """
        Model fill rate as a function of floor price.
        Useful for identifying the revenue-maximizing floor.
        """
        if self.auctions is None:
            raise ValueError("Auctions data required.")

        df = self.auctions[self.auctions["placement_type"] == placement].copy()
        floors = np.linspace(
            df["bid_floor_usd"].min(),
            df["bid_floor_usd"].quantile(0.95),
            50,
        )
        rows = []
        for floor in floors:
            filled = (df["winning_bid_usd"] >= floor).mean()
            rev_per_auction = (
                df.loc[df["winning_bid_usd"] >= floor, "clearing_price_usd"].mean()
                * filled
            )
            rows.append(
                {
                    "floor_usd": round(float(floor), 4),
                    "fill_rate": round(float(filled), 4),
                    "expected_rev_per_auction": round(float(rev_per_auction), 6),
                }
            )

        result = pd.DataFrame(rows)
        # Find revenue-maximizing floor
        opt_row = result.loc[result["expected_rev_per_auction"].idxmax()]
        result["is_optimal_floor"] = result["floor_usd"] == opt_row["floor_usd"]
        result["placement_type"] = placement
        return result

    def supply_trend(self, freq: str = "W") -> pd.DataFrame:
        """Weekly supply and fill rate trends."""
        df = self.supply.copy()
        df = df.set_index("timestamp")
        trend = (
            df.resample(freq)
            .agg(
                supply_events=("supply_event_id", "count"),
                avg_fill_rate=("fill_rate", "mean"),
                avg_available_slots=("available_slots", "mean"),
                avg_floor_price=("floor_price_usd", "mean"),
            )
            .round(4)
            .reset_index()
        )
        trend["fill_rate_rolling"] = (
            trend["avg_fill_rate"].rolling(4, min_periods=1).mean().round(4)
        )
        return trend

    def ad_load_analysis(self) -> dict:
        """
        Estimate ad load (ads per page view) and its relationship with supply health.
        High ad load can reduce individual slot value.
        """
        df = self.supply.copy()
        load_by_placement = (
            df.groupby("placement_type", observed=True)["available_slots"]
            .agg(["mean", "median", "max", "std"])
            .round(2)
            .rename(
                columns={
                    "mean": "avg_ad_load",
                    "median": "median_ad_load",
                    "max": "max_ad_load",
                    "std": "std_ad_load",
                }
            )
            .reset_index()
        )
        return {
            "by_placement": load_by_placement,
            "overall_avg_load": round(float(df["available_slots"].mean()), 2),
            "page_load_p50_ms": int(df["page_load_ms"].median()),
            "page_load_p95_ms": int(df["page_load_ms"].quantile(0.95)),
        }
