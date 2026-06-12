-- =============================================================================
-- Bid Spread Analysis
-- Bid spread = (winning_bid - clearing_price) / winning_bid
-- High spread → large gap between what winner paid and true market price.
-- Low spread → efficient, competitive auction.
-- =============================================================================

-- 1. Bid spread summary statistics by placement
SELECT
    placement_type,
    COUNT(*)                                                AS n_auctions,
    ROUND(AVG(bid_spread), 4)                               AS mean_spread,
    ROUND(
        (SELECT AVG(bid_spread)
         FROM (SELECT bid_spread, ROW_NUMBER() OVER (ORDER BY bid_spread) AS rn,
                      COUNT(*) OVER () AS cnt
               FROM fact_auctions a2
               WHERE a2.placement_type = a.placement_type)
         WHERE rn IN (cnt/2, cnt/2+1)), 4)                  AS approx_median_spread,
    ROUND(MIN(bid_spread), 4)                               AS min_spread,
    ROUND(MAX(bid_spread), 4)                               AS max_spread,
    ROUND(AVG(winning_bid_usd - clearing_price_usd), 4)     AS avg_margin_usd,
    ROUND(SUM(winning_bid_usd - clearing_price_usd), 2)     AS total_advertiser_surplus
FROM fact_auctions
WHERE filled = 1
GROUP BY placement_type
ORDER BY mean_spread DESC;


-- 2. Bid spread by ad format × device — cross-segment efficiency
SELECT
    ad_format,
    device_type,
    COUNT(*)                                AS n_auctions,
    ROUND(AVG(bid_spread), 4)               AS avg_spread,
    ROUND(AVG(ecpm), 2)                     AS avg_ecpm,
    ROUND(AVG(auction_depth), 2)            AS avg_depth,
    ROUND(SUM(winning_bid_usd - clearing_price_usd), 2) AS total_advertiser_surplus_usd
FROM fact_auctions
WHERE filled = 1
GROUP BY ad_format, device_type
ORDER BY avg_spread DESC;


-- 3. Bid spread trend — are auctions becoming more or less efficient?
SELECT
    date,
    ROUND(AVG(bid_spread), 4)               AS avg_spread,
    ROUND(AVG(winning_bid_usd), 4)          AS avg_winning_bid,
    ROUND(AVG(clearing_price_usd), 4)       AS avg_clearing_price,
    COUNT(*)                                AS n_filled_auctions
FROM fact_auctions
WHERE filled = 1
GROUP BY date
ORDER BY date;


-- 4. Spread concentration: what fraction of surplus is captured by top 10% spreads?
WITH spread_ranked AS (
    SELECT
        auction_id,
        bid_spread,
        winning_bid_usd - clearing_price_usd AS margin_usd,
        NTILE(10) OVER (ORDER BY bid_spread DESC) AS spread_decile
    FROM fact_auctions
    WHERE filled = 1
)
SELECT
    spread_decile,
    COUNT(*)                                    AS n_auctions,
    ROUND(AVG(bid_spread), 4)                   AS avg_spread,
    ROUND(SUM(margin_usd), 2)                   AS total_surplus_usd,
    ROUND(100.0 * SUM(margin_usd) / SUM(SUM(margin_usd)) OVER (), 2) AS pct_total_surplus
FROM spread_ranked
GROUP BY spread_decile
ORDER BY spread_decile;
