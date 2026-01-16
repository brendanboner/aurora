#!/usr/bin/env bash

# =============================================================================
# Database Migration Script
# =============================================================================
# This script runs SQL migrations against the Aurora PostgreSQL database.
#
# Usage:
#   ./migrate.sh                    # Run all pending migrations
#   ./migrate.sh 003_add_column.sql # Run specific migration
#   ./migrate.sh --rollback         # (Future: rollback last migration)
#
# Prerequisites:
#   - Docker Compose running with postgres service
#   - Migration files in ../migrations/ directory
#   - Files named with format: NNN_description.sql (e.g., 001_initial_schema.sql)
# =============================================================================

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATIONS_DIR="$(cd "$SCRIPT_DIR/../migrations" && pwd)"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-aurora-postgres}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Load environment variables
if [ -f "$SCRIPT_DIR/../.env" ]; then
    set -a  # automatically export all variables
    source <(grep -v '^#' "$SCRIPT_DIR/../.env" | grep -v '^$' | sed 's/=/="/' | sed 's/$/"/')
    set +a  # stop auto-export
else
    echo -e "${YELLOW}Warning: .env file not found. Using defaults.${NC}"
fi

POSTGRES_DB="${POSTGRES_DB:-aurora}"
POSTGRES_USER="${POSTGRES_USER:-aurora}"

# Function to print colored messages
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Check if postgres container is running
check_postgres() {
    if ! docker ps --format '{{.Names}}' | grep -q "^${POSTGRES_CONTAINER}$"; then
        error "PostgreSQL container '${POSTGRES_CONTAINER}' is not running!"
        error "Start services with: docker compose up -d postgres"
        exit 1
    fi
    info "PostgreSQL container is running"
}

# Create migrations tracking table if it doesn't exist
init_migrations_table() {
    info "Initializing migrations tracking table..."
    docker exec -i "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<-EOSQL
		CREATE TABLE IF NOT EXISTS schema_migrations (
		    id SERIAL PRIMARY KEY,
		    version VARCHAR(255) NOT NULL UNIQUE,
		    filename VARCHAR(255) NOT NULL,
		    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
		    checksum VARCHAR(64)
		);
		CREATE INDEX IF NOT EXISTS idx_schema_migrations_version ON schema_migrations(version);
	EOSQL
    success "Migrations table ready"
}

# Get list of applied migrations
get_applied_migrations() {
    docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c \
        "SELECT version FROM schema_migrations ORDER BY version;" | grep -v '^$' | sed 's/^[ \t]*//'
}

# Get checksum of a file
get_checksum() {
    local file="$1"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        md5 -q "$file"
    else
        # Linux
        md5sum "$file" | awk '{print $1}'
    fi
}

# Run a single migration
run_migration() {
    local migration_file="$1"
    local filename="$(basename "$migration_file")"
    local version="${filename%%_*}"  # Extract version number (everything before first _)
    local checksum=$(get_checksum "$migration_file")
    
    info "Running migration: $filename"
    
    # Run the migration
    migration_output=$(docker exec -i "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$migration_file" 2>&1)
    migration_exit_code=$?
    
    # Print the output
    echo "$migration_output"
    
    # Check if migration succeeded (exit code 0 or only notices/warnings)
    if [ $migration_exit_code -eq 0 ] || ([ $migration_exit_code -ne 0 ] && echo "$migration_output" | grep -q "^NOTICE:\|^CREATE\|^INSERT\|^UPDATE\|^DELETE" && ! echo "$migration_output" | grep -q "^ERROR:"); then
        # Record successful migration
        docker exec -i "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<-EOSQL
			INSERT INTO schema_migrations (version, filename, checksum)
			VALUES ('$version', '$filename', '$checksum')
			ON CONFLICT (version) DO NOTHING;
		EOSQL
        success "Applied migration: $filename"
        return 0
    else
        error "Failed to apply migration: $filename"
        return 1
    fi
}

# Run all pending migrations
run_all_migrations() {
    info "Checking for pending migrations in: $MIGRATIONS_DIR"
    
    # Get list of applied migrations
    applied_migrations=$(get_applied_migrations)
    
    # Find all .sql files in migrations directory
    if [ ! -d "$MIGRATIONS_DIR" ]; then
        error "Migrations directory not found: $MIGRATIONS_DIR"
        exit 1
    fi
    
    local pending_count=0
    local applied_count=0
    
    # Process migrations in order
    for migration_file in "$MIGRATIONS_DIR"/*.sql; do
        if [ ! -f "$migration_file" ]; then
            warn "No migration files found in $MIGRATIONS_DIR"
            break
        fi
        
        local filename="$(basename "$migration_file")"
        local version="${filename%%_*}"
        
        # Check if already applied
        if echo "$applied_migrations" | grep -q "^${version}$"; then
            info "Skipping (already applied): $filename"
            ((applied_count++))
            continue
        fi
        
        # Run the migration
        if run_migration "$migration_file"; then
            ((pending_count++))
        else
            error "Migration failed. Stopping."
            exit 1
        fi
    done
    
    echo ""
    success "Migration complete!"
    info "Already applied: $applied_count"
    info "Newly applied: $pending_count"
}

# Show migration status
show_status() {
    info "Migration Status"
    echo ""
    echo "Applied Migrations:"
    docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
        "SELECT version, filename, applied_at FROM schema_migrations ORDER BY version;"
    echo ""
    
    info "Available Migrations:"
    for migration_file in "$MIGRATIONS_DIR"/*.sql; do
        if [ -f "$migration_file" ]; then
            basename "$migration_file"
        fi
    done
}

# Main execution
main() {
    echo ""
    info "Aurora Database Migration Tool"
    echo ""
    
    check_postgres
    init_migrations_table
    
    if [ "$1" == "--status" ]; then
        show_status
    elif [ "$1" == "--rollback" ]; then
        error "Rollback not yet implemented"
        exit 1
    elif [ -n "$1" ]; then
        # Run specific migration file
        if [ -f "$MIGRATIONS_DIR/$1" ]; then
            run_migration "$MIGRATIONS_DIR/$1"
        elif [ -f "$1" ]; then
            run_migration "$1"
        else
            error "Migration file not found: $1"
            exit 1
        fi
    else
        # Run all pending migrations
        run_all_migrations
    fi
    
    echo ""
}

main "$@"
