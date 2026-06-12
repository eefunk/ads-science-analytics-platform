-- =============================================================================
-- Ads Science Analytics Platform — Data Warehouse DDL
-- Data Model: Star Schema
--   Fact tables:  fact_auctions, fact_supply
--   Dimension tables: dim_advertiser, dim_campaign, dim_placement, dim_date
--   KPI snapshots: kpi_daily, kpi_hourly
-- =============================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Dimension: Advertiser
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_advertiser (
    advertiser_id      TEXT PRIMARY KEY,
    tier               TEXT NOT NULL CHECK(tier IN ('small','mid','large','enterprise')),
    category           TEXT NOT NULL,
    daily_budget_usd   REAL NOT NULL,
    bidding_strategy   TEXT NOT NULL,
    target_cpc_usd     REAL,
    quality_score      REAL CHECK(quality_score BETWEEN 0 AND 10),
    identity_match_rate REAL CHECK(identity_match_rate BETWEEN 0 AND 1),
    created_at         TEXT DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Dimension: Campaign
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_campaign (
    campaign_id       TEXT PRIMARY KEY,
    advertiser_id     TEXT NOT NULL REFERENCES dim_advertiser(advertiser_id),
    ad_format         TEXT NOT NULL,
    category          TEXT NOT NULL,
    daily_budget_usd  REAL NOT NULL,
    target_bid_usd    REAL,
    quality_score     REAL CHECK(quality_score BETWEEN 0 AND 10),
    relevance_score   REAL CHECK(relevance_score BETWEEN 0 AND 1),
    created_at        TEXT DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Dimension: Date (for partitioned analytics)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_date (
    date_key       TEXT PRIMARY KEY,   -- YYYY-MM-DD
    year           INTEGER NOT NULL,
    quarter        INTEGER NOT NULL CHECK(quarter BETWEEN 1 AND 4),
    month          INTEGER NOT NULL CHECK(month BETWEEN 1 AND 12),
    week           INTEGER NOT NULL,
    day_of_week    TEXT NOT NULL,
    is_weekend     INTEGER NOT NULL CHECK(is_weekend IN (0,1)),
    is_holiday     INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- Dimension: Placement Configuration
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_placement (
    placement_key  TEXT PRIMARY KEY,  -- e.g., top_of_search|desktop
    placement_type TEXT NOT NULL,
    device_type    TEXT NOT NULL,
    floor_price_usd REAL,
    ad_formats_allowed TEXT           -- JSON array of allowed formats
);

-- ---------------------------------------------------------------------------
-- Fact: Auction Events
-- Core fact table — one row per auction request
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_auctions (
    auction_id          TEXT PRIMARY KEY,
    timestamp           TEXT NOT NULL,
    date                TEXT NOT NULL,
    hour                INTEGER NOT NULL CHECK(hour BETWEEN 0 AND 23),
    day_of_week         TEXT,
    week                INTEGER,
    month               INTEGER,
    is_weekend          INTEGER,
    placement_type      TEXT NOT NULL,
    device_type         TEXT NOT NULL,
    ad_format           TEXT NOT NULL,
    category            TEXT NOT NULL,
    campaign_id         TEXT REFERENCES dim_campaign(campaign_id),
    advertiser_id       TEXT REFERENCES dim_advertiser(advertiser_id),
    -- Auction mechanics
    auction_depth       INTEGER NOT NULL CHECK(auction_depth >= 1),
    bid_floor_usd       REAL NOT NULL,
    winning_bid_usd     REAL NOT NULL,
    clearing_price_usd  REAL NOT NULL,
    bid_spread          REAL,
    margin_usd          REAL,
    bid_z_score         REAL,
    is_bid_anomaly      INTEGER DEFAULT 0,
    ecpm                REAL,
    -- Outcomes
    filled              INTEGER NOT NULL DEFAULT 0 CHECK(filled IN (0,1)),
    clicked             INTEGER NOT NULL DEFAULT 0 CHECK(clicked IN (0,1)),
    converted           INTEGER NOT NULL DEFAULT 0 CHECK(converted IN (0,1)),
    revenue_usd         REAL NOT NULL DEFAULT 0,
    -- Feature release tracking
    feature_version     TEXT,
    release_period      TEXT CHECK(release_period IN ('pre','post')),
    treatment           INTEGER DEFAULT 0 CHECK(treatment IN (0,1))
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_fact_auctions_date       ON fact_auctions(date);
CREATE INDEX IF NOT EXISTS idx_fact_auctions_placement  ON fact_auctions(placement_type);
CREATE INDEX IF NOT EXISTS idx_fact_auctions_campaign   ON fact_auctions(campaign_id);
CREATE INDEX IF NOT EXISTS idx_fact_auctions_advertiser ON fact_auctions(advertiser_id);
CREATE INDEX IF NOT EXISTS idx_fact_auctions_ts         ON fact_auctions(timestamp);
CREATE INDEX IF NOT EXISTS idx_fact_auctions_treatment  ON fact_auctions(treatment, release_period);

-- ---------------------------------------------------------------------------
-- Fact: Supply Events
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_supply (
    supply_event_id    TEXT PRIMARY KEY,
    timestamp          TEXT NOT NULL,
    date               TEXT NOT NULL,
    hour               INTEGER NOT NULL,
    day_of_week        TEXT,
    placement_type     TEXT NOT NULL,
    device_type        TEXT NOT NULL,
    available_slots    INTEGER NOT NULL CHECK(available_slots >= 0),
    fill_rate          REAL NOT NULL CHECK(fill_rate BETWEEN 0 AND 1),
    floor_price_usd    REAL NOT NULL,
    monetized_slots    REAL,
    supply_health      REAL,
    page_load_ms       INTEGER
);

CREATE INDEX IF NOT EXISTS idx_fact_supply_date      ON fact_supply(date);
CREATE INDEX IF NOT EXISTS idx_fact_supply_placement ON fact_supply(placement_type);

-- ---------------------------------------------------------------------------
-- KPI Snapshots (pre-aggregated for dashboards)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kpi_daily (
    date                  TEXT NOT NULL,
    placement_type        TEXT NOT NULL,
    device_type           TEXT NOT NULL,
    ad_format             TEXT NOT NULL,
    total_auctions        INTEGER,
    filled_auctions       INTEGER,
    total_clicks          INTEGER,
    total_conversions     INTEGER,
    total_revenue_usd     REAL,
    avg_winning_bid       REAL,
    avg_clearing_price    REAL,
    avg_bid_spread        REAL,
    avg_ecpm              REAL,
    avg_auction_depth     REAL,
    p50_winning_bid       REAL,
    p90_winning_bid       REAL,
    p99_winning_bid       REAL,
    fill_rate             REAL,
    ctr                   REAL,
    cvr                   REAL,
    cpc_usd               REAL,
    rpm_usd               REAL,
    PRIMARY KEY (date, placement_type, device_type, ad_format)
);

CREATE TABLE IF NOT EXISTS kpi_hourly (
    date           TEXT NOT NULL,
    hour           INTEGER NOT NULL,
    placement_type TEXT NOT NULL,
    total_auctions INTEGER,
    filled_auctions INTEGER,
    total_clicks   INTEGER,
    total_conversions INTEGER,
    total_revenue_usd REAL,
    avg_winning_bid REAL,
    avg_clearing_price REAL,
    avg_bid_spread REAL,
    avg_ecpm       REAL,
    avg_auction_depth REAL,
    fill_rate      REAL,
    ctr            REAL,
    cvr            REAL,
    rpm_usd        REAL,
    PRIMARY KEY (date, hour, placement_type)
);
