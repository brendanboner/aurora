"""Database migration script for fast pipeline tables.

Creates PostgreSQL tables for rollups, cache, and benchmark queries.
"""

import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from src.models.db_models import init_db
from src.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Initialize database schema for fast pipeline."""
    try:
        logger.info("Initializing fast pipeline database schema...")
        logger.info(f"Database: {settings.postgres_dsn}")
        
        engine = init_db(settings.postgres_dsn)
        
        logger.info("✓ Database schema initialized successfully")
        logger.info("  Created tables:")
        logger.info("    - rollups (pre-computed summaries)")
        logger.info("    - fast_cache (plan/result/answer cache)")
        logger.info("    - benchmark_queries (A/B test queries)")
        logger.info("    - benchmark_results (performance comparison)")
        
        return 0
        
    except Exception as e:
        logger.error(f"✗ Database initialization failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
