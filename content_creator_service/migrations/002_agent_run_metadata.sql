BEGIN;

ALTER TABLE creator_agent
    ADD COLUMN IF NOT EXISTS last_run_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_generated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_event_cursor TEXT;

CREATE INDEX IF NOT EXISTS idx_creator_agent_enabled ON creator_agent(enabled);

COMMIT;
