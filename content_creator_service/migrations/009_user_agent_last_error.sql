-- Add last_error / last_error_at to user_agent so the UI can surface
-- generation failures (e.g. OpenAI content filter) with a fix prompt.
ALTER TABLE user_agent
    ADD COLUMN IF NOT EXISTS last_error      TEXT        DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS last_error_at   TIMESTAMPTZ DEFAULT NULL;
