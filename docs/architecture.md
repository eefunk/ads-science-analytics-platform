# Architecture Deep-Dive

This doc covers the key design decisions in the platform — not just *what* was built but *why*, including where I considered alternatives and what tradeoffs pushed me in a particular direction.

---

## Data Layer: Star Schema vs. Wide Tables

The warehouse uses a star schema with separate fact and dimension tables rather than a single denormalized wide table. This was a deliberate tradeoff.

**Wide table pros:** Simpler queries (no joins), faster for columnar engines, easier to explain to non-engineers.

**Star schema pros:** Dimension attributes can change over time without rewriting fact rows. Adding a new advertiser attribute (say, `verified_brand`) is a `ALTER TABLE dim_advertiser ADD COLUMN` rather than a full table rebuild. Query patterns that slice facts along multiple independent dimensions (placement × device × ad format × advertiser tier) are cleaner when each dimension is its own table.

For an ads analytics platform where advertiser properties, campaign structures, and placement configurations all evolve independently, the star schema flexibility wins.

**Schema overview:**

```
fact_auctions ──→ dim_advertiser
      │       ──→ dim_campaign
      │       ──→ dim_placement
      └───────→ dim_date

fact_supply   ──→ dim_placement
              ──→ dim_date

kpi_daily     (pre-aggregated KPI snapshots)
kpi_hourly    (higher-granularity for intraday monitoring)
```

The `kpi_daily` and `kpi_hourly` tables are derived from `fact_auctions` rather than computed on-the-fly. This matters for dashboard performance — aggregating 100M+ auction rows on every page load isn't viable. Pre-aggregation trades storage for query speed.

---

## ETL: Pluggable Extractors

The extract stage uses an abstract interface so the same transform + load logic works regardless of data source:

```python
class BaseExtractor:
    def extract(self) -> pd.DataFrame: ...
```

In this repo the implementations are CSV, SQLite, and in-memory (for tests). In production these would be replaced by S3/Parquet, Redshift UNLOAD, or a Kinesis consumer — without touching any downstream code.

The transform stage does more than just clean data. `AuctionTransformer` also engineers features that appear multiple times downstream (bid_spread, bid_z_score per placement, time features). Computing these once during ETL is more reliable than recomputing them inconsistently across different analytical modules.

---

## KPI Framework: One Definition, Many Consumers

The `KPIDefinition` dataclass pattern was influenced by how metrics platforms like Airbnb's Minerva or Lyft's Amundsen approach metric standardization. The core idea: a KPI should have exactly one canonical definition, and every consumer — dashboard, alert, report, email — should reference that definition rather than hardcoding the formula.

```python
@dataclass
class KPIDefinition:
    name: str
    formula: Callable[[pd.DataFrame], float]
    target: float
    alert_threshold: float
    unit: str
    owner: str
    description: str
```

The `KPIEngine` takes a DataFrame and a list of `KPIDefinition` objects and produces a standardized output. Adding a new KPI is registering a new definition — the rest of the infrastructure picks it up automatically.

This design also makes it trivial to compute KPIs for any segment: `engine.compute_all(segment={"placement_type": "top_of_search"})` filters the DataFrame before applying formulas, so you get segment-specific KPIs without writing new code.

---

## Auction Analytics: Simulation vs. Observation

A core tension in ads analytics is that you can observe the auctions that happened, but the most interesting questions are counterfactual: *what would have happened if we'd raised the floor price?*

The `simulate_floor_price_change` and `simulate_auction_format_change` methods answer these by applying counterfactual logic to the observed auction dataset. For floor simulation, it re-evaluates fill decisions using the new floor against the same historical bids. This isn't perfect (advertiser behavior would adapt to a new floor over time), but it gives a directionally correct estimate of the revenue/fill tradeoff.

For auction format (second-price → first-price): in a second-price auction, the winner pays the second-highest bid. In a first-price auction, they pay their own bid. The simulation estimates the revenue difference by comparing clearing prices under each model, holding bids fixed. Again, this ignores strategic bid shading that would happen in practice, but it's a useful first-pass estimate.

---

## Causal Inference: Why DiD

Measuring the impact of a feature release requires answering a causal question: did the feature *cause* the improvement, or was fill rate already trending up?

**Before/after comparison** (naive): compare the metric before and after the release for the treated group. Problem: confounds seasonal trends, algorithm drift, external market changes.

**A/B testing**: random assignment eliminates confounding. Problem: not always possible post-hoc, and some features can't be cleanly randomized across users or placements.

**Difference-in-Differences**: uses a control group (placements not affected by the feature) to estimate what would have happened to the treatment group if the feature hadn't shipped. The DiD estimator is:

```
DiD = (Treatment_post - Treatment_pre) - (Control_post - Control_pre)
```

The key assumption is "parallel trends" — that without the treatment, both groups would have changed by the same amount. You can partially check this by looking at pre-period trends for both groups. If they were moving together before the release, it's more credible that any post-release divergence is due to the feature.

The implementation in `FeatureReleaseAnalyzer` also runs a t-test on the post-period treated vs. control groups to provide a p-value. On small samples this can be unreliable (low power), but with production-scale auction data it becomes useful.

---

## ML Models: Design Choices

### Fill Rate Prediction (GBT Classifier)

**Why not logistic regression?** The relationship between bid floor and fill probability is nonlinear — there's a relatively flat middle region and steep dropoffs at extremes. Logistic regression would require polynomial or interaction features to capture this; GBT handles it automatically.

**Why not a neural network?** For tabular data with ~10 features, GBT consistently outperforms NNs in practice (see the XGBoost vs. deep learning comparison literature from Kaggle competitions). GBT is also easier to interpret via feature importances, which matters when you're explaining to an engineering team why the model thinks a particular auction is likely to fill.

**Feature engineering:** The model uses placement type, device type, ad format, category (categorical, one-hot encoded) plus bid floor, winning bid, auction depth, eCPM, and hour of day (numeric, StandardScaled). Placing everything through a `Pipeline` with `ColumnTransformer` ensures that the same preprocessing is applied at both training and inference time — a common source of training/serving skew if not handled carefully.

### eCPM Prediction (GBT Regressor + log1p)

eCPM has a heavy right tail (top-of-search premium placements can be 10-20x higher than off-Amazon). Training a regressor on raw eCPM would cause the model to overfit to high-value outliers and perform poorly on average-value auctions.

The `log1p` transform compresses the right tail before training and `expm1` inverts it after prediction. This is standard practice for revenue/price prediction tasks.

### Anomaly Detection: Two-Layer Approach

**Statistical detector (Z-score/IQR):** Fast, interpretable, easy to explain. "This bid was 4.2 standard deviations above the placement mean" is something you can put in an alert email. Works best for single-dimensional outliers with roughly Gaussian distributions.

**Isolation Forest:** Better for high-dimensional anomalies that don't stand out on any single feature but are unusual in combination. A bid that's slightly high *and* the auction depth is unusually low *and* it's 3am *and* it's from an advertiser that normally bids on mobile: each signal is borderline, but together they're suspicious. Isolation Forest catches this; Z-score doesn't.

In practice, both detectors run and the results are unioned — different tools for different failure modes.

---

## What's Missing (Intentionally)

**Streaming ingestion:** The ETL is batch-oriented. Production ads systems would use Kinesis/Kafka for real-time auction data with latencies in the seconds. Batch is appropriate here for analytical workloads; I'd add a streaming layer for the anomaly detection use case specifically.

**Slowly-changing dimensions:** The `dim_advertiser` table doesn't track historical attribute changes. If an advertiser moves from "mid" to "large" tier, that change overwrites the history. Type 2 SCD (adding `valid_from`/`valid_to` columns) would fix this but adds significant complexity to the ETL.

**Model serving:** The ML models are trained offline and pickled. A production setup would have them behind a low-latency serving layer (e.g., a FastAPI endpoint with in-memory model caching) with A/B traffic splitting for model comparison.

**Parallel trends test:** The DiD implementation doesn't include a formal test of the parallel trends assumption (comparing pre-period slopes between treatment and control). This should be in the dashboard's Feature Release page as a diagnostic.
