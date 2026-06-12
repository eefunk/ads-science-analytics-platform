# Contributing

Thanks for taking a look. This is primarily a personal project but I'm happy to take PRs for bug fixes, improvements to the analytics logic, or new features that fit naturally with the auction analytics focus.

---

## What I'd welcome

- **New analytics methods** — anything auction-related: bid shading analysis, budget pacing curves, multi-touch attribution, intraday traffic patterns
- **Better synthetic data** — the generator is pretty simple right now. Realistic intraday pacing cycles, seasonality, or budget exhaustion dynamics would make the simulations more useful
- **Additional KPI definitions** — I've been conservative about adding KPIs to keep the registry manageable, but there are obvious gaps (impression share, budget utilization, identity match rate)
- **SQL improvements** — particularly around the WoW comparison queries and anything that adds fiscal calendar support
- **Bug fixes** — especially in the DiD implementation or the ML model feature pipelines

## What probably won't get merged

- Changes that break the existing 55 tests without a good reason
- New dependencies that aren't in the core stack (numpy, pandas, scikit-learn, streamlit, plotly)
- Anything that replaces the SQLite warehouse with a cloud-specific service — keeping this runnable locally is intentional

---

## Setup

```bash
git clone https://github.com/edenfunkk/ads-science-analytics-platform.git
cd ads-science-analytics-platform
python -m pip install -r requirements.txt
pytest tests/ -v  # make sure everything passes before you change anything
```

---

## Code style

I use `black` for formatting and `ruff` for linting. Both run in CI. Before opening a PR:

```bash
black src/ tests/ data/
ruff check src/ tests/ data/
```

If ruff flags something you disagree with, just add a `# noqa` with a comment explaining why — I'm not rigid about it.

---

## Testing

Add a test for whatever you change. The existing test structure is in `tests/`:
- `test_etl.py` — generator, transformer, loader
- `test_analytics.py` — AuctionAnalyzer, KPIEngine, FeatureReleaseAnalyzer, SupplyAnalyzer
- `test_models.py` — predictor and anomaly detector models

Use the `datasets` and `auctions` pytest fixtures from `test_analytics.py` for any analytics tests — they generate a shared module-scope dataset so tests don't each spin up 10K auctions independently.

---

## Opening a PR

- Keep PRs focused — one feature or fix per PR
- Include a short description of what you changed and why
- Make sure CI passes

That's pretty much it. Open an issue first if you're planning something big and want to check it's worth the effort.
