-- Migration 005: Add user_agent table and extend post table for personal agents
-- This enables users to create personal AI agents from project descriptions

BEGIN;

-- Create user_agent table for personal agents
CREATE TABLE IF NOT EXISTS user_agent (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    project_description TEXT NOT NULL,
    scope_notes TEXT,
    cadence TEXT NOT NULL DEFAULT 'daily',
    show_in_feed BOOLEAN NOT NULL DEFAULT TRUE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    
    -- AI-generated fields (populated by LLM analysis)
    expertise_topics TEXT[] DEFAULT '{}',
    expertise_organisations TEXT[] DEFAULT '{}',
    tone_style TEXT DEFAULT 'analytical',
    persona TEXT,
    
    -- Feedback learning system (JSONB array of feedback entries)
    -- Each entry: {timestamp, feedback_text, applied_changes}
    feedback_history JSONB DEFAULT '[]'::jsonb,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_run_at TIMESTAMPTZ,
    last_generated_at TIMESTAMPTZ,
    
    -- Unique constraint per user
    UNIQUE(user_id, name)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_user_agent_user_id ON user_agent(user_id);
CREATE INDEX IF NOT EXISTS idx_user_agent_enabled ON user_agent(enabled);
CREATE INDEX IF NOT EXISTS idx_user_agent_user_enabled ON user_agent(user_id, enabled);

-- Auto-update timestamp trigger
CREATE OR REPLACE FUNCTION touch_user_agent_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_user_agent_updated_at ON user_agent;
CREATE TRIGGER trg_user_agent_updated_at
BEFORE UPDATE ON user_agent
FOR EACH ROW EXECUTE PROCEDURE touch_user_agent_updated_at();

-- Extend post table for user ownership and visibility
ALTER TABLE post
ADD COLUMN IF NOT EXISTS user_id TEXT REFERENCES app_users(id) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS agent_type TEXT DEFAULT 'shared' CHECK (agent_type IN ('shared', 'personal'));

-- Update existing posts to be 'shared' type
UPDATE post SET agent_type = 'shared' WHERE agent_type IS NULL;

-- Create indexes for user-scoped queries
CREATE INDEX IF NOT EXISTS idx_post_user_id ON post(user_id);
CREATE INDEX IF NOT EXISTS idx_post_user_id_created_at ON post(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_post_agent_type ON post(agent_type);
CREATE INDEX IF NOT EXISTS idx_post_visibility ON post(visibility);

COMMIT;
