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

echo "[DEBUG] Script starting with PID: $$"
echo "[DEBUG] Shell: $0"
echo "[DEBUG] Arguments: $@"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "[DEBUG] Script directory: $SCRIPT_DIR"

MIGRATIONS_DIR="$(cd "$SCRIPT_DIR/../migrations" && pwd)"
echo "[DEBUG] Migrations directory: $MIGRATIONS_DIR"

POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-aurora-postgres}"
echo "[DEBUG] PostgreSQL container: $POSTGRES_CONTAINER"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "[DEBUG] Color variables set"

# Load environment variables
echo "[DEBUG] Starting to load environment variables"
if [ -f "$SCRIPT_DIR/../.env" ]; then
    echo "[DEBUG] .env file found at: $SCRIPT_DIR/../.env"
    echo "[DEBUG] Setting auto-export mode"
    set -a  # automatically export all variables
    echo "[DEBUG] Processing .env file with grep and sed"
    env_content=$(grep -v '^#' "$SCRIPT_DIR/../.env" | grep -v '^$' | sed 's/=/="/' | sed 's/$/"/')
    echo "[DEBUG] Processed .env content (first few lines):"
    echo "$env_content" | head -5
    echo "[DEBUG] Sourcing processed content"
    source <(echo "$env_content")
    echo "[DEBUG] Stopping auto-export mode"
    set +a  # stop auto-export
    echo "[DEBUG] .env file loaded successfully"
else
    echo "[DEBUG] .env file not found at: $SCRIPT_DIR/../.env"
    echo -e "${YELLOW}Warning: .env file not found. Using defaults.${NC}"
fi

echo "[DEBUG] Setting database defaults"
POSTGRES_DB="${POSTGRES_DB:-aurora}"
POSTGRES_USER="${POSTGRES_USER:-user}"
echo "[DEBUG] Final database config - DB: $POSTGRES_DB, USER: $POSTGRES_USER, CONTAINER: $POSTGRES_CONTAINER"

# Function to print colored messages
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
    echo "[DEBUG] INFO: $1" >&2
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
    echo "[DEBUG] SUCCESS: $1" >&2
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    echo "[DEBUG] ERROR: $1" >&2
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
    echo "[DEBUG] WARNING: $1" >&2
}

# Check if postgres container is running
check_postgres() {
    echo "[DEBUG] Checking if PostgreSQL container '$POSTGRES_CONTAINER' is running"
    if ! docker ps --format '{{.Names}}' | grep -q "^${POSTGRES_CONTAINER}$"; then
        echo "[DEBUG] Container not found in running containers"
        error "PostgreSQL container '${POSTGRES_CONTAINER}' is not running!"
        error "Start services with: docker compose up -d postgres"
        echo "[DEBUG] Available running containers:"
        docker ps --format '{{.Names}}' >&2
        exit 1
    fi
    echo "[DEBUG] PostgreSQL container is running"
    info "PostgreSQL container is running"
}

# Create migrations tracking table if it doesn't exist
init_migrations_table() {
    echo "[DEBUG] Initializing migrations tracking table"
    info "Initializing migrations tracking table..."
    
    echo "[DEBUG] Running CREATE TABLE command for schema_migrations"
    local create_output
    create_output=$(docker exec -i "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<-EOSQL 2>&1
		CREATE TABLE IF NOT EXISTS schema_migrations (
		    id SERIAL PRIMARY KEY,
		    version VARCHAR(255) NOT NULL UNIQUE,
		    filename VARCHAR(255) NOT NULL,
		    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
		    checksum VARCHAR(64)
		);
		CREATE INDEX IF NOT EXISTS idx_schema_migrations_version ON schema_migrations(version);
	EOSQL
    )
    local create_exit_code=$?
    echo "[DEBUG] CREATE TABLE exit code: $create_exit_code"
    echo "[DEBUG] CREATE TABLE output: $create_output"
    echo "$create_output"
    
    if [ $create_exit_code -ne 0 ]; then
        echo "[DEBUG] CREATE TABLE failed"
        error "Failed to create migrations table"
        exit 1
    fi
    
    echo "[DEBUG] Migrations table initialization completed successfully"
    success "Migrations table ready"
}

# Get list of applied migrations
get_applied_migrations() {
    echo "[DEBUG] Getting list of applied migrations"
    local result
    local query_output
    local query_exit_code
    
    echo "[DEBUG] Running query: SELECT version FROM schema_migrations ORDER BY version"
    query_output=$(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c \
        "SELECT version FROM schema_migrations ORDER BY version;" 2>&1)
    query_exit_code=$?
    
    echo "[DEBUG] Query exit code: $query_exit_code"
    echo "[DEBUG] Raw query output: '$query_output'"
    
    if [ $query_exit_code -ne 0 ]; then
        echo "[DEBUG] Query failed, returning empty result"
        echo ""
        return
    fi
    
    result=$(echo "$query_output" | grep -v '^$' | sed 's/^[ \t]*//' || echo "")
    echo "[DEBUG] Processed result: '$result'"
    echo "$result"
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
    echo "[DEBUG] Starting run_all_migrations function"
    info "Checking for pending migrations in: $MIGRATIONS_DIR"
    
    echo "[DEBUG] Calling get_applied_migrations"
    # Get list of applied migrations
    applied_migrations=$(get_applied_migrations)
    info "Applied migrations found: $applied_migrations"
    
    echo "[DEBUG] Checking if migrations directory exists: $MIGRATIONS_DIR"
    # Find all .sql files in migrations directory
    if [ ! -d "$MIGRATIONS_DIR" ]; then
        echo "[DEBUG] Migrations directory does not exist"
        error "Migrations directory not found: $MIGRATIONS_DIR"
        exit 1
    fi
    
    echo "[DEBUG] Migrations directory exists"
    local pending_count=0
    local applied_count=0
    echo "[DEBUG] Initialized counters - pending: $pending_count, applied: $applied_count"
    
    echo "[DEBUG] Starting migration file loop"
    # Process migrations in order
    for migration_file in "$MIGRATIONS_DIR"/*.sql; do
        echo "[DEBUG] Processing file: $migration_file"
        if [ ! -f "$migration_file" ]; then
            echo "[DEBUG] No migration files found or file does not exist"
            warn "No migration files found in $MIGRATIONS_DIR"
            break
        fi
        
        local filename="$(basename "$migration_file")"
        local version="${filename%%_*}"
        echo "[DEBUG] Migration filename: $filename, version: $version"
        
        echo "[DEBUG] Checking if migration is already applied"
        echo "[DEBUG] Applied migrations list: '$applied_migrations'"
        echo "[DEBUG] Looking for version: '^${version}$'"
        
        # Check if already applied
        if echo "$applied_migrations" | grep -q "^${version}$"; then
            echo "[DEBUG] Migration already applied, incrementing applied_count"
            info "Skipping (already applied): $filename"
            applied_count=$((applied_count + 1))
            echo "[DEBUG] Applied count is now: $applied_count"
            continue
        fi
        
        echo "[DEBUG] Migration is pending, will run it"
        # Run the migration
        if run_migration "$migration_file"; then
            echo "[DEBUG] Migration successful, incrementing pending_count"
            pending_count=$((pending_count + 1))
            echo "[DEBUG] Pending count is now: $pending_count"
        else
            echo "[DEBUG] Migration failed, exiting"
            error "Migration failed. Stopping."
            exit 1
        fi
    done
    
    echo "[DEBUG] Migration loop completed"
    info "Migration loop completed. Pending: $pending_count, Applied: $applied_count"
    echo ""
    success "Migration complete!"
    info "Already applied: $applied_count"
    info "Newly applied: $pending_count"
    echo "[DEBUG] run_all_migrations function completed successfully"
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
    echo "[DEBUG] Starting main function"
    echo ""
    info "Aurora Database Migration Tool"
    echo ""
    
    echo "[DEBUG] Calling check_postgres"
    check_postgres
    echo "[DEBUG] check_postgres completed"
    
    echo "[DEBUG] Calling init_migrations_table"
    init_migrations_table
    echo "[DEBUG] init_migrations_table completed"
    
    echo "[DEBUG] Processing command line arguments: $@"
    if [ "$1" == "--status" ]; then
        echo "[DEBUG] Running status command"
        show_status
    elif [ "$1" == "--rollback" ]; then
        echo "[DEBUG] Rollback requested but not implemented"
        error "Rollback not yet implemented"
        exit 1
    elif [ -n "$1" ]; then
        echo "[DEBUG] Running specific migration: $1"
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
        echo "[DEBUG] Running all pending migrations"
        # Run all pending migrations
        run_all_migrations
    fi
    
    echo "[DEBUG] Main function completed successfully"
    echo ""
}

echo "[DEBUG] About to call main function"
main "$@"
echo "[DEBUG] Main function call completed"
echo "[DEBUG] Script ending normally"
exit 0
