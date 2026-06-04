-- Migration 014: user "About me" / background field
--
-- Adds a free-text background column to user_preferences so users can
-- describe their role, interests, and how they want answers framed. This
-- replaces the per-chat persona-lens chip selector with a one-time
-- profile setting that the answer generator reads on every query.
--
-- Idempotent — safe to re-run.

ALTER TABLE user_preferences
    ADD COLUMN IF NOT EXISTS background TEXT DEFAULT NULL;

COMMENT ON COLUMN user_preferences.background IS
    'Free-text user-supplied summary of role, interests, and answer-style preferences. Injected into the answer-generation prompt when present.';
