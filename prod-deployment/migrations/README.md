# Database Migrations

This directory contains all database schema migrations for Aurora.

## 📁 Structure

Migrations are numbered SQL files that run in order:

```
migrations/
├── 001_initial_schema.sql      # Initial database schema
├── 002_seed_data.sql           # Initial seed data
├── 003_add_user_roles.sql      # Future migration example
└── 004_add_indexes.sql         # Future migration example
```

## 📝 Naming Convention

**Format:** `NNN_description.sql`

- `NNN` - Three-digit version number (001, 002, 003, etc.)
- `description` - Brief description using snake_case
- `.sql` - SQL file extension

**Examples:**
- `001_initial_schema.sql`
- `002_seed_data.sql`
- `003_add_user_roles.sql`
- `004_add_email_notifications.sql`
- `005_create_audit_log.sql`

## 🚀 Running Migrations

### Development (from repo root)
```bash
make migrate              # Run all pending migrations
make migrate-status       # Show migration status
```

### Production (from prod-deployment folder)
```bash
make migrate              # Run all pending migrations
make migrate-status       # Show migration status
```

### Manual (using script directly)
```bash
# From prod-deployment directory
./scripts/migrate.sh                    # Run all pending
./scripts/migrate.sh --status           # Show status
./scripts/migrate.sh 003_example.sql    # Run specific migration
```

## 📋 Creating New Migrations

### 1. Create Migration File

Create a new file in this directory with the next version number:

```bash
# Example: Adding a new column
cd prod-deployment/migrations
touch 003_add_notification_preferences.sql
```

### 2. Write SQL

```sql
-- 003_add_notification_preferences.sql
-- Add notification preferences to user_preferences table

ALTER TABLE user_preferences
ADD COLUMN notify_mentions BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE user_preferences
ADD COLUMN notify_updates BOOLEAN NOT NULL DEFAULT TRUE;

-- Add comment for documentation
COMMENT ON COLUMN user_preferences.notify_mentions IS 'Send notification when user is mentioned';
COMMENT ON COLUMN user_preferences.notify_updates IS 'Send notification for content updates';
```

### 3. Test Locally

```bash
# From repo root
make migrate

# Verify the change
docker compose exec postgres psql -U aurora -d aurora -c "\d user_preferences"
```

### 4. Deploy to Production

The migration will run automatically during deployment, or manually:

```bash
# On production server
cd prod-deployment
make migrate
```

## 🔍 Migration Tracking

Migrations are tracked in the `schema_migrations` table:

```sql
-- View applied migrations
SELECT * FROM schema_migrations ORDER BY version;

-- Check if specific migration was applied
SELECT * FROM schema_migrations WHERE version = '003';
```

The tracking table is automatically created by the migration script.

## ⚠️ Best Practices

### DO:
- ✅ **Always increment version numbers** - Never reuse or skip numbers
- ✅ **Test locally first** - Run on dev environment before production
- ✅ **Make migrations idempotent** - Use `IF NOT EXISTS` when possible
- ✅ **Keep migrations focused** - One logical change per migration
- ✅ **Add comments** - Explain what and why
- ✅ **Include rollback plan** - Document how to undo if needed

### DON'T:
- ❌ **Never modify existing migrations** - Once applied, they're immutable
- ❌ **Don't delete migrations** - They're part of the history
- ❌ **Avoid destructive operations** - Be very careful with DROP/DELETE
- ❌ **Don't skip testing** - Always test on dev first

## 📖 Example Migrations

### Adding a Column
```sql
-- 003_add_user_avatar.sql
ALTER TABLE app_users
ADD COLUMN avatar_url TEXT;

COMMENT ON COLUMN app_users.avatar_url IS 'URL to user profile avatar image';
```

### Creating a Table
```sql
-- 004_create_audit_log.sql
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    user_id TEXT REFERENCES app_users(id),
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_log_user ON audit_log(user_id);
CREATE INDEX idx_audit_log_resource ON audit_log(resource_type, resource_id);
CREATE INDEX idx_audit_log_created ON audit_log(created_at);
```

### Modifying Data
```sql
-- 005_update_default_preferences.sql
-- Update existing users to have new default preferences
UPDATE user_preferences
SET notify_mentions = TRUE
WHERE notify_mentions IS NULL;

UPDATE user_preferences
SET notify_updates = TRUE
WHERE notify_updates IS NULL;
```

### Adding Constraints
```sql
-- 006_add_email_validation.sql
-- Add constraint to ensure email format
ALTER TABLE app_users
ADD CONSTRAINT check_email_format 
CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$');
```

## 🔄 Initial Setup vs. Migrations

- **Initial Setup** (`001_initial_schema.sql`, `002_seed_data.sql`) - Run automatically by Docker when postgres container starts fresh
- **Subsequent Migrations** (`003+`) - Run manually via `make migrate` command

On fresh installations, all migrations run automatically. On existing installations, only new migrations run.

## 🐛 Troubleshooting

### Migration failed halfway
```bash
# Check postgres logs
docker compose logs postgres

# Check which migrations were applied
make migrate-status

# If needed, manually fix the issue in postgres
docker compose exec postgres psql -U aurora -d aurora
```

### Need to rollback
Currently, rollback is not automated. To manually rollback:

1. Write a reverse migration (or manually execute SQL)
2. Remove the entry from `schema_migrations` table
3. Re-run the corrected migration

### Migration shows as applied but didn't work
```bash
# Check the migration tracking
docker compose exec postgres psql -U aurora -d aurora -c \
  "SELECT * FROM schema_migrations WHERE version = '003';"

# Manually verify the database state
docker compose exec postgres psql -U aurora -d aurora -c "\d"
```

---

**Need Help?** Check the main documentation or ask the team!
