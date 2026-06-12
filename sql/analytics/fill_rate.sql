-- =============================================================================
-- Fill Rate & Supply Intelligence Analysis
-- Fill rate = filled auctions / total auction requests
-- Critical KPI: low fill rate → lost revenue and poor advertiser experience
-- =============================================================================

-- 1. Fill rate heatmap: placement × device
SELECT
    placement_type,
    device_type,
    COUNT(*)                                        AS total_requests,
    SUM(filled)                                     AS filled_requests,
    ROUND(100.0 * AVG(filled), 2)                   AS fill_rate_pct,
    ROUND(AVG(bid_floor_usd), 4)                    AS avg_floor_usd,
    ROUND(AVG(winning_bid_usd), 4)                  AS avg_winning_bid,
    ROUND(AVG(CASE WHEN filled=1 THEN ecpm END), 2) AS avg_filled_ecpm,
    ROUND(SUM(revenue_usd), 2)                      AS total_revenue_usd
FROM fact_auctions
GROUP BY placement_type, device_type
ORDER BY fill_rate_pct DESC;


-- 2. Unfilled auction analysis — why are auctions not filling?
SELECT
    placement_type,
    COUNT(*)                                        AS unfilled_auctions,
    ROUND(AVG(bid_floor_usd), 4)                    AS avg_floor_usd,
    ROUND(AVG(winning_bid_usd), 4)                  AS avg_bid_below_floor,
    ROUND(AVG(bid_floor_usd - winning_bid_usd), 4)  AS avg_shortfall_usd,
    ROUND(
        100.0 * SUM(CASE WHEN winning_bid_usd < bid_floor_usd THEN 1 ELSE 0 END)
        / COUNT(*), 2
    )                                               AS pct_below_floor
FROM fact_auctions
WHERE filled = 0
GROUP BY placement_type
ORDER BY unfilled_auctions DESC;


-- 3. Daily fill rate trend with 7-day rolling average
WITH daily_fill AS (
    SELECT
        date,
        ROUND(AVG(filled), 4)       AS fill_rate,
        COUNT(*)                     AS n_auctions
    FROM fact_auctions
    GROUP BY date
)
SELECT
    date,
    fill_rate,
    n_auctions,
    ROUND(AVG(fill_rate) OVER (
        ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ), 4)                            AS rolling_7d_fill_rate
FROM daily_fill
ORDER BY date;


-- 4. Floor price sensitivity — revenue vs fill rate tradeoff
WITH floor_buckets AS (
    SELECT
        placement_type,
        ROUND(bid_floor_usd * 20) / 20  AS floor_bucket,   -- round to nearest $0.05
        COUNT(*)                         AS n_auctions,
        ROUND(AVG(filled), 4)            AS fill_rate,
        ROUND(SUM(revenue_usd), 2)       AS revenue_usd
    FROM fact_auctions
    GROUP BY placement_type, floor_bucket
    HAVING COUNT(*) >= 100
)
SELECT
    placement_type,
    floor_bucket,
    n_auctions,
    fill_rate,
    revenue_usd,
    ROUND(revenue_usd / n_auctions, 4)  AS rev_per_request
FROM floor_buckets
ORDER BY placement_type, floor_bucket;


-- 5. Supply-demand imbalance by hour
SELECT
    hour,
    COUNT(*)                            AS n_requests,
    ROUND(AVG(filled), 4)               AS fill_rate,
    ROUND(AVG(auction_depth), 2)        AS avg_depth,
    ROUND(AVG(ecpm), 2)                 AS avg_ecpm,
    ROUND(SUM(revenue_usd), 2)          AS hourly_revenue
FROM fact_auctions
GROUP BY hour
ORDER BY hour;
