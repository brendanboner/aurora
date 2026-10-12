-- Add aad_object_id column to app_users so the Teams bot can resolve users
-- by their Microsoft Graph Object ID without depending on Graph API access
-- (which currently 403s due to missing User.Read.All permission, breaking
-- "my agents" and @-mentions in Teams).
--
-- Background: bbonner (and every other SSO-migrated user) has three distinct
-- identifiers in flight at the same time:
--   - app_users.id         e.g. e4b864d8-…  (original Cognito UUID)
--   - app_users.sso_id     e.g. 74e8a418-…  (Cognito-issued sub claim post-SSO migration)
--   - AAD Object ID         e.g. 50b5c83c-…  (what Teams sends as activity.from.aadObjectId)
-- The Teams bot was creating duplicate synthetic accounts keyed on the AAD
-- OID; this column lets it find the real account directly.

BEGIN;

ALTER TABLE app_users ADD COLUMN IF NOT EXISTS aad_object_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS app_users_aad_object_id_key
    ON app_users(aad_object_id) WHERE aad_object_id IS NOT NULL;

-- Backfill: for every conversation reference whose aurora_user_id is a real
-- account (not a synthetic teams-… or @teams.aad placeholder), copy the
-- aad_object_id onto the corresponding app_users row. This recovers any
-- mapping that the Teams bot already managed to establish via Graph API
-- (when it was working) or via manual /link commands.
UPDATE app_users u
SET aad_object_id = ref.aad_object_id,
    updated_at = NOW()
FROM (
    SELECT DISTINCT ON (aurora_user_id) aurora_user_id, aad_object_id
    FROM teams_conversation_references
    WHERE aad_object_id IS NOT NULL
      AND aurora_user_id IS NOT NULL
      AND aurora_user_id NOT LIKE 'teams-%'
      AND aurora_user_id NOT LIKE '%@teams.aad'
      AND aurora_user_id <> aad_object_id  -- exclude synthetic rows where aurora_user_id == OID
) ref
WHERE u.id = ref.aurora_user_id
  AND u.aad_object_id IS NULL;

COMMIT;
