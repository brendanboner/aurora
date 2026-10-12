-- Add user feedback table for collecting feedback, bugs, and accessibility issues
CREATE TABLE IF NOT EXISTS user_feedback (
    id              SERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    feedback_text   TEXT NOT NULL,
    category        TEXT NOT NULL CHECK (category IN ('feedback', 'bug', 'accessibility', 'styling')),
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'in_progress', 'paused')),
    priority        TEXT CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_user_feedback_user_id ON user_feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_user_feedback_status ON user_feedback(status);
CREATE INDEX IF NOT EXISTS idx_user_feedback_category ON user_feedback(category);
CREATE INDEX IF NOT EXISTS idx_user_feedback_priority ON user_feedback(priority);
CREATE INDEX IF NOT EXISTS idx_user_feedback_submitted_at ON user_feedback(submitted_at DESC);

-- Add trigger to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_user_feedback_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_user_feedback_updated_at
BEFORE UPDATE ON user_feedback
FOR EACH ROW EXECUTE PROCEDURE update_user_feedback_updated_at();

COMMENT ON TABLE user_feedback IS 'User feedback submissions including bugs, accessibility issues, and general feedback';
COMMENT ON COLUMN user_feedback.category IS 'Type of feedback: feedback (general), bug (functional issue), accessibility (a11y issue), styling (UI/UX issue)';
COMMENT ON COLUMN user_feedback.status IS 'Current status: open (new), in_progress (being addressed), paused (on hold), closed (resolved)';
COMMENT ON COLUMN user_feedback.priority IS 'Admin-assigned priority level';
