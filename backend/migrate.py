#!/usr/bin/env python3
"""
Database Migration Runner for Aurora Backend

Executes SQL migrations and performs data transformations.
Run with: python migrate.py [migration_number]
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime
from dateutil import parser as date_parser

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from src.services.postgres import get_conn

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_sql_migration(migration_file: Path):
    """Execute a SQL migration file."""
    logger.info(f"Running SQL migration: {migration_file.name}")
    
    with open(migration_file, 'r') as f:
        sql = f.read()
    
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Execute the entire migration file
            cur.execute(sql)
            logger.info(f"✓ SQL migration {migration_file.name} completed successfully")
            return True
    except Exception as e:
        logger.error(f"✗ SQL migration {migration_file.name} failed: {e}")
        conn.rollback()
        return False


def parse_neo4j_publish_dates():
    """
    Parse existing string publish_date fields in Neo4j Resources to datetime.
    
    This connects to Neo4j and updates Resource nodes where publish_date is a string
    to convert them to proper datetime objects.
    """
    logger.info("Parsing Neo4j Resource publish_date strings to datetime...")
    
    try:
        from neo4j_client import Neo4jClient
        
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
        neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")
        
        client = Neo4jClient(neo4j_uri, neo4j_user, neo4j_password, neo4j_database)
        
        # Query to find all Resources with string publish_date
        query = """
        MATCH (r:Resource)
        WHERE r.publish_date IS NOT NULL
        RETURN r.url_hash as url_hash, r.publish_date as publish_date, r.scraped_at as scraped_at
        """
        
        results = client.execute_query(query)
        logger.info(f"Found {len(results)} Resources with publish_date to process")
        
        updated_count = 0
        failed_count = 0
        skipped_count = 0
        
        for record in results:
            url_hash = record['url_hash']
            publish_date_str = record['publish_date']
            scraped_at = record['scraped_at']
            
            # Skip if already a datetime object
            if isinstance(publish_date_str, datetime):
                skipped_count += 1
                continue
            
            # Try to parse the date string
            try:
                if publish_date_str and publish_date_str != 'unknown':
                    # Use dateutil parser for flexible date parsing
                    parsed_date = date_parser.parse(publish_date_str)
                    
                    # Update the node with parsed datetime
                    update_query = """
                    MATCH (r:Resource {url_hash: $url_hash})
                    SET r.publish_date = datetime($publish_date)
                    """
                    
                    client.execute_write(
                        update_query, 
                        {"url_hash": url_hash, "publish_date": parsed_date.isoformat()}
                    )
                    updated_count += 1
                    
                    if updated_count % 100 == 0:
                        logger.info(f"Progress: {updated_count} dates parsed...")
                        
                else:
                    # Set to None if unknown
                    update_query = """
                    MATCH (r:Resource {url_hash: $url_hash})
                    SET r.publish_date = NULL
                    """
                    client.execute_write(update_query, {"url_hash": url_hash})
                    updated_count += 1
                    
            except Exception as e:
                logger.warning(f"Failed to parse date '{publish_date_str}' for {url_hash}: {e}")
                failed_count += 1
        
        logger.info(f"✓ Publish date parsing complete:")
        logger.info(f"  - Updated: {updated_count}")
        logger.info(f"  - Skipped (already datetime): {skipped_count}")
        logger.info(f"  - Failed: {failed_count}")
        
        return True
        
    except ImportError:
        logger.warning("neo4j_client not available - skipping Neo4j date parsing")
        return False
    except Exception as e:
        logger.error(f"✗ Neo4j date parsing failed: {e}")
        return False


def set_first_seen_at_from_created():
    """
    Set first_seen_at field on Resources using existing created_at timestamps.
    """
    logger.info("Setting first_seen_at from Neo4j created_at timestamps...")
    
    try:
        from neo4j_client import Neo4jClient
        
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
        neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")
        
        client = Neo4jClient(neo4j_uri, neo4j_user, neo4j_password, neo4j_database)
        
        # Update all Resources to set first_seen_at from created_at
        query = """
        MATCH (r:Resource)
        WHERE r.created_at IS NOT NULL AND r.first_seen_at IS NULL
        SET r.first_seen_at = r.created_at
        RETURN count(r) as count
        """
        
        result = client.execute_write(query)
        count = result[0]['count'] if result else 0
        
        logger.info(f"✓ Set first_seen_at for {count} Resources")
        return True
        
    except ImportError:
        logger.warning("neo4j_client not available - skipping first_seen_at setup")
        return False
    except Exception as e:
        logger.error(f"✗ Setting first_seen_at failed: {e}")
        return False


def run_migration_001():
    """Run migration 001: Add temporal tracking."""
    logger.info("=" * 80)
    logger.info("Running Migration 001: Add Temporal Tracking")
    logger.info("=" * 80)
    
    migrations_dir = Path(__file__).parent / "migrations"
    sql_file = migrations_dir / "001_add_temporal_tracking.sql"
    
    if not sql_file.exists():
        logger.error(f"Migration file not found: {sql_file}")
        return False
    
    # Step 1: Run SQL migration
    if not run_sql_migration(sql_file):
        logger.error("SQL migration failed - aborting")
        return False
    
    # Step 2: Parse existing publish_date strings in Neo4j
    parse_neo4j_publish_dates()
    
    # Step 3: Set first_seen_at from created_at
    set_first_seen_at_from_created()
    
    logger.info("=" * 80)
    logger.info("✓ Migration 001 completed successfully")
    logger.info("=" * 80)
    return True


def main():
    """Main migration runner."""
    if len(sys.argv) > 1:
        migration_number = sys.argv[1]
        logger.info(f"Running specific migration: {migration_number}")
        
        if migration_number == "001":
            success = run_migration_001()
        else:
            logger.error(f"Unknown migration: {migration_number}")
            success = False
    else:
        # Run all migrations
        logger.info("Running all migrations...")
        success = run_migration_001()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
