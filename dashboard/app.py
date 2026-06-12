"""
Ads Science Analytics Platform — Streamlit Dashboard
Interactive analytics for ad auction insights, supply intelligence, and KPI monitoring.

Run with:
    streamlit run dashboard/app.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from data.generators.auction_data_generator import generate_all
from src.etl.transformers import AuctionTransformer, SupplyTransformer, KPITransformer
from src.analytics.auction_analytics import AuctionAnalyzer, FeatureReleaseAnalyzer
from src.analytics.supply_analytics import SupplyAnalyzer
from src.analytics.kpi_framework import KPIEngine

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Ads Science Analytics Platform",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Theme colors ──────────────────────────────────────────────────────────────
AMAZON_ORANGE = "#FF9900"
AMAZON_DARK = "#232F3E"
COLORS = px.colors.qualitative.Plotly


# ── Data loading ──────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Generating synthetic auction data…")
def load_data(n_auctions: int = 50_000, n_supply: int = 25_000, days: int = 90):
    raw = generate_all(
        n_advertisers=150, n_auctions=n_auctions, n_supply=n_supply, days=days
    )
    auctions = AuctionTransformer().transform(raw["auctions"])
    supply = SupplyTransformer().transform(raw["supply"])
    kpi_daily = KPITransformer().transform(
        auctions, ["date", "placement_type", "device_type", "ad_format"]
    )
    kpi_daily["date"] = pd.to_datetime(kpi_daily["date"])
    auctions["date"] = pd.to_datetime(auctions["date"])
    return auctions, supply, kpi_daily


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image(
        "https://upload.wikimedia.org/wikipedia/commons/a/a9/Amazon_logo.svg", width=120
    )
    st.markdown("## Ads Science Analytics")
    st.markdown("---")

    n_auctions = st.selectbox(
        "Dataset size",
        [10_000, 50_000, 100_000],
        index=1,
        format_func=lambda x: f"{x:,} auctions",
    )
    st.markdown("---")

    page = st.radio(
        "Navigation",
        [
            "📈 KPI Overview",
            "🏷️ Auction Analysis",
            "📦 Supply Intelligence",
            "🤖 Feature Release Impact",
            "🔍 Anomaly Monitor",
        ],
    )

auctions, supply, kpi_daily = load_data(n_auctions=n_auctions)
auction_analyzer = AuctionAnalyzer(auctions)
supply_analyzer = SupplyAnalyzer(supply, auctions)
kpi_engine = KPIEngine(auctions)
feature_analyzer = FeatureReleaseAnalyzer(auctions)


# ── Helper: metric card row ───────────────────────────────────────────────────
def metric_row(kpis: pd.DataFrame):
    cols = st.columns(len(kpis))
    for col, (_, row) in zip(cols, kpis.iterrows()):
        val = row["value"]
        if row["unit"] == "ratio":
            display = f"{val:.2%}"
        elif row["unit"] == "USD":
            display = f"${val:,.4f}" if val < 1 else f"${val:,.2f}"
        else:
            display = f"{val:.2f}"
        delta_color = "normal" if row["higher_is_better"] else "inverse"
        col.metric(
            label=row["kpi"].replace("_", " ").title(),
            value=display,
            delta=row["status"].upper(),
            delta_color=delta_color if row["status"] != "ok" else "off",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: KPI Overview
# ═══════════════════════════════════════════════════════════════════════════════
if page == "📈 KPI Overview":
    st.title("📈 Ads KPI Dashboard")
    st.caption(f"Platform overview · {len(auctions):,} auction events")

    # KPI cards
    kpis = kpi_engine.compute_all()
    core_kpis = kpis[
        kpis["kpi"].isin(
            ["fill_rate", "ecpm", "bid_spread", "ctr", "cvr", "auction_depth"]
        )
    ]
    metric_row(core_kpis)

    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        # Revenue over time
        rev_trend = kpi_daily.groupby("date")["total_revenue_usd"].sum().reset_index()
        fig = px.area(
            rev_trend,
            x="date",
            y="total_revenue_usd",
            title="Daily Revenue",
            color_discrete_sequence=[AMAZON_ORANGE],
        )
        fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Revenue (USD)")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        # Fill rate by placement
        fill_by_placement = (
            kpi_daily.groupby("placement_type")["fill_rate"]
            .mean()
            .sort_values(ascending=True)
            .reset_index()
        )
        fig = px.bar(
            fill_by_placement,
            x="fill_rate",
            y="placement_type",
            orientation="h",
            title="Avg Fill Rate by Placement",
            color="fill_rate",
            color_continuous_scale="Blues",
        )
        fig.update_layout(
            yaxis_title="", xaxis_title="Fill Rate", coloraxis_showscale=False
        )
        st.plotly_chart(fig, use_container_width=True)

    # KPI table
    st.subheader("Full KPI Scorecard")
    st.dataframe(
        kpis[
            ["kpi", "value", "unit", "target", "status", "category", "description"]
        ].style.applymap(
            lambda v: (
                "background-color: #ffcccc"
                if v == "alert"
                else ("background-color: #ccffcc" if v == "on_target" else "")
            ),
            subset=["status"],
        ),
        use_container_width=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: Auction Analysis
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🏷️ Auction Analysis":
    st.title("🏷️ Auction Analysis")

    tab1, tab2, tab3 = st.tabs(
        ["Bid Spreads", "Auction Depth", "Floor Price Simulation"]
    )

    with tab1:
        st.subheader("Bid Spread Analysis")
        spread_summary = auction_analyzer.bid_spread_summary()
        st.dataframe(spread_summary, use_container_width=True)

        spread_trend = auction_analyzer.bid_spread_over_time()
        fig = px.line(
            spread_trend,
            x="timestamp",
            y=["avg_spread", "p50_spread"],
            title="Bid Spread Trend Over Time",
            labels={"value": "Bid Spread", "timestamp": "Date"},
        )
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        st.subheader("Auction Depth")
        depth_analysis = auction_analyzer.auction_depth_analysis()

        c1, c2, c3 = st.columns(3)
        c1.metric("Mean Depth", f"{depth_analysis['summary']['mean_depth']:.1f}")
        c2.metric("Median Depth", f"{depth_analysis['summary']['median_depth']:.0f}")
        c3.metric("P75 Depth", f"{depth_analysis['summary']['p75_depth']:.0f}")

        by_depth = depth_analysis["by_depth_bucket"]
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(
            go.Bar(
                x=by_depth["depth_bucket"],
                y=by_depth["avg_ecpm"],
                name="Avg eCPM",
                marker_color=AMAZON_ORANGE,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=by_depth["depth_bucket"],
                y=by_depth["fill_rate"],
                name="Fill Rate",
                mode="lines+markers",
                line=dict(color="#1f77b4", width=2),
            ),
            secondary_y=True,
        )
        fig.update_layout(title="eCPM and Fill Rate by Auction Depth")
        st.plotly_chart(fig, use_container_width=True)

    with tab3:
        st.subheader("Floor Price Impact Simulation")
        placement = st.selectbox("Placement", auctions["placement_type"].unique())
        multiplier = st.slider("Floor price multiplier", 0.8, 2.0, 1.1, 0.05)
        sim = auction_analyzer.simulate_floor_price_change(multiplier, placement)

        c1, c2, c3 = st.columns(3)
        c1.metric("Baseline Fill Rate", f"{sim['baseline_fill_rate']:.2%}")
        c2.metric(
            "Simulated Fill Rate",
            f"{sim['simulated_fill_rate']:.2%}",
            delta=f"{sim['fill_rate_delta']:.2%}",
        )
        c3.metric("Revenue Δ", f"{sim['revenue_delta_pct']:+.1f}%")

        st.info(
            f"Raising floors {(multiplier-1)*100:.0f}% on **{placement}** → "
            f"fill rate changes by {sim['fill_rate_delta']:.2%} "
            f"and revenue changes by {sim['revenue_delta_pct']:+.1f}%."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: Supply Intelligence
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📦 Supply Intelligence":
    st.title("📦 Supply Intelligence")

    health = supply_analyzer.inventory_health()
    st.subheader("Inventory Health by Placement × Device")
    fig = px.scatter(
        health,
        x="avg_fill_rate",
        y="avg_supply_health",
        size="total_supply_events",
        color="placement_type",
        hover_data=["device_type", "avg_floor_price"],
        title="Supply Health vs Fill Rate",
        labels={"avg_fill_rate": "Fill Rate", "avg_supply_health": "Health Score"},
    )
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Floor Price Sensitivity")
    placement = st.selectbox(
        "Select placement",
        supply.get("placement_type", auctions["placement_type"]).unique(),
        key="supply_placement",
    )
    try:
        sensitivity = supply_analyzer.floor_price_sensitivity(placement)
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(
            go.Scatter(
                x=sensitivity["floor_usd"],
                y=sensitivity["fill_rate"],
                name="Fill Rate",
                line=dict(color="#1f77b4"),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=sensitivity["floor_usd"],
                y=sensitivity["expected_rev_per_auction"],
                name="Rev/Auction",
                line=dict(color=AMAZON_ORANGE),
            ),
            secondary_y=True,
        )
        opt = sensitivity[sensitivity["is_optimal_floor"]]
        if len(opt):
            fig.add_vline(
                x=opt["floor_usd"].iloc[0],
                line_dash="dash",
                annotation_text=f"Optimal floor: ${opt['floor_usd'].iloc[0]:.3f}",
            )
        fig.update_layout(title=f"Floor Price Sensitivity — {placement}")
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.warning(f"Could not compute sensitivity: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: Feature Release Impact
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🤖 Feature Release Impact":
    st.title("🤖 Feature Release Impact Analysis")
    st.caption("Difference-in-Differences analysis of feature release v2.0")

    metric = st.selectbox("Metric", ["fill_rate", "ecpm", "revenue"])
    results = feature_analyzer.diff_in_diff(metric=metric)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pre (Treated)", f"{results['pre_treated']:.4f}")
    c2.metric("Post (Treated)", f"{results['post_treated']:.4f}")
    c3.metric(
        "DiD Estimate",
        f"{results['did_estimate']:.4f}",
        delta=f"{results['relative_lift_pct']:+.1f}%",
    )
    c4.metric(
        "p-value",
        f"{results['p_value']:.4f}",
        delta="Significant ✓" if results["significant_at_5pct"] else "Not significant",
    )

    # Parallel trends chart
    df_plot = pd.DataFrame(
        [
            {"group": "Control (pre)", "value": results["pre_control"]},
            {"group": "Control (post)", "value": results["post_control"]},
            {"group": "Treated (pre)", "value": results["pre_treated"]},
            {"group": "Treated (post)", "value": results["post_treated"]},
        ]
    )

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=["Pre", "Post"],
            y=[results["pre_control"], results["post_control"]],
            name="Control",
            mode="lines+markers",
            line=dict(color="#1f77b4", dash="dash"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=["Pre", "Post"],
            y=[results["pre_treated"], results["post_treated"]],
            name="Treated",
            mode="lines+markers",
            line=dict(color=AMAZON_ORANGE, width=3),
        )
    )
    fig.update_layout(
        title=f"DiD — {metric} (Feature v2.0)", yaxis_title=metric, xaxis_title="Period"
    )
    st.plotly_chart(fig, use_container_width=True)

    st.json(results)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: Anomaly Monitor
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🔍 Anomaly Monitor":
    st.title("🔍 Anomaly Monitor")

    from src.models.anomaly_detector import MLAnomalyDetector, BidAnomalyMonitor

    @st.cache_resource
    def train_anomaly_detector(_auctions):
        detector = MLAnomalyDetector(contamination=0.02)
        return detector.fit(_auctions)

    detector = train_anomaly_detector(auctions)
    result = detector.predict(auctions)
    summary = detector.anomaly_summary(auctions)

    st.subheader("Anomaly Rate by Placement × Device")
    fig = px.bar(
        summary,
        x="placement_type",
        y="anomaly_rate",
        color="device_type",
        barmode="group",
        title="Anomaly Rate by Placement and Device",
        labels={"anomaly_rate": "Anomaly Rate"},
    )
    st.plotly_chart(fig, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Anomalous Auctions")
        anomalies = result[result["is_anomaly"]].sort_values(
            "anomaly_score", ascending=False
        )
        st.dataframe(
            anomalies[
                [
                    "auction_id",
                    "placement_type",
                    "device_type",
                    "winning_bid_usd",
                    "ecpm",
                    "bid_spread",
                    "anomaly_score",
                ]
            ].head(20),
            use_container_width=True,
        )
    with c2:
        st.subheader("Score Distribution")
        fig = px.histogram(
            result,
            x="anomaly_score",
            color_discrete_sequence=[AMAZON_ORANGE],
            title="Anomaly Score Distribution",
            labels={"anomaly_score": "Anomaly Score"},
        )
        st.plotly_chart(fig, use_container_width=True)

    # Bid monitor
    st.subheader("Bid Anomaly Monitor")
    monitor = BidAnomalyMonitor(z_threshold=3.0).fit(auctions)
    scored = monitor.score(auctions)
    bid_anomalies = scored[scored["bid_is_anomaly"]].sort_values(
        "bid_z_score", ascending=False
    )
    st.metric(
        "Bid Anomalies Detected",
        f"{len(bid_anomalies):,}",
        delta=f"{len(bid_anomalies)/len(auctions):.2%} of auctions",
    )
    st.dataframe(
        bid_anomalies[
            [
                "auction_id",
                "placement_type",
                "device_type",
                "winning_bid_usd",
                "bid_floor_usd",
                "bid_z_score",
            ]
        ].head(15),
        use_container_width=True,
    )
