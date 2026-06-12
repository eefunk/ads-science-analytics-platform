# Dev Notes & Design Journal

Running log of decisions, dead ends, and things I learned while building this. Mostly for my own reference, but also useful if you're trying to understand *why* the code looks the way it does.

---

## Why I built this

I kept running into the same problem when reading about ad tech: the explanations are either too abstract ("auctions clear at the second-highest bid") or too implementation-specific to be useful without internal access. I wanted to build something that actually runs end-to-end so I could see how the pieces connect — what happens to fill rate when you change a floor, what the bid spread distribution actually looks like across placements, whether DiD is actually the right tool for measuring feature releases.

Short answer: yes it is, and the math matters more than I expected.

---

## Data generator

**Getting fill rates right took longer than expected.**

My first version had a bug where I clipped winning bids *up* to the floor value, which meant every auction cleared. Fill rate was 100%. Obvious in retrospect, but I spent a while confused about why my floor simulation showed zero effect.

The fix was to model the bid as `target_bid × pacing_factor` where `pacing_factor ~ Beta(5, 2)`. Beta(5, 2) has mean ~0.71, which gives you realistic ~65-75% fill rates across placements since some bids will naturally fall below the floor. This also means the floor simulation actually does something, because raising floors cuts into the lower tail of the pacing distribution.

The `generate_feature_release_data` function injects a ~8% lift in fill rate for the treated placement types post-release. The key was injecting the lift only on *unfilled* auctions (flipping some from 0 → 1), otherwise you end up with the treatment group already at 100% fill and the lift has nowhere to go.

**Bid floors by placement:**
- top_of_search: $0.35–$0.85 (premium inventory, higher floor makes sense)
- rest_of_search: $0.15–$0.45
- product_detail_page: $0.10–$0.35
- off_amazon: $0.05–$0.20

These are made up but roughly in line with what publicly available data suggests for CPCs at these placements.

---

## ETL pipeline

The pluggable extractor pattern (CSVExtractor, SQLiteExtractor, InMemoryExtractor all sharing the same interface) was a deliberate choice. In practice, you'd be pulling from Kinesis/S3/Redshift, but having a clean `extract()` → `transform()` → `load()` contract means you can swap the source without touching the transform logic.

The `AuctionTransformer` computes a few things worth explaining:
- **bid_spread** = `(winning_bid - clearing_price) / winning_bid` — measures how much of the winner's bid was "surplus" above what they had to pay. High spread = auction isn't very competitive.
- **bid_z_score** — computed per-placement, not globally. A $2.00 bid is normal on top_of_search and suspicious on off_amazon. Grouping by placement before computing z-scores is important.

The KPI transformer aggregates to daily grain by default, but it's configurable. I went with `["date", "placement_type", "device_type", "ad_format"]` as the default group-by because that's the level at which you'd typically want to drill in from a dashboard.

---

## Star schema design

I went back and forth on whether to use a wide flat table or a proper star schema. Wide tables are simpler and faster for one-off queries, but they make it hard to add new dimensions without schema migrations. The star schema made more sense here because:

1. Advertiser and campaign attributes change over time (slow-changing dimensions) and I didn't want them baked into every fact row
2. `dim_date` lets me add fiscal calendar, holiday flags, etc. without touching fact tables
3. The query patterns (slice fill rate by placement, then by device, then by advertiser tier) fit naturally into join + filter

The tradeoff is query complexity — every analysis needs joins. The SQL analytics queries in `sql/analytics/` are all pre-written to handle this.

---

## KPI framework

The `KPIDefinition` dataclass is the core of this. Every KPI is defined with:
- `formula` — a function that takes the auction DataFrame and returns a number
- `target` — what "good" looks like
- `alert_threshold` — when to page someone
- `owner` — who's responsible

The point of centralizing this is metric drift. If the dashboard computes fill rate one way and the weekly report computes it another way, you end up with two numbers that disagree and nobody trusts either. One definition, referenced everywhere.

The 8 KPIs I settled on: fill_rate, ecpm, bid_spread, ctr, cvr, auction_depth, revenue_per_auction, below_floor_rate. There's an argument for adding more (impression share, budget utilization, identity match rate) but I wanted to start with the core set and see how they interact before expanding.

---

## Diff-in-differences

This one required the most thought to get right.

The naive approach: compare fill rate before vs. after the release for the treated placement types. Problem: if fill rate was already trending up (seasonal effect, algorithm improvements elsewhere), you'll overestimate the impact of your feature.

DiD controls for this by asking: "how did fill rate change in the treatment group, *relative to* how it changed in the control group?" If both groups were trending up at the same rate before the release, and then the treatment group accelerated after the release, that acceleration is your causal estimate.

The implementation identifies the treatment group by which placement types had `treatment=1` in the post period, then splits the data into four cells: treated×pre, treated×post, control×pre, control×post. The DiD estimate is `(T_post - T_pre) - (C_post - C_pre)`.

I also ran t-tests on the post-period to check whether the difference is statistically significant, not just directionally positive. With enough data it usually is, but on small samples the p-value can be unreliable (which is why the test handles `None` gracefully).

---

## ML models

**Why GBT over logistic regression for fill rate?**

I tried logistic regression first. The problem is that the relationship between bid_floor and fill rate is nonlinear — there's a relatively flat region in the middle and steep dropoffs at both ends. GBT handles this naturally without feature engineering. The ROC-AUC improvement was meaningful (~0.82 vs ~0.74 on this dataset).

The log1p transform on eCPM before regression is important because eCPM has a long right tail (high-quality top-of-search placements can have 10x the eCPM of off_amazon). Training a regressor directly on raw eCPM would cause the model to overfit to outliers. Log1p compresses the tail and makes the residuals more homoskedastic.

**Anomaly detection:**

I ended up with two detectors because they catch different things:
- `StatisticalAnomalyDetector` (Z-score/IQR) — good for detecting single-dimension outliers, easy to explain to stakeholders ("the bid was 4 standard deviations above the placement mean")
- `MLAnomalyDetector` (Isolation Forest) — better for catching multi-dimensional anomalies that don't look suspicious on any single axis but are unusual when you consider all features together

In practice you'd probably run both and union the results.

---

## Things I'd do differently

- **Async ETL** — the current pipeline is sequential. For production data volumes you'd want concurrent extraction and possibly streaming transforms (Spark or Flink rather than pandas).
- **More realistic bid dynamics** — real auctions have per-advertiser budget pacing that creates intraday patterns. The current generator doesn't model this (each auction is IID), which means the time series is too smooth.
- **Proper SCD handling** — the `dim_advertiser` table doesn't implement slowly-changing dimensions. In a real warehouse you'd want type 2 SCD to track how advertiser budgets/strategies change over time.
- **Feature store** — the ML models recompute features from raw data every time. A proper setup would have a feature store so training and serving use identical feature definitions.
- **More rigorous DiD assumptions** — the parallel trends assumption is untestable but you can check pre-period trends visually. I didn't add that visualization to the dashboard, but it should be there.

---

## Resources that helped

- Preston McAfee's *Introduction to Economic Analysis* — clear explanation of auction theory and second-price mechanics
- Susan Athey & Guido Imbens on DiD with staggered treatment timing — more rigorous than what I implemented but good for understanding the assumptions
- The Airbnb engineering blog posts on their KPI framework — influenced the `KPIDefinition` registry design
