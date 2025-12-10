-- Users
CREATE TABLE IF NOT EXISTS app_users (
    id              SERIAL PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    display_name    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Per-user preferences
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id         INTEGER PRIMARY KEY REFERENCES app_users(id) ON DELETE CASCADE,
    topics          TEXT[] DEFAULT '{}',
    organisations   TEXT[] DEFAULT '{}',
    people          TEXT[] DEFAULT '{}',
    sources         TEXT[] DEFAULT '{}',
    notify_email    BOOLEAN NOT NULL DEFAULT TRUE,
    notify_digest   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Event attendance (links users to Neo4j events)
CREATE TABLE IF NOT EXISTS event_attendance (
    user_id         INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    event_id        TEXT NOT NULL,
    status          TEXT NOT NULL,
    role            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, event_id)
);

-- System Configuration
CREATE TABLE IF NOT EXISTS system_configuration (
    datasource_id               TEXT PRIMARY KEY,
    name                        TEXT NOT NULL,
    scraper_type                TEXT DEFAULT NULL,              -- Scraper class to use (e.g., 'wfa', 'wfa_causeway')
    resource_url                TEXT DEFAULT NULL,              -- URL path to scrape (e.g., '/resource-center', '/wg/WiFi7MTG/document')
    scrape_schedule             TEXT DEFAULT NULL,              -- Cron expression for scheduling (e.g., '0 2 * * *' = 2 AM daily), NULL = manual only
    run_on_startup              BOOLEAN NOT NULL DEFAULT FALSE, -- Run immediately when retriever starts
    check_content_hash          BOOLEAN NOT NULL DEFAULT TRUE,
    last_scraped_at             TIMESTAMPTZ,
    publish_weight              REAL NOT NULL DEFAULT 1.0,      -- Weight for newly published docs
    update_weight               REAL NOT NULL DEFAULT 0.8,      -- Weight for updated docs
    event_weight                REAL NOT NULL DEFAULT 0.9,      -- Weight for events
    temporal_extraction_days    INTEGER DEFAULT 90,             -- Days threshold for extracting events from documents
    folders                     JSONB DEFAULT NULL,             -- Folder paths for hierarchical scrapers (e.g., Causeway)
    scraper_delay               REAL DEFAULT 0.5,               -- Delay between requests in seconds
    max_resources               INTEGER DEFAULT 150,            -- Max resources to scrape per run (-1 = unlimited)
    max_redirects               INTEGER DEFAULT 10,             -- Max redirects to follow when resolving URLs
    discovery_mode              TEXT DEFAULT 'incremental',     -- 'date_based' (Causeway), 'incremental' (WFA public)
    consecutive_duplicates_limit INTEGER DEFAULT 5,             -- For incremental mode: stop after N consecutive dupes
    full_refresh_schedule       TEXT DEFAULT NULL,              -- Cron for content update checks (e.g., weekly full scan)
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for querying datasources with schedules
CREATE INDEX IF NOT EXISTS idx_system_config_scrape_schedule 
ON system_configuration(scrape_schedule) WHERE scrape_schedule IS NOT NULL;

-- Index for querying by temporal extraction threshold
CREATE INDEX IF NOT EXISTS idx_system_config_temporal_threshold 
ON system_configuration(temporal_extraction_days);

-- Index for querying by scraper type (for grouping datasources by scraper)
CREATE INDEX IF NOT EXISTS idx_system_config_scraper_type 
ON system_configuration(scraper_type);

-- Index for startup datasources
CREATE INDEX IF NOT EXISTS idx_system_config_run_on_startup
ON system_configuration(run_on_startup) WHERE run_on_startup = TRUE;
