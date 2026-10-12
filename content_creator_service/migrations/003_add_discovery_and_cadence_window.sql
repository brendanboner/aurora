BEGIN;

ALTER TABLE creator_agent
    ADD COLUMN IF NOT EXISTS discovery_tolerance NUMERIC(3,2) NOT NULL DEFAULT 0.5 CHECK (discovery_tolerance >= 0 AND discovery_tolerance <= 1),
    ADD COLUMN IF NOT EXISTS cadence_window_days INTEGER NOT NULL DEFAULT 7 CHECK (cadence_window_days >= 1 AND cadence_window_days <= 365);

CREATE INDEX IF NOT EXISTS idx_creator_agent_discovery_tolerance ON creator_agent(discovery_tolerance);

COMMIT;
