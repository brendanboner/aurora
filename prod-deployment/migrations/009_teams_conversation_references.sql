BEGIN;

CREATE TABLE IF NOT EXISTS teams_conversation_references (
    id                      SERIAL PRIMARY KEY,
    -- Bot Framework identity
    conversation_id         TEXT NOT NULL UNIQUE,
    service_url             TEXT NOT NULL,
    tenant_id               TEXT,
    bot_id                  TEXT,
    -- Conversation metadata
    conversation_type       TEXT NOT NULL DEFAULT 'personal', -- personal | groupChat | channel
    channel_id              TEXT,                             -- Teams channel ID for channel conversations
    -- User linkage (nullable for group chats)
    aad_object_id           TEXT,                             -- AAD Object ID from Bot Framework
    aurora_user_id          TEXT,                             -- Aurora user UUID once resolved
    -- Agent subscriptions
    subscribed_agent_slugs  TEXT[]  NOT NULL DEFAULT '{}',    -- which creator agents push here
    default_agent_slug      TEXT,                             -- channel-scoped default agent
    default_agent_expires_at TIMESTAMPTZ,                    -- TTL for temporary default agent
    -- Timestamps
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_teams_conv_ref_aurora_user
    ON teams_conversation_references(aurora_user_id)
    WHERE aurora_user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_teams_conv_ref_subscribed_slugs
    ON teams_conversation_references USING GIN(subscribed_agent_slugs);

CREATE OR REPLACE FUNCTION touch_teams_conv_ref_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_teams_conv_ref_updated_at ON teams_conversation_references;
CREATE TRIGGER trg_teams_conv_ref_updated_at
BEFORE UPDATE ON teams_conversation_references
FOR EACH ROW EXECUTE FUNCTION touch_teams_conv_ref_updated_at();

COMMIT;
