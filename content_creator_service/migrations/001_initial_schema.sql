BEGIN;

CREATE TABLE IF NOT EXISTS creator_agent (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    persona TEXT,
    expertise_topics TEXT[] NOT NULL DEFAULT '{}',
    expertise_organisations TEXT[] NOT NULL DEFAULT '{}',
    expertise_standards TEXT[] NOT NULL DEFAULT '{}',
    tone_style TEXT NOT NULL DEFAULT 'analytical',
    posting_cadence TEXT NOT NULL DEFAULT 'per-event',
    content_length_preference TEXT NOT NULL DEFAULT 'medium',
    importance_threshold TEXT NOT NULL DEFAULT 'normal',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION touch_creator_agent_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_creator_agent_updated_at ON creator_agent;
CREATE TRIGGER trg_creator_agent_updated_at
BEFORE UPDATE ON creator_agent
FOR EACH ROW EXECUTE PROCEDURE touch_creator_agent_updated_at();

CREATE TABLE IF NOT EXISTS post (
    id BIGSERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES creator_agent(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    summary TEXT,
    tags TEXT[] NOT NULL DEFAULT '{}',
    visibility TEXT NOT NULL DEFAULT 'public',
    importance TEXT NOT NULL DEFAULT 'normal',
    content_length TEXT NOT NULL DEFAULT 'medium',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION touch_post_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_post_updated_at ON post;
CREATE TRIGGER trg_post_updated_at
BEFORE UPDATE ON post
FOR EACH ROW EXECUTE PROCEDURE touch_post_updated_at();

CREATE TABLE IF NOT EXISTS post_source (
    id BIGSERIAL PRIMARY KEY,
    post_id BIGINT NOT NULL REFERENCES post(id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL,
    source_identifier TEXT,
    url TEXT,
    confidence NUMERIC(5,4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_agent_follow (
    user_id TEXT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    agent_id INTEGER NOT NULL REFERENCES creator_agent(id) ON DELETE CASCADE,
    followed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, agent_id)
);

CREATE TABLE IF NOT EXISTS user_post_reaction (
    user_id TEXT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    post_id BIGINT NOT NULL REFERENCES post(id) ON DELETE CASCADE,
    reaction_type TEXT NOT NULL CHECK (reaction_type IN ('like', 'dislike')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, post_id)
);

CREATE TABLE IF NOT EXISTS user_preference_profile (
    user_id TEXT PRIMARY KEY REFERENCES app_users(id) ON DELETE CASCADE,
    topic_weights JSONB NOT NULL DEFAULT '{}'::jsonb,
    agent_affinity JSONB NOT NULL DEFAULT '{}'::jsonb,
    preferred_length TEXT NOT NULL DEFAULT 'medium',
    preferred_cadence TEXT NOT NULL DEFAULT 'per-event',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_post_agent_id_created_at ON post(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_post_created_at ON post(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_post_reaction_post_id ON user_post_reaction(post_id);
CREATE INDEX IF NOT EXISTS idx_post_tags_gin ON post USING GIN (tags);

COMMIT;
