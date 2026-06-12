"""
Auction analytics: bid spreads, depth, fill rates, floor/format simulations, DiD.

This module grew out of trying to answer a simple question: where is value leaking
in the auction? Bid spread tells you how much the winner overpaid relative to
the clearing price. Auction depth tells you whether more competition is actually
helping eCPM (it does, but with diminishing returns past ~5 bidders). The
simulation methods let you model floor price changes or format shifts before
committing to them in production.

The FeatureReleaseAnalyzer at the bottom handles causal measurement — using
diff-in-differences rather than raw before/after to control for time trends.
"""

import pandas as pd
from scipy import stats
from typing import Optional
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)


class AuctionAnalyzer:
    """
    Core auction analytics: bid spread, depth, fill rate, eCPM, and simulations.

    Pass a transformed auctions DataFrame (from AuctionTransformer) and call
    whatever analyses you need. Methods are intentionally stateless — each one
    operates on self.auctions and returns a DataFrame or dict, nothing persisted.
    """

    def __init__(self, auctions: pd.DataFrame):
        self.auctions = auctions.copy()
        self.auctions["timestamp"] = pd.to_datetime(self.auctions["timestamp"])

    # ── Bid Spread Analysis ───────────────────────────────────────────────────

    def bid_spread_summary(self, group_by: list = None) -> pd.DataFrame:
        """
        Bid spread statistics per segment.

        Spread = (winning_bid - clearing_price) / winning_bid. This measures
        how much of the winner's bid was "wasted" above what they had to pay.
        High spread = not very competitive; the winner could have bid lower.
        Low spread = tight competition, clearing price is close to the winning bid.

        I look at this by placement type first — top_of_search typically has
        tighter spreads because there are more bidders competing.
        """
        cols = group_by or ["placement_type"]
        return (
            self.auctions[self.auctions["filled"] == 1]
            .groupby(cols, observed=True)["bid_spread"]
            .agg(
                mean_spread="mean",
                median_spread="median",
                p10_spread=lambda x: x.quantile(0.1),
                p90_spread=lambda x: x.quantile(0.9),
                std_spread="std",
                n_auctions="count",
            )
            .round(4)
            .reset_index()
        )

    def bid_spread_over_time(self, freq: str = "D") -> pd.DataFrame:
        """Daily/weekly bid spread trends."""
        df = self.auctions[self.auctions["filled"] == 1].copy()
        df = df.set_index("timestamp")
        result = (
            df["bid_spread"]
            .resample(freq)
            .agg(["mean", "median", "std", "count"])
            .rename(
                columns={
                    "mean": "avg_spread",
                    "median": "p50_spread",
                    "std": "std_spread",
                    "count": "n_auctions",
                }
            )
            .round(4)
        )
        result.index.name = "timestamp"
        return result.reset_index()

    # ── Auction Depth ─────────────────────────────────────────────────────────

    def auction_depth_analysis(self) -> dict:
        """
        Analyze competition intensity (auction depth).

        Depth = number of bidders in an auction. More bidders generally means
        higher eCPM and tighter spreads, but the relationship is nonlinear —
        going from 2 to 4 bidders matters much more than going from 8 to 10.
        The depth bucket breakdown makes this visible.
        """
        df = self.auctions.copy()
        df["depth_bucket"] = pd.cut(
            df["auction_depth"],
            bins=[0, 2, 4, 6, 8, 100],
            labels=["2", "3-4", "5-6", "7-8", "9+"],
        )
        by_depth = (
            df.groupby("depth_bucket", observed=True)
            .agg(
                n_auctions=("auction_id", "count"),
                fill_rate=("filled", "mean"),
                avg_ecpm=("ecpm", "mean"),
                avg_winning_bid=("winning_bid_usd", "mean"),
                avg_bid_spread=("bid_spread", "mean"),
            )
            .round(4)
            .reset_index()
        )
        return {
            "summary": {
                "mean_depth": df["auction_depth"].mean(),
                "median_depth": df["auction_depth"].median(),
                "p25_depth": df["auction_depth"].quantile(0.25),
                "p75_depth": df["auction_depth"].quantile(0.75),
            },
            "by_depth_bucket": by_depth,
            "depth_distribution": df["auction_depth"].value_counts().sort_index(),
        }

    # ── Fill Rate ─────────────────────────────────────────────────────────────

    def fill_rate_analysis(self) -> pd.DataFrame:
        """Fill rate by placement x device x format."""
        return (
            self.auctions.groupby(
                ["placement_type", "device_type", "ad_format"], observed=True
            )
            .agg(
                n_auctions=("auction_id", "count"),
                fill_rate=("filled", "mean"),
                avg_floor_usd=("bid_floor_usd", "mean"),
                avg_winning_bid=("winning_bid_usd", "mean"),
                revenue_usd=("revenue_usd", "sum"),
            )
            .round(4)
            .reset_index()
            .sort_values("fill_rate", ascending=False)
        )

    def fill_rate_over_time(self, freq: str = "D") -> pd.DataFrame:
        """Detect fill rate degradation over time."""
        df = self.auctions.set_index("timestamp")
        result = (
            df["filled"]
            .resample(freq)
            .agg(fill_rate="mean", n_auctions="count")
            .round(4)
        )
        result.index.name = "timestamp"
        return result.reset_index()

    # ── eCPM and Revenue ──────────────────────────────────────────────────────

    def ecpm_percentiles(self, group_by: list = None) -> pd.DataFrame:
        """eCPM distribution by segment."""
        cols = group_by or ["placement_type", "ad_format"]
        return (
            self.auctions[self.auctions["filled"] == 1]
            .groupby(cols, observed=True)["ecpm"]
            .agg(
                p25=lambda x: x.quantile(0.25),
                p50=lambda x: x.quantile(0.50),
                p75=lambda x: x.quantile(0.75),
                p95=lambda x: x.quantile(0.95),
                mean="mean",
                n="count",
            )
            .round(2)
            .reset_index()
        )

    # ── Auction Structure Simulation ──────────────────────────────────────────

    def simulate_floor_price_change(
        self,
        new_floor_multiplier: float = 1.10,
        placement: Optional[str] = None,
    ) -> dict:
        """
        Simulate the revenue/fill tradeoff of changing bid floors.

        Raises floors -> some auctions that previously filled now don't (fill rate drops),
        but those that do fill generate higher clearing prices (revenue per fill goes up).
        The net effect on total revenue depends on the shape of the bid distribution.

        This applies counterfactual floor prices to historical bids — useful for
        sizing the impact before committing to a change in production. Caveat: it
        assumes advertiser bids don't change in response to the new floor, which
        isn't true long-term but is a reasonable first-pass estimate.
        """
        df = self.auctions.copy()
        mask = (
            (df["placement_type"] == placement)
            if placement
            else pd.Series(True, index=df.index)
        )

        new_floor = df.loc[mask, "bid_floor_usd"] * new_floor_multiplier
        still_filled = df.loc[mask, "winning_bid_usd"] >= new_floor

        baseline_fill = df.loc[mask, "filled"].mean()
        simulated_fill = still_filled.mean()
        baseline_rev = df.loc[mask, "revenue_usd"].sum()
        simulated_rev = df.loc[mask & still_filled, "revenue_usd"].sum()

        return {
            "floor_multiplier": new_floor_multiplier,
            "placement": placement or "all",
            "baseline_fill_rate": round(float(baseline_fill), 4),
            "simulated_fill_rate": round(float(simulated_fill), 4),
            "fill_rate_delta": round(float(simulated_fill - baseline_fill), 4),
            "baseline_revenue_usd": round(float(baseline_rev), 2),
            "simulated_revenue_usd": round(float(simulated_rev), 2),
            "revenue_delta_pct": (
                round(float((simulated_rev / baseline_rev - 1) * 100), 2)
                if baseline_rev
                else 0.0
            ),
            "n_auctions_affected": int(mask.sum()),
        }

    def simulate_auction_format_change(
        self, from_format: str = "second_price", to_format: str = "first_price"
    ) -> dict:
        """
        Estimate revenue impact of switching second-price -> first-price.

        In a second-price auction, the winner pays the second-highest bid (approximated
        here as 85-97% of the winning bid). In a first-price auction, they pay their
        own bid in full.

        This simulation assumes bids stay fixed, which won't be true — advertisers
        will shade their bids in a first-price format once they learn to. The note
        in the output flags this. Real first-price lift is typically 10-20% of
        what this simulation shows, after strategic adjustment.
        """
        df = self.auctions[self.auctions["filled"] == 1].copy()
        baseline_rev = df["clearing_price_usd"].sum()
        simulated_rev = df["winning_bid_usd"].sum()
        avg_spread = df["bid_spread"].mean()
        return {
            "from_format": from_format,
            "to_format": to_format,
            "baseline_revenue_usd": round(float(baseline_rev), 2),
            "simulated_revenue_usd": round(float(simulated_rev), 2),
            "revenue_lift_pct": round(
                float((simulated_rev / baseline_rev - 1) * 100), 2
            ),
            "avg_bid_spread": round(float(avg_spread), 4),
            "note": (
                "First-price auctions incentivize bid-shading; "
                "actual lift will be lower as advertisers adjust bids."
            ),
        }


class FeatureReleaseAnalyzer:
    """
    Causal measurement for feature releases.

    The core method is diff_in_diff — preferred over raw before/after
    comparisons because it controls for time trends by using a control group.
    If fill rate was already trending up seasonally, a naive before/after
    comparison would attribute that to the feature. DiD subtracts out whatever
    the control group did in the same period.

    Requires the auctions DataFrame to have been processed with
    generate_feature_release_data() so it has release_period and treatment columns.
    """

    def __init__(self, auctions: pd.DataFrame):
        self.auctions = auctions.copy()
        self.auctions["timestamp"] = pd.to_datetime(self.auctions["timestamp"])

    def diff_in_diff(
        self,
        metric: str = "fill_rate",
        treatment_col: str = "treatment",
        period_col: str = "release_period",
    ) -> dict:
        """
        Difference-in-Differences estimator.

        DiD = (post_treated - pre_treated) - (post_control - pre_control)

        The treatment column marks which auctions received the feature post-release,
        but we need both pre and post observations for both groups to run DiD.
        So we identify the *treatment group* by which placement types ever had
        treatment=1, then split by release_period. This gives us four cells:
        treated x pre, treated x post, control x pre, control x post.

        The t-test on post-period treated vs. pre-period treated gives a p-value,
        but treat it with caution on small samples — it has low power.
        """
        df = self.auctions.copy()

        if metric == "fill_rate":
            df["metric_val"] = df["filled"]
        elif metric == "ecpm":
            df["metric_val"] = df["ecpm"]
        elif metric == "revenue":
            df["metric_val"] = df["revenue_usd"]
        else:
            df["metric_val"] = df[metric]

        # treated_group = 1 for placements that receive the feature (in both periods)
        treated_placements = set(
            df.loc[df[treatment_col] == 1, "placement_type"].unique()
        )
        df["treated_group"] = df["placement_type"].isin(treated_placements).astype(int)

        groups = df.groupby(["treated_group", period_col], observed=True)[
            "metric_val"
        ].mean()

        try:
            pre_control = float(groups.get((0, "pre"), 0))
            post_control = float(groups.get((0, "post"), 0))
            pre_treated = float(groups.get((1, "pre"), 0))
            post_treated = float(groups.get((1, "post"), 0))
        except (KeyError, TypeError):
            return {"error": "Missing required treatment/period combinations"}

        did_estimate = (post_treated - pre_treated) - (post_control - pre_control)

        pre_vals = df[(df["treated_group"] == 1) & (df[period_col] == "pre")][
            "metric_val"
        ]
        post_vals = df[(df["treated_group"] == 1) & (df[period_col] == "post")][
            "metric_val"
        ]
        if len(pre_vals) < 2 or len(post_vals) < 2:
            t_stat, p_val = float("nan"), float("nan")
        else:
            t_stat, p_val = stats.ttest_ind(post_vals.dropna(), pre_vals.dropna())

        rel_lift = (
            round(float(did_estimate / pre_treated * 100), 2)
            if pre_treated != 0
            else 0.0
        )
        p_val_clean = round(float(p_val), 4) if p_val == p_val else None

        return {
            "metric": metric,
            "pre_control": round(pre_control, 4),
            "post_control": round(post_control, 4),
            "pre_treated": round(pre_treated, 4),
            "post_treated": round(post_treated, 4),
            "did_estimate": round(float(did_estimate), 4),
            "relative_lift_pct": rel_lift,
            "t_statistic": round(float(t_stat), 3) if t_stat == t_stat else None,
            "p_value": p_val_clean,
            "significant_at_5pct": (
                bool(p_val < 0.05) if p_val_clean is not None else None
            ),
        }

    def adoption_curve(self, freq: str = "D") -> pd.DataFrame:
        """Track feature adoption (treatment rate) over time."""
        df = self.auctions[self.auctions["release_period"] == "post"].copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return (
            df.groupby(pd.Grouper(key="timestamp", freq=freq))["treatment"]
            .agg(adoption_rate="mean", n_events="count")
            .round(4)
            .reset_index()
            .rename(columns={"timestamp": "period"})
        )
