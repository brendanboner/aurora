BEGIN;

CREATE TABLE IF NOT EXISTS post_comment (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,          -- Cognito UUID or Teams-SSO OID
    user_display_name TEXT,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_post_comment_post_id ON post_comment (post_id);

COMMIT;
