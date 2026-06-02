-- Migration 012 backfilled aad_object_id from teams_conversation_references where
-- the conv-ref pointed at a real (non-synthetic) account. That misses users whose
-- Teams session created a synthetic {OID}@teams.aad account in parallel to their
-- real SSO account — the conv-ref points at the synthetic row, not the real one.
--
-- This pass bridges them by display_name: for every synthetic user whose
-- display_name uniquely identifies a real user, copy the synthetic's id (which
-- equals the AAD OID per the bot's syncUser logic) onto the real user's
-- aad_object_id column.

BEGIN;

WITH synthetic_users AS (
    SELECT
        id AS aad_object_id,    -- by construction id == AAD OID on synthetic rows
        display_name
    FROM app_users
    WHERE email LIKE '%@teams.aad'
      AND display_name IS NOT NULL
      AND TRIM(display_name) <> ''
),
candidates AS (
    SELECT
        s.aad_object_id,
        u.id AS real_user_id,
        COUNT(*) OVER (PARTITION BY s.aad_object_id) AS match_count
    FROM synthetic_users s
    JOIN app_users u
        ON u.email NOT LIKE '%@teams.aad'
       AND u.aad_object_id IS NULL
       AND LOWER(TRIM(u.display_name)) = LOWER(TRIM(s.display_name))
)
UPDATE app_users u
SET aad_object_id = c.aad_object_id,
    updated_at = NOW()
FROM candidates c
WHERE u.id = c.real_user_id
  AND c.match_count = 1;  -- only link when the display_name uniquely identifies a real user

COMMIT;
