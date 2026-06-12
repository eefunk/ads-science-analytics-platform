# KPI Definitions & Standards

This document formalizes the KPIs used to measure ad serving system performance,
aligning with the Ads Science Product Team's analytics framework.

---

## Delivery KPIs

### Fill Rate
**Definition:** Fraction of auction requests that result in a delivered ad.  
**Formula:** `filled_auctions / total_auction_requests`  
**Target:** ≥ 85%  
**Alert threshold:** < 70%  
**Grain:** Placement × Device × Format, daily  
**Owner:** Ads Science — Supply Analytics  

Fill rate is the primary signal for supply health. Persistent drops indicate
floor price misalignment, reduced bidder competition, or data pipeline issues.

---

### Below-Floor Rate
**Definition:** Fraction of bids that do not meet the bid floor.  
**Formula:** `count(winning_bid < bid_floor) / total_auctions`  
**Target:** ≤ 5%  
**Alert threshold:** > 15%  

---

## Revenue KPIs

### eCPM (Effective CPM)
**Definition:** Revenue per 1,000 auction requests (including unfilled).  
**Formula:** `(total_revenue_usd / total_auctions) * 1000`  
**Unit:** USD  
**Grain:** Placement × Device, daily  
**Note:** eCPM is the primary revenue efficiency metric; it penalizes low fill rates.

### Revenue Per Auction (RPA)
**Formula:** `total_clearing_revenue / total_auctions`  
**Unit:** USD  

---

## Efficiency KPIs

### Bid Spread
**Definition:** Normalized gap between winning bid and clearing price.  
**Formula:** `(winning_bid - clearing_price) / winning_bid`  
**Target:** ≤ 0.08 (8%)  
**Alert threshold:** > 0.20 (20%)  
**Interpretation:**
- Low spread → competitive, efficient auction
- High spread → winner significantly overpaid; potential for auction redesign

### Auction Depth
**Definition:** Mean number of competing bids per auction.  
**Target:** ≥ 6 bidders  
**Alert threshold:** < 3 bidders  
**Use:** Diagnoses demand-side health. Falling depth may indicate bidder churn
or targeting system issues.

---

## Quality KPIs

### CTR (Click-Through Rate)
**Formula:** `total_clicks / filled_auctions`  
**Target:** ≥ 4%  
**Alert:** < 1%  

### CVR (Conversion Rate)
**Formula:** `total_conversions / total_clicks`  
**Target:** ≥ 3%  
**Alert:** < 0.5%  

---

## Operationalization

All KPIs are computed in two passes:
1. **Streaming (near-real-time):** 5-minute windows via `KPIEngine.compute_all()`.
2. **Batch (daily snapshot):** `kpi_daily` table loaded at 02:00 UTC.

Alerts are sent to the `#ads-science-alerts` Slack channel when any KPI
crosses its alert threshold for two consecutive measurement windows.

See [`kpi_framework.py`](../src/analytics/kpi_framework.py) for implementation.
