-- User Source Memberships
-- Stores per-user join/ignore preferences for data sources (workgroups and public sources).
-- status = 'joined'  → user is a member; documents from this source are boosted in results
-- status = 'ignored' → user has opted out; documents from this source are hard-excluded
-- Default behaviour (no row) = treat source normally, no boost or exclusion

CREATE TABLE IF NOT EXISTS user_source_memberships (
    user_id         TEXT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    datasource_id   TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('joined', 'ignored')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, datasource_id)
);

CREATE INDEX IF NOT EXISTS idx_user_source_memberships_user_id
    ON user_source_memberships(user_id);
