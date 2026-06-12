-- 015_survey_responses.sql
-- Quick-feedback survey results captured at /survey.
-- One row per submission; unlimited re-submissions per user.

CREATE TABLE IF NOT EXISTS survey_responses (
    id                  BIGSERIAL    PRIMARY KEY,
    user_id             TEXT         NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    user_email          TEXT,
    user_display_name   TEXT,
    submitted_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    duration_seconds    INTEGER,
    client_user_agent   TEXT,
    responses           JSONB        NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_survey_responses_user_submitted
    ON survey_responses (user_id, submitted_at DESC);

COMMENT ON TABLE survey_responses
    IS 'Quick-feedback survey results captured at /survey during the Aurora trial';
COMMENT ON COLUMN survey_responses.responses
    IS 'JSONB blob keyed by qN_<slug>; shape validated at the API layer';
COMMENT ON COLUMN survey_responses.duration_seconds
    IS 'Client-reported time from page mount to submit; informational only';
