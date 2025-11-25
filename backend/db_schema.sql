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
    datasource_id       TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    scrape_frequency    TEXT NOT NULL DEFAULT 'daily',  -- hourly, daily, weekly, monthly, manual
    check_content_hash  BOOLEAN NOT NULL DEFAULT TRUE,
    last_scraped_at     TIMESTAMPTZ,
    publish_weight      REAL NOT NULL DEFAULT 1.0,      -- Weight for newly published docs
    update_weight       REAL NOT NULL DEFAULT 0.8,      -- Weight for updated docs
    event_weight        REAL NOT NULL DEFAULT 0.9,      -- Weight for events
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for querying by scrape frequency
CREATE INDEX IF NOT EXISTS idx_system_config_scrape_freq 
ON system_configuration(scrape_frequency);

-- Insert default system configurations
INSERT INTO system_configuration (datasource_id, name, scrape_frequency, check_content_hash)
VALUES 
    ('default', 'Default Configuration', 'daily', TRUE),
    ('wfa_resource_page', 'Wi-Fi Alliance Resource Center', 'daily', TRUE),
    ('manual_upload', 'Manual Document Upload', 'manual', TRUE)
ON CONFLICT (datasource_id) DO NOTHING;

