"""
Configuration manager for scrapers.
Loads datasource configuration from PostgreSQL to control scraping behavior.
"""
import os
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

# PostgreSQL connection string
PG_DSN = os.getenv(
    "PG_DSN",
    "postgresql://aurora:aurora_password@localhost:5432/aurora"
)

class ConfigManager:
    """Manages scraper configuration from PostgreSQL."""
    
    def __init__(self):
        self.conn = None
        self._connect()
    
    def _connect(self):
        """Establish PostgreSQL connection."""
        try:
            self.conn = psycopg2.connect(PG_DSN)
            self.conn.autocommit = True
            logger.info("Connected to PostgreSQL for configuration management")
        except Exception as e:
            logger.warning(f"Failed to connect to PostgreSQL: {e}. Using default configuration.")
            self.conn = None
    
    def get_datasource_config(self, datasource_id: str) -> Dict[str, Any]:
        """
        Get configuration for a specific datasource.
        
        Args:
            datasource_id: Identifier for the datasource (e.g., 'wfa_resource_page')
            
        Returns:
            Configuration dict with keys:
            - scrape_frequency: 'hourly', 'daily', 'weekly', 'monthly', 'manual'
            - check_content_hash: bool
            - publish_weight: float (0.0-1.0)
            - update_weight: float (0.0-1.0)
            - event_weight: float (0.0-1.0)
            - last_scraped_at: datetime or None
        """
        if not self.conn:
            # Return default config if no database connection
            return {
                "datasource_id": datasource_id,
                "scrape_frequency": "daily",
                "check_content_hash": True,
                "publish_weight": 1.0,
                "update_weight": 0.8,
                "event_weight": 0.9,
                "last_scraped_at": None
            }
        
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                query = "SELECT * FROM system_configuration WHERE datasource_id = %s"
                cur.execute(query, (datasource_id,))
                result = cur.fetchone()
                
                if result:
                    return dict(result)
                else:
                    # Return default config if not found
                    return {
                        "datasource_id": datasource_id,
                        "scrape_frequency": "daily",
                        "check_content_hash": True,
                        "publish_weight": 1.0,
                        "update_weight": 0.8,
                        "event_weight": 0.9,
                        "last_scraped_at": None
                    }
        except Exception as e:
            logger.error(f"Error fetching configuration for {datasource_id}: {e}")
            # Return default config on error
            return {
                "datasource_id": datasource_id,
                "scrape_frequency": "daily",
                "check_content_hash": True,
                "publish_weight": 1.0,
                "update_weight": 0.8,
                "event_weight": 0.9,
                "last_scraped_at": None
            }
    
    def should_scrape(self, datasource_id: str) -> bool:
        """
        Check if a datasource should be scraped based on its frequency configuration.
        
        Args:
            datasource_id: Identifier for the datasource
            
        Returns:
            True if scraping should proceed, False otherwise
        """
        config = self.get_datasource_config(datasource_id)
        
        frequency = config.get("scrape_frequency", "daily")
        last_scraped = config.get("last_scraped_at")
        
        # Always scrape if manual or no last_scraped timestamp
        if frequency == "manual" or not last_scraped:
            return True
        
        # Convert last_scraped to datetime if it's a string
        if isinstance(last_scraped, str):
            try:
                last_scraped = datetime.fromisoformat(last_scraped.replace('Z', '+00:00'))
            except Exception:
                # If parsing fails, scrape anyway
                return True
        
        now = datetime.now(last_scraped.tzinfo) if last_scraped.tzinfo else datetime.now()
        time_since_last = now - last_scraped
        
        # Check based on frequency
        if frequency == "hourly":
            return time_since_last >= timedelta(hours=1)
        elif frequency == "daily":
            return time_since_last >= timedelta(days=1)
        elif frequency == "weekly":
            return time_since_last >= timedelta(weeks=1)
        elif frequency == "monthly":
            return time_since_last >= timedelta(days=30)
        
        # Default: scrape
        return True
    
    def update_last_scraped(self, datasource_id: str):
        """
        Update the last_scraped_at timestamp for a datasource.
        
        Args:
            datasource_id: Identifier for the datasource
        """
        if not self.conn:
            logger.warning(f"Cannot update last_scraped for {datasource_id}: no database connection")
            return
        
        try:
            with self.conn.cursor() as cur:
                query = """
                INSERT INTO system_configuration (datasource_id, last_scraped_at)
                VALUES (%s, NOW())
                ON CONFLICT (datasource_id) DO UPDATE SET
                    last_scraped_at = NOW(),
                    updated_at = NOW()
                """
                cur.execute(query, (datasource_id,))
                logger.info(f"Updated last_scraped_at for {datasource_id}")
        except Exception as e:
            logger.error(f"Error updating last_scraped for {datasource_id}: {e}")
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
