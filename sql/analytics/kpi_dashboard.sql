-- =============================================================================
-- Ads KPI Dashboard Queries
-- Master set of queries for the ad revenue & supply intelligence analytics deck.
-- Designed to be run against the kpi_daily snapshot table.
-- =============================================================================

-- 1. Platform-level KPI scorecard (latest 30 days)
WITH latest_30d AS (
    SELECT *
    FROM kpi_daily
    WHERE date >= date('now', '-30 days')
),
prev_30d AS (
    SELECT *
    FROM kpi_daily
    WHERE date >= date('now', '-60 days')
      AND date <  date('now', '-30 days')
)
SELECT
    'fill_rate'       AS kpi,
    ROUND(AVG(l.fill_rate), 4)            AS current_value,
    ROUND(AVG(p.fill_rate), 4)            AS prior_value,
    ROUND(100.0 * (AVG(l.fill_rate) - AVG(p.fill_rate)) / NULLIF(AVG(p.fill_rate), 0), 2) AS pct_change
FROM latest_30d l, prev_30d p
UNION ALL
SELECT 'avg_ecpm',
    ROUND(AVG(l.avg_ecpm), 2), ROUND(AVG(p.avg_ecpm), 2),
    ROUND(100.0 * (AVG(l.avg_ecpm) - AVG(p.avg_ecpm)) / NULLIF(AVG(p.avg_ecpm), 0), 2)
FROM latest_30d l, prev_30d p
UNION ALL
SELECT 'avg_bid_spread',
    ROUND(AVG(l.avg_bid_spread), 4), ROUND(AVG(p.avg_bid_spread), 4),
    ROUND(100.0 * (AVG(l.avg_bid_spread) - AVG(p.avg_bid_spread)) / NULLIF(AVG(p.avg_bid_spread), 0), 2)
FROM latest_30d l, prev_30d p
UNION ALL
SELECT 'ctr',
    ROUND(AVG(l.ctr), 4), ROUND(AVG(p.ctr), 4),
    ROUND(100.0 * (AVG(l.ctr) - AVG(p.ctr)) / NULLIF(AVG(p.ctr), 0), 2)
FROM latest_30d l, prev_30d p
UNION ALL
SELECT 'total_revenue_usd',
    ROUND(SUM(l.total_revenue_usd), 2), ROUND(SUM(p.total_revenue_usd), 2),
    ROUND(100.0 * (SUM(l.total_revenue_usd) - SUM(p.total_revenue_usd)) / NULLIF(SUM(p.total_revenue_usd), 0), 2)
FROM latest_30d l, prev_30d p;


-- 2. Revenue by placement (last 30 days, ranked)
SELECT
    placement_type,
    ROUND(SUM(total_revenue_usd), 2)    AS revenue_usd,
    ROUND(AVG(fill_rate), 4)            AS avg_fill_rate,
    ROUND(AVG(avg_ecpm), 2)             AS avg_ecpm,
    SUM(total_auctions)                  AS total_auctions,
    ROUND(AVG(avg_bid_spread), 4)       AS avg_bid_spread,
    ROUND(100.0 * SUM(total_revenue_usd) /
          SUM(SUM(total_revenue_usd)) OVER (), 2)  AS revenue_share_pct
FROM kpi_daily
WHERE date >= date('now', '-30 days')
GROUP BY placement_type
ORDER BY revenue_usd DESC;


-- 3. Daily revenue run rate with WoW comparison
SELECT
    a.date,
    a.placement_type,
    ROUND(SUM(a.total_revenue_usd), 2)  AS revenue_usd,
    ROUND(AVG(a.fill_rate), 4)          AS fill_rate,
    ROUND(AVG(a.avg_ecpm), 2)           AS avg_ecpm,
    ROUND(SUM(b.total_revenue_usd), 2)  AS revenue_usd_wow,
    ROUND(100.0 * (SUM(a.total_revenue_usd) - SUM(b.total_revenue_usd))
          / NULLIF(SUM(b.total_revenue_usd), 0), 2) AS wow_pct_change
FROM kpi_daily a
LEFT JOIN kpi_daily b
    ON a.placement_type = b.placement_type
   AND a.device_type    = b.device_type
   AND a.ad_format      = b.ad_format
   AND b.date = date(a.date, '-7 days')
GROUP BY a.date, a.placement_type
ORDER BY a.date, a.placement_type;


-- 4. Top/Bottom performing ad formats
SELECT
    ad_format,
    device_type,
    ROUND(AVG(fill_rate), 4)         AS avg_fill_rate,
    ROUND(AVG(avg_ecpm), 2)          AS avg_ecpm,
    ROUND(AVG(ctr), 4)               AS avg_ctr,
    ROUND(AVG(cvr), 4)               AS avg_cvr,
    ROUND(AVG(avg_bid_spread), 4)    AS avg_bid_spread,
    SUM(total_auctions)              AS total_auctions,
    ROUND(SUM(total_revenue_usd), 2) AS total_revenue
FROM kpi_daily
GROUP BY ad_format, device_type
ORDER BY avg_ecpm DESC;


-- 5. Hourly intraday revenue pattern (last 7 days)
SELECT
    hour,
    placement_type,
    ROUND(AVG(total_revenue_usd), 2)   AS avg_hourly_revenue,
    ROUND(AVG(fill_rate), 4)           AS avg_fill_rate,
    ROUND(AVG(avg_ecpm), 2)            AS avg_ecpm,
    SUM(total_auctions)                AS total_auctions
FROM kpi_hourly
WHERE date >= date('now', '-7 days')
GROUP BY hour, placement_type
ORDER BY hour, placement_type;
