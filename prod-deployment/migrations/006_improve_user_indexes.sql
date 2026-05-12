-- Migration 006: Improve user table indexes and constraints
-- Adds explicit email index (UNIQUE creates implicit but this documents it)
-- and improves email handling for Cognito email changes

-- The UNIQUE constraint on email already creates an index, but we make it explicit
-- for clarity and to ensure it's optimized for lookups
CREATE INDEX IF NOT EXISTS idx_app_users_email ON app_users(email);

-- Add comment explaining the email uniqueness constraint behavior
COMMENT ON COLUMN app_users.email IS 'User email from Cognito. Unique constraint enforced. Note: If user changes email in Cognito, the create_user function will update the existing record.';

-- Add comment for id column
COMMENT ON COLUMN app_users.id IS 'Cognito user UUID (sub claim). This is the primary identifier and never changes for a user.';

-- Add comment for the table
COMMENT ON TABLE app_users IS 'Core user table. Users are automatically created/updated on login via auth service. The id (Cognito sub) is immutable, but email/display_name can be updated from Cognito.';
