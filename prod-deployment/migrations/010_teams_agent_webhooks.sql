BEGIN;

ALTER TABLE teams_conversation_references
  ADD COLUMN IF NOT EXISTS agent_webhook_urls JSONB NOT NULL DEFAULT '{}';

COMMENT ON COLUMN teams_conversation_references.agent_webhook_urls IS
  'Maps agent slug → Teams Incoming Webhook URL for this conversation. '
  'Webhooks post with custom agent name/icon; used in preference to bot push when set. '
  'Example: {"aurora-ietf": "https://outlook.office.com/webhook/...", "aurora-wba-wifi-design-wg": "https://..."}';

COMMIT;
