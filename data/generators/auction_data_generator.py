"""
Synthetic Ad Auction Data Generator
Simulates realistic Amazon-style ad auction events including bid requests,
responses, wins/losses, impression delivery, and campaign performance metrics.
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
import random
import hashlib

# ── Reproducibility ──────────────────────────────────────────────────────────
RNG = np.random.default_rng(42)
random.seed(42)


# ── Constants ─────────────────────────────────────────────────────────────────
AD_FORMATS = [
    "sponsored_product",
    "sponsored_brand",
    "sponsored_display",
    "dsp_display",
]
DEVICE_TYPES = ["desktop", "mobile", "tablet", "ctv"]
PLACEMENT_TYPES = [
    "top_of_search",
    "rest_of_search",
    "product_detail_page",
    "off_amazon",
]
CATEGORIES = [
    "electronics",
    "apparel",
    "home_kitchen",
    "beauty",
    "sports",
    "books",
    "toys",
    "automotive",
    "grocery",
    "health",
]
BIDDER_STRATEGIES = ["target_cpa", "target_roas", "maximize_clicks", "manual_cpc"]

# Realistic bid floor ranges by placement (in USD)
BID_FLOORS = {
    "top_of_search": (0.35, 0.85),
    "rest_of_search": (0.15, 0.45),
    "product_detail_page": (0.10, 0.35),
    "off_amazon": (0.05, 0.20),
}


# ── Helpers ──────────────────────────────────────────────────────────────────
def _uid(prefix: str, idx: int) -> str:
    h = hashlib.md5(f"{prefix}-{idx}".encode()).hexdigest()[:8]
    return f"{prefix}_{h}"


def _lognormal(mean: float, sigma: float, n: int) -> np.ndarray:
    return RNG.lognormal(np.log(mean), sigma, n)


# ── Advertisers ──────────────────────────────────────────────────────────────
def generate_advertisers(n: int = 500) -> pd.DataFrame:
    """Generate a pool of advertisers with realistic budget distributions."""
    tiers = RNG.choice(
        ["small", "mid", "large", "enterprise"], n, p=[0.55, 0.28, 0.12, 0.05]
    )
    budgets = {
        "small": (50, 500),
        "mid": (500, 5_000),
        "large": (5_000, 50_000),
        "enterprise": (50_000, 500_000),
    }
    daily_budgets = np.array([RNG.uniform(*budgets[t]) for t in tiers])
    return pd.DataFrame(
        {
            "advertiser_id": [_uid("adv", i) for i in range(n)],
            "tier": tiers,
            "category": RNG.choice(CATEGORIES, n),
            "daily_budget_usd": daily_budgets.round(2),
            "bidding_strategy": RNG.choice(BIDDER_STRATEGIES, n),
            "target_cpc_usd": _lognormal(0.45, 0.6, n).round(3),
            "quality_score": RNG.uniform(3.0, 10.0, n).round(2),
            "identity_match_rate": RNG.beta(7, 3, n).round(4),
        }
    )


# ── Campaigns ────────────────────────────────────────────────────────────────
def generate_campaigns(
    advertisers: pd.DataFrame, campaigns_per_adv: int = 3
) -> pd.DataFrame:
    """Generate campaigns linked to advertisers."""
    rows = []
    for _, adv in advertisers.iterrows():
        n_campaigns = RNG.integers(1, campaigns_per_adv + 1)
        for _ in range(n_campaigns):
            rows.append(
                {
                    "campaign_id": _uid("cmp", len(rows)),
                    "advertiser_id": adv["advertiser_id"],
                    "ad_format": RNG.choice(AD_FORMATS),
                    "category": adv["category"],
                    "daily_budget_usd": (adv["daily_budget_usd"] / n_campaigns).round(
                        2
                    ),
                    "target_bid_usd": float(adv["target_cpc_usd"])
                    * float(RNG.uniform(0.8, 1.4)),
                    "quality_score": float(adv["quality_score"])
                    + float(RNG.normal(0, 0.5)),
                    "relevance_score": float(RNG.beta(6, 4)),
                }
            )
    df = pd.DataFrame(rows)
    df["quality_score"] = df["quality_score"].clip(1, 10).round(2)
    df["relevance_score"] = df["relevance_score"].round(4)
    df["target_bid_usd"] = df["target_bid_usd"].round(3)
    return df


# ── Auction Events ────────────────────────────────────────────────────────────
def generate_auction_events(
    campaigns: pd.DataFrame,
    n_auctions: int = 100_000,
    start_date: datetime = datetime(2024, 1, 1),
    days: int = 90,
) -> pd.DataFrame:
    """
    Generate auction-level events.

    Each row = one bid request. The winning bid is determined by eCPM.
    Pacing factor (Beta distribution) creates realistic ~70-80% fill rates.
    """
    n = n_auctions
    end_ts = start_date + timedelta(days=days)
    timestamps = pd.to_datetime(
        RNG.uniform(start_date.timestamp(), end_ts.timestamp(), n), unit="s"
    )

    placements = RNG.choice(PLACEMENT_TYPES, n, p=[0.25, 0.30, 0.30, 0.15])
    devices = RNG.choice(DEVICE_TYPES, n, p=[0.38, 0.45, 0.10, 0.07])
    auction_depths = RNG.integers(2, 13, n)

    win_idx = RNG.integers(0, len(campaigns), n)
    winning_campaigns = campaigns.iloc[win_idx].reset_index(drop=True)

    # Bid floors per placement
    floors = np.array([RNG.uniform(*BID_FLOORS[p]) for p in placements])

    # Winning bid = target_bid x pacing factor
    # Beta(5,2) pacing: mean ~0.71 — creates realistic ~70-80% fill rates
    pacing = RNG.beta(5, 2, n)
    winning_bids = (winning_campaigns["target_bid_usd"].values * pacing).clip(0.001)

    # Fill: auction clears if winning bid >= floor
    filled = (winning_bids >= floors).astype(int)

    # Clearing price = 85-97% of winning bid (second-price logic), 0 if unfilled
    clearing_prices = np.where(
        filled == 1,
        winning_bids * RNG.uniform(0.85, 0.97, n),
        0.0,
    )

    # Bid spread = (winning_bid - clearing_price) / winning_bid
    bid_spreads = np.where(
        filled == 1,
        (winning_bids - clearing_prices)
        / np.where(winning_bids > 0, winning_bids, 1.0),
        0.0,
    ).round(4)

    # eCPM
    ecpm = (
        winning_bids
        * winning_campaigns["quality_score"].values
        / 10.0
        * winning_campaigns["relevance_score"].values
        * 1000.0
    )

    # Click-through and conversion rates
    base_ctr = RNG.beta(2, 40, n)
    placement_ctr_boost = np.where(
        placements == "top_of_search",
        1.6,
        np.where(
            placements == "rest_of_search",
            1.0,
            np.where(placements == "product_detail_page", 0.8, 0.6),
        ),
    )
    ctrs = (base_ctr * placement_ctr_boost).clip(0, 1)
    clicks = RNG.binomial(1, ctrs)
    cvrs = RNG.beta(1, 30, n)
    conversions = clicks * RNG.binomial(1, cvrs)

    return pd.DataFrame(
        {
            "auction_id": [_uid("auc", i) for i in range(n)],
            "timestamp": timestamps,
            "date": timestamps.date,
            "hour": timestamps.hour,
            "placement_type": placements,
            "device_type": devices,
            "ad_format": winning_campaigns["ad_format"].values,
            "category": winning_campaigns["category"].values,
            "campaign_id": winning_campaigns["campaign_id"].values,
            "advertiser_id": winning_campaigns["advertiser_id"].values,
            "auction_depth": auction_depths,
            "bid_floor_usd": floors.round(4),
            "winning_bid_usd": winning_bids.round(4),
            "clearing_price_usd": clearing_prices.round(4),
            "bid_spread": bid_spreads,
            "ecpm": ecpm.round(2),
            "filled": filled,
            "clicked": clicks,
            "converted": conversions,
            "revenue_usd": (clearing_prices * filled).round(4),
        }
    )


# ── Supply Events ─────────────────────────────────────────────────────────────
def generate_supply_events(
    n: int = 50_000,
    start_date: datetime = datetime(2024, 1, 1),
    days: int = 90,
) -> pd.DataFrame:
    """Generate supply-side events (ad slot availability)."""
    end_ts = start_date + timedelta(days=days)
    timestamps = pd.to_datetime(
        RNG.uniform(start_date.timestamp(), end_ts.timestamp(), n), unit="s"
    )
    placements = RNG.choice(PLACEMENT_TYPES, n, p=[0.25, 0.30, 0.30, 0.15])
    fill_rates = np.array(
        [
            RNG.beta(
                *{
                    "top_of_search": (7, 2),
                    "rest_of_search": (8, 2),
                    "product_detail_page": (9, 1.5),
                    "off_amazon": (6, 3),
                }[p]
            )
            for p in placements
        ]
    )
    floor_prices = np.array([RNG.uniform(*BID_FLOORS[p]) for p in placements])
    return pd.DataFrame(
        {
            "supply_event_id": [_uid("sup", i) for i in range(n)],
            "timestamp": timestamps,
            "date": timestamps.date,
            "placement_type": placements,
            "device_type": RNG.choice(DEVICE_TYPES, n, p=[0.38, 0.45, 0.10, 0.07]),
            "available_slots": RNG.integers(1, 6, n),
            "fill_rate": fill_rates.round(4),
            "floor_price_usd": floor_prices.round(4),
            "page_load_ms": _lognormal(250, 0.4, n).clip(50, 3000).round(0).astype(int),
        }
    )


# ── Feature Release Impact ────────────────────────────────────────────────────
def generate_feature_release_data(
    auctions: pd.DataFrame,
    release_date: str = "2024-03-01",
    affected_placements: list = None,
) -> pd.DataFrame:
    """
    Simulate pre/post feature release data.
    Injects a lift signal in fill rate and eCPM for the treated group.
    """
    if affected_placements is None:
        affected_placements = ["top_of_search", "rest_of_search"]

    release_ts = pd.Timestamp(release_date)
    df = auctions.copy()
    df["release_period"] = np.where(df["timestamp"] >= release_ts, "post", "pre")
    df["treatment"] = (
        (df["timestamp"] >= release_ts)
        & (df["placement_type"].isin(affected_placements))
    ).astype(int)

    # Simulate lift: post-release improves fill rate ~8% for treated group
    lift_mask = (df["treatment"] == 1) & (df["filled"] == 0)
    n_lift = lift_mask.sum()
    if n_lift > 0:
        extra_fills = RNG.random(n_lift) < 0.08
        df.loc[lift_mask, "filled"] = extra_fills.astype(int)

    # eCPM lift for already-filled treated auctions
    filled_treated = (df["treatment"] == 1) & (df["filled"] == 1)
    n_ft = filled_treated.sum()
    if n_ft > 0:
        df.loc[filled_treated, "ecpm"] = df.loc[filled_treated, "ecpm"] * RNG.uniform(
            1.03, 1.12, n_ft
        )

    df.loc[df["filled"] == 1, "revenue_usd"] = (
        df.loc[df["filled"] == 1, "clearing_price_usd"]
    ).round(4)

    df["feature_version"] = np.where(df["treatment"] == 1, "v2.0", "v1.0")
    return df


# ── Master generator ──────────────────────────────────────────────────────────
def generate_all(
    n_advertisers: int = 200,
    n_auctions: int = 100_000,
    n_supply: int = 50_000,
    days: int = 90,
    output_dir: Optional[str] = None,
) -> dict:
    """Generate the complete dataset. Optionally write CSVs to output_dir."""
    print("Generating advertisers...")
    advertisers = generate_advertisers(n_advertisers)

    print("Generating campaigns...")
    campaigns = generate_campaigns(advertisers)

    print(f"Generating {n_auctions:,} auction events...")
    auctions = generate_auction_events(campaigns, n_auctions, days=days)

    print("Injecting feature release signal...")
    auctions = generate_feature_release_data(auctions)

    print(f"Generating {n_supply:,} supply events...")
    supply = generate_supply_events(n_supply, days=days)

    datasets = {
        "advertisers": advertisers,
        "campaigns": campaigns,
        "auctions": auctions,
        "supply": supply,
    }

    if output_dir:
        import os

        os.makedirs(output_dir, exist_ok=True)
        for name, df in datasets.items():
            path = os.path.join(output_dir, f"{name}.csv")
            df.to_csv(path, index=False)
            print(f"  -> Saved {path} ({len(df):,} rows)")

    print("Done.")
    return datasets


if __name__ == "__main__":
    import os

    out = os.path.join(os.path.dirname(__file__), "..", "sample")
    generate_all(output_dir=out)
