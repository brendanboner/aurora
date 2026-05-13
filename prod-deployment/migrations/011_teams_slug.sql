BEGIN;

ALTER TABLE creator_agent
  ADD COLUMN IF NOT EXISTS teams_slug TEXT UNIQUE;

COMMENT ON COLUMN creator_agent.teams_slug IS
  'Teams bot slug for @aurora-<slug> routing (e.g. aurora-wba-wifi-design-wg). NULL means no Teams identity yet.';

CREATE INDEX IF NOT EXISTS idx_creator_agent_teams_slug ON creator_agent(teams_slug)
  WHERE teams_slug IS NOT NULL;

COMMIT;
