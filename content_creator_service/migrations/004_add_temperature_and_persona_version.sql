-- Migration 004: Add temperature override and persona versioning
-- Adds llm_temperature_override for per-agent temperature control
-- Adds persona_version and persona_updated_at for tracking persona evolution

ALTER TABLE creator_agent
ADD COLUMN IF NOT EXISTS llm_temperature_override NUMERIC(3,2) CHECK (llm_temperature_override >= 0.0 AND llm_temperature_override <= 1.0),
ADD COLUMN IF NOT EXISTS persona_version INTEGER NOT NULL DEFAULT 1,
ADD COLUMN IF NOT EXISTS persona_updated_at TIMESTAMPTZ;

-- Set persona_updated_at to created_at for existing agents
UPDATE creator_agent
SET persona_updated_at = created_at
WHERE persona_updated_at IS NULL;

COMMENT ON COLUMN creator_agent.llm_temperature_override IS 'Override LLM temperature for this agent (0.0-1.0). NULL uses system default.';
COMMENT ON COLUMN creator_agent.persona_version IS 'Version number for persona, increments on updates';
COMMENT ON COLUMN creator_agent.persona_updated_at IS 'Timestamp of last persona modification';
