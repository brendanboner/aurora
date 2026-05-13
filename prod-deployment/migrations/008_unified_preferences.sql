-- Migration 008: Unified source preferences
--
-- Replaces the free-text user_preferences.sources TEXT[] (which held root
-- URLs of scraped sources and had become messy) with a proper join table
-- user_source_preferences backed by DataSource node IDs from Neo4j.
--
-- The sources column is dropped AFTER the migrate_user_sources.py script
-- has mapped any existing values to datasource_ids.
--
-- The user_source_memberships table (join/ignore semantics) is unchanged.
-- This new table handles weighted source preference ("prefer IEEE 802.11").

-- New table: weighted source preferences (distinct from join/ignore memberships)
CREATE TABLE IF NOT EXISTS user_source_preferences (
    user_id         TEXT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    datasource_id   TEXT NOT NULL,
    weight          REAL NOT NULL DEFAULT 1.0
        CHECK (weight >= 0.0 AND weight <= 2.0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, datasource_id)
);

CREATE INDEX IF NOT EXISTS idx_user_source_preferences_user
    ON user_source_preferences (user_id);

-- Remove the legacy free-text sources column now that the migration script
-- has moved any data. If the column doesn't exist (fresh install) the
-- IF EXISTS guard makes this a no-op.
ALTER TABLE user_preferences
    DROP COLUMN IF EXISTS sources;

-- Also add domains column if not present (migration 006 adds it but some
-- older installs may be missing it).
ALTER TABLE user_preferences
    ADD COLUMN IF NOT EXISTS domains TEXT[] DEFAULT '{}';
