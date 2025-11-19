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
