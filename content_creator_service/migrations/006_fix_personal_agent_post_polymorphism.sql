BEGIN;

-- Personal-agent posts reuse post.agent_id to point at either creator_agent.id
-- or user_agent.id depending on post.agent_type, so the original creator_agent FK
-- must be removed for the personal-agent path to work.
ALTER TABLE IF EXISTS post
DROP CONSTRAINT IF EXISTS post_agent_id_fkey;

COMMIT;
