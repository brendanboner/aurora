"""
Database migration runner for Aurora.

This script checks which migrations have been applied and runs any pending migrations.
It uses a schema_migrations table to track which migrations have been applied.
"""
import os
import psycopg2
from pathlib import Path
import logging
import hashlib

logger = logging.getLogger(__name__)

PG_DSN = os.getenv(
    "PG_DSN",
    "postgresql://aurora:aurora_password@localhost:5432/aurora"
)

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "prod-deployment" / "migrations"


def get_connection():
    """Get database connection."""
    return psycopg2.connect(PG_DSN)


def init_migrations_table(conn):
    """Create migrations tracking table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id SERIAL PRIMARY KEY,
                version VARCHAR(255) NOT NULL UNIQUE,
                filename VARCHAR(255) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                checksum VARCHAR(64)
            );
            CREATE INDEX IF NOT EXISTS idx_schema_migrations_version 
            ON schema_migrations(version);
        """)
    conn.commit()
    logger.info("✓ Migrations tracking table ready")


def get_applied_migrations(conn):
    """Get set of already applied migration versions."""
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        return {row[0] for row in cur.fetchall()}


def calculate_checksum(content: str) -> str:
    """Calculate SHA256 checksum of migration content."""
    return hashlib.sha256(content.encode()).hexdigest()


def apply_migration(conn, filepath: Path):
    """Apply a single migration file."""
    version = filepath.stem  # e.g., "001_initial_schema"
    
    logger.info(f"Applying migration: {version}")
    
    # Read migration file
    with open(filepath, 'r') as f:
        sql_content = f.read()
    
    checksum = calculate_checksum(sql_content)
    
    # Execute migration
    with conn.cursor() as cur:
        try:
            cur.execute(sql_content)
            
            # Record that migration was applied
            cur.execute(
                """
                INSERT INTO schema_migrations (version, filename, checksum)
                VALUES (%s, %s, %s)
                """,
                (version, filepath.name, checksum)
            )
            
            conn.commit()
            logger.info(f"✓ Applied migration: {version}")
            
        except Exception as e:
            conn.rollback()
            logger.error(f"✗ Failed to apply migration {version}: {e}")
            raise


def run_migrations():
    """Run all pending migrations."""
    try:
        logger.info("Starting database migration check...")
        
        if not MIGRATIONS_DIR.exists():
            logger.warning(f"Migrations directory not found: {MIGRATIONS_DIR}")
            return
        
        conn = get_connection()
        
        # Initialize migrations tracking table
        init_migrations_table(conn)
        
        # Get already applied migrations
        applied = get_applied_migrations(conn)
        logger.info(f"Found {len(applied)} already applied migrations")
        
        # Get all migration files
        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        
        if not migration_files:
            logger.info("No migration files found")
            return
        
        # Apply pending migrations
        pending_count = 0
        for filepath in migration_files:
            version = filepath.stem
            
            if version not in applied:
                apply_migration(conn, filepath)
                pending_count += 1
        
        if pending_count == 0:
            logger.info("✓ All migrations are up to date")
        else:
            logger.info(f"✓ Applied {pending_count} new migration(s)")
        
        conn.close()
        
    except Exception as e:
        logger.error(f"Migration error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migrations()
