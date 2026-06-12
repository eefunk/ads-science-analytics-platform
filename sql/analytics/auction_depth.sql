-- =============================================================================
-- Auction Depth Analysis
-- Analyzes competition intensity across placements and its effect on revenue.
-- =============================================================================

-- 1. Auction depth distribution with revenue and fill metrics
SELECT
    placement_type,
    auction_depth,
    COUNT(*)                                         AS n_auctions,
    ROUND(AVG(filled), 4)                            AS fill_rate,
    ROUND(AVG(ecpm), 2)                              AS avg_ecpm,
    ROUND(AVG(winning_bid_usd), 4)                   AS avg_winning_bid,
    ROUND(AVG(clearing_price_usd), 4)                AS avg_clearing_price,
    ROUND(AVG(bid_spread), 4)                        AS avg_bid_spread,
    ROUND(SUM(revenue_usd), 2)                       AS total_revenue,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY placement_type), 2) AS pct_of_placement
FROM fact_auctions
GROUP BY placement_type, auction_depth
ORDER BY placement_type, auction_depth;


-- 2. Depth buckets — how competitive are auctions by placement?
SELECT
    placement_type,
    CASE
        WHEN auction_depth <= 2  THEN 'low (1-2)'
        WHEN auction_depth <= 4  THEN 'medium (3-4)'
        WHEN auction_depth <= 6  THEN 'high (5-6)'
        WHEN auction_depth <= 8  THEN 'very_high (7-8)'
        ELSE                          'extreme (9+)'
    END                                              AS depth_bucket,
    COUNT(*)                                         AS n_auctions,
    ROUND(AVG(fill_rate), 4)                         AS avg_fill_rate,
    ROUND(AVG(ecpm), 2)                              AS avg_ecpm,
    ROUND(AVG(bid_spread), 4)                        AS avg_bid_spread
FROM fact_auctions
LEFT JOIN (
    SELECT date, placement_type,
           ROUND(AVG(filled), 4) AS fill_rate
    FROM fact_auctions
    GROUP BY date, placement_type
) AS daily_fr USING (date, placement_type)
GROUP BY 1, 2
ORDER BY placement_type, MIN(auction_depth);


-- 3. Depth trend over time — is auction competitiveness improving?
SELECT
    date,
    placement_type,
    ROUND(AVG(auction_depth), 2)                     AS avg_depth,
    ROUND(AVG(filled), 4)                            AS fill_rate,
    ROUND(AVG(ecpm), 2)                              AS avg_ecpm,
    COUNT(*)                                         AS n_auctions
FROM fact_auctions
GROUP BY date, placement_type
ORDER BY date, placement_type;


-- 4. Revenue elasticity of depth — marginal eCPM gain per additional bidder
WITH depth_revenue AS (
    SELECT
        auction_depth,
        ROUND(AVG(ecpm), 4)  AS avg_ecpm,
        COUNT(*)             AS n_auctions
    FROM fact_auctions
    WHERE filled = 1
    GROUP BY auction_depth
    HAVING COUNT(*) >= 50
)
SELECT
    auction_depth,
    avg_ecpm,
    n_auctions,
    ROUND(avg_ecpm - LAG(avg_ecpm) OVER (ORDER BY auction_depth), 4) AS ecpm_marginal_gain
FROM depth_revenue
ORDER BY auction_depth;
