-- Users
-- id is now TEXT to store Cognito UUID (sub claim)
-- This matches the user_id from X-User-Id header passed by auth service
CREATE TABLE IF NOT EXISTS app_users (
    id              TEXT PRIMARY KEY,  -- Cognito user UUID (sub claim)
    email           TEXT NOT NULL UNIQUE,
    display_name    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Per-user preferences
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id         TEXT PRIMARY KEY REFERENCES app_users(id) ON DELETE CASCADE,  -- Changed from INTEGER to TEXT
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
    user_id         TEXT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,  -- Changed from INTEGER to TEXT
    event_id        TEXT NOT NULL,
    status          TEXT NOT NULL,
    role            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, event_id)
);

-- Chat conversations (tracks user chat sessions)
CREATE TABLE IF NOT EXISTS chat_conversations (
    id              SERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    title           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Chat messages (tracks individual messages in conversations)
CREATE TABLE IF NOT EXISTS chat_messages (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for efficient chat queries
CREATE INDEX IF NOT EXISTS idx_chat_conversations_user_id ON chat_conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_conversations_created_at ON chat_conversations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation_id ON chat_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_user_id ON chat_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at ON chat_messages(created_at);

-- Note: system_configuration table has been migrated to Neo4j DataSource nodes
-- All datasource configuration including scraper settings, schedules, and weights
-- are now stored as properties on DataSource nodes in the knowledge graph.
