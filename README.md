# Ads Science Analytics Platform

[![CI](https://github.com/edenfunkk/ads-science-analytics-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/edenfunkk/ads-science-analytics-platform/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

I built this after spending a lot of time trying to understand how real ad auctions actually work — not the simplified textbook version, but the messy reality where bid floors vary by placement, pacing curves eat into fill rates, and "did this feature actually help?" is a genuinely hard question to answer without the right analytical scaffolding.

This repo is my attempt at building that scaffolding end-to-end: synthetic auction data that behaves realistically, an ETL pipeline to warehouse it, analytics modules to interrogate it, ML models to predict auction outcomes, and a dashboard to pull it all together.

---

## What it does

The core loop is:

1. **Generate** realistic auction data (bid floors, pacing, fill rates, feature release signals)
2. **ETL** it into a star-schema SQLite warehouse
3. **Analyze** bid spreads, fill rates, auction depth, supply-demand balance
4. **Measure** the causal impact of feature releases using difference-in-differences
5. **Predict** fill probability and expected eCPM with gradient-boosted models
6. **Monitor** for anomalies across bid prices, fill rates, and supply
7. **Explore** everything interactively in a Streamlit dashboard

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Ads Science Analytics Platform                    │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────────────┐   │
│  │ Data         │   │ ETL Pipeline │   │ Data Warehouse        │   │
│  │ Generators   │──▶│              │──▶│ (SQLite / star schema)│   │
│  │              │   │ Extract      │   │                       │   │
│  │ • Auctions   │   │ Transform    │   │ fact_auctions         │   │
│  │ • Supply     │   │ Load         │   │ fact_supply           │   │
│  │ • Campaigns  │   │              │   │ dim_advertiser        │   │
│  └──────────────┘   └──────────────┘   │ kpi_daily / hourly   │   │
│                                        └───────────────────────┘   │
│                                                    │                │
│  ┌─────────────────────────────────────────────────▼───────────┐   │
│  │                    Analytics Layer                          │   │
│  │                                                             │   │
│  │  AuctionAnalyzer    SupplyAnalyzer    KPIEngine             │   │
│  │  • Bid spread       • Fill rate       • 8 core KPIs        │   │
│  │  • Auction depth    • Floor price     • Alert thresholds   │   │
│  │  • Floor sims       • Supply health   • Trend analysis     │   │
│  │  • Format sims      • Demand balance  • Segment breakouts  │   │
│  │                                                             │   │
│  │  FeatureReleaseAnalyzer                                     │   │
│  │  • Diff-in-differences   • Adoption curves   • T-tests     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                    │                │
│  ┌─────────────────────────────────────────────────▼───────────┐   │
│  │                      ML Models                              │   │
│  │  FillRatePredictor   ECPMPredictor   MLAnomalyDetector      │   │
│  │  (GBT classifier)    (GBT regressor) (Isolation Forest)     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                    │                │
│  ┌─────────────────────────────────────────────────▼───────────┐   │
│  │              Streamlit Dashboard (5 pages)                  │   │
│  │  KPI Overview │ Auction Analysis │ Supply │ Feature Release │   │
│  │  │ Anomaly Monitor                                          │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
ads-science-analytics-platform/
├── data/
│   └── generators/
│       └── auction_data_generator.py   # Synthetic auction, supply & campaign data
├── src/
│   ├── etl/
│   │   ├── extractors.py               # CSV, SQLite, in-memory extractors
│   │   ├── transformers.py             # Auction, supply, KPI transformers
│   │   ├── loaders.py                  # SQLite loader with upsert support
│   │   └── pipeline.py                 # Orchestrated ETL pipeline
│   ├── analytics/
│   │   ├── auction_analytics.py        # Bid spread, depth, floor sims, DiD
│   │   ├── supply_analytics.py         # Fill rate, supply-demand balance
│   │   └── kpi_framework.py            # KPI registry, engine, alerting
│   └── models/
│       ├── auction_predictor.py        # Fill rate & eCPM prediction
│       └── anomaly_detector.py         # Statistical + ML anomaly detection
├── sql/
│   ├── ddl/create_tables.sql           # Star schema DDL
│   └── analytics/
│       ├── auction_depth.sql           # Depth distribution & elasticity
│       ├── bid_spreads.sql             # Spread analysis & surplus concentration
│       ├── fill_rate.sql               # Fill rate heatmaps, trends, floor sensitivity
│       └── kpi_dashboard.sql           # WoW KPI scorecard & revenue queries
├── dashboard/app.py                    # Streamlit interactive dashboard
├── tests/                              # pytest unit & integration tests (55 tests)
│   ├── test_etl.py
│   ├── test_analytics.py
│   └── test_models.py
├── docs/
│   ├── kpi_definitions.md              # Formalized KPI standards
│   └── architecture.md                 # Deep-dive on design decisions
├── NOTES.md                            # Dev journal — decisions, dead ends, lessons
└── .github/workflows/ci.yml           # GitHub Actions CI (Python 3.10/3.11/3.12)
```

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/edenfunkk/ads-science-analytics-platform.git
cd ads-science-analytics-platform

# 2. Install
python -m pip install -r requirements.txt

# 3. Generate data + run ETL
python src/etl/pipeline.py --generate --data-dir data/sample --db warehouse/ads.db

# 4. Launch dashboard
streamlit run dashboard/app.py

# 5. Run tests
pytest tests/ -v --cov=src
```

---

## Using the Analytics Modules

```python
from data.generators.auction_data_generator import generate_all
from src.etl.transformers import AuctionTransformer
from src.analytics.auction_analytics import AuctionAnalyzer, FeatureReleaseAnalyzer
from src.analytics.kpi_framework import KPIEngine

datasets = generate_all(n_advertisers=200, n_auctions=100_000, days=90)
auctions = AuctionTransformer().transform(datasets["auctions"])

analyzer = AuctionAnalyzer(auctions)

# Bid spread by placement type
print(analyzer.bid_spread_summary())

# What happens to revenue and fill rate if we raise floors 10%?
print(analyzer.simulate_floor_price_change(new_floor_multiplier=1.10))

# Causal impact of a feature release (diff-in-differences)
fra = FeatureReleaseAnalyzer(auctions)
print(fra.diff_in_diff(metric="fill_rate"))

# KPI dashboard with alerts
engine = KPIEngine(auctions)
print(engine.compute_all())
print(engine.alerts())
```

---

## Auction Analytics

| Analysis | What it answers |
|---|---|
| **Bid spread** | Where is value leaking between winning bid and clearing price? |
| **Auction depth** | Does more competition actually improve eCPM? (It does, nonlinearly) |
| **Fill rate** | Which placement × device combos are underperforming and why? |
| **Floor simulation** | If we raise floors 15%, what's the revenue/fill tradeoff before we ship? |
| **Format simulation** | How much more revenue would first-price collect vs. second-price? |

---

## KPI Framework

Eight KPIs with formal definitions, targets, alert thresholds, and owners. The point was to make sure every downstream consumer — dashboards, alerts, reports — is using the exact same definition of "fill rate" rather than each team computing it slightly differently. See [`docs/kpi_definitions.md`](docs/kpi_definitions.md) for the full registry.

---

## Feature Release Measurement

The `FeatureReleaseAnalyzer` implements difference-in-differences estimation. Raw before/after comparisons get contaminated by seasonal trends; DiD controls for that by isolating the treatment effect using a control group that experienced everything except the feature. The result is a credible causal estimate rather than a correlation.

---

## ML Models

| Model | Algorithm | Purpose |
|---|---|---|
| `FillRatePredictor` | Gradient Boosted Trees | P(fill) — helps bidding algorithms decide when and how much to bid |
| `ECPMPredictor` | GBT + log1p transform | Expected eCPM — feeds budget pacing and bid optimization |
| `MLAnomalyDetector` | Isolation Forest | Flags unusual auction clusters across multiple dimensions simultaneously |
| `BidAnomalyMonitor` | Rolling Z-score per placement | Real-time detection of bid price spikes or drops |

---

## Tests

55 tests across ETL, analytics, and models. CI runs on Python 3.10, 3.11, and 3.12.

```bash
pytest tests/ -v --cov=src --cov-report=term-missing
```

---

## SQL

Production-style analytical SQL queries, runnable against the generated warehouse:

```bash
sqlite3 warehouse/ads.db < sql/analytics/bid_spreads.sql
sqlite3 warehouse/ads.db < sql/analytics/fill_rate.sql
sqlite3 warehouse/ads.db < sql/analytics/kpi_dashboard.sql
```

---

## Design notes

If you want the full story on why I made specific choices — star schema over wide tables, DiD over raw A/B, GBT over logistic regression for fill prediction — it's all in [`NOTES.md`](NOTES.md) and [`docs/architecture.md`](docs/architecture.md).

---

## License

MIT
                                                                                                                    