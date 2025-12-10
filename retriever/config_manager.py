"""
Configuration manager for scrapers.
Loads datasource configuration from PostgreSQL to control scraping behavior.
Handles cron-based scheduling for datasource scraping.
"""
import os
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import psycopg2
import psycopg2.extras

try:
    from croniter import croniter
    CRONITER_AVAILABLE = True
except ImportError:
    CRONITER_AVAILABLE = False
    # Note: This warning appears at module import time before logger is configured.
    # Consider moving croniter usage behind a lazy check instead of import-time warning.

logger = logging.getLogger(__name__)

if not CRONITER_AVAILABLE:
    logger.warning("croniter not installed - cron scheduling will be disabled")

# PostgreSQL connection parameters from environment
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "aurora")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "aurora_password")
POSTGRES_DB = os.getenv("POSTGRES_DB", "aurora")

# Construct connection string
PG_DSN = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"


class ConfigManager:
    """
    Manages scraper configuration from PostgreSQL.
    
    Handles cron-based scheduling:
    - get_due_datasources(): Returns datasources that should run NOW
    - get_startup_datasources(): Returns datasources with run_on_startup=true
    - is_schedule_due(): Checks if a cron schedule is due (or was missed)
    """
    
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
    
    def _ensure_connection(self) -> bool:
        """Ensure database connection is active, reconnect if needed."""
        if self.conn is None:
            logger.debug("No connection, attempting to connect...")
            self._connect()
        
        if self.conn is None:
            return False
        
        try:
            # Test connection
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1")
            return True
        except Exception as e:
            # Connection lost, try to reconnect
            logger.warning(f"PostgreSQL connection lost ({e}), attempting to reconnect...")
            self._connect()
            if self.conn is not None:
                logger.info("Successfully reconnected to PostgreSQL")
            return self.conn is not None
    
    def get_datasource_config(self, datasource_id: str) -> Dict[str, Any]:
        """
        Get configuration for a specific datasource.
        
        Args:
            datasource_id: Identifier for the datasource (e.g., 'wfa_resource_page')
            
        Returns:
            Configuration dict with all columns from system_configuration
        """
        default_config = {
            "datasource_id": datasource_id,
            "scrape_schedule": None,
            "run_on_startup": False,
            "check_content_hash": True,
            "publish_weight": 1.0,
            "update_weight": 0.8,
            "event_weight": 0.9,
            "last_scraped_at": None,
            "scraper_delay": 0.5,
            "max_resources": 150,
            "max_redirects": 10,
            "discovery_mode": "incremental",
            "consecutive_duplicates_limit": 5,
            "full_refresh_schedule": None
        }
        
        if not self._ensure_connection():
            return default_config
        
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM system_configuration WHERE datasource_id = %s", (datasource_id,))
                result = cur.fetchone()
                return dict(result) if result else default_config
        except Exception as e:
            logger.error(f"Error fetching configuration for {datasource_id}: {e}")
            return default_config
    
    def is_schedule_due(self, schedule: str, reference_time: Optional[datetime]) -> bool:
        """
        Check if a cron schedule is due to run.
        
        A schedule is due if the most recent scheduled time is after the reference_time.
        The caller decides what reference_time to use:
        - For previously scraped datasources: use last_scraped_at
        - For never-scraped datasources: use updated_at or created_at
        
        Args:
            schedule: Cron expression (e.g., '0 2 * * *')
            reference_time: Timestamp to compare against (last_scraped_at, updated_at, etc.)
            
        Returns:
            True if the schedule is due, False otherwise
        """
        if not CRONITER_AVAILABLE:
            logger.warning("croniter not available - cannot check schedule")
            return False
        
        if not schedule:
            return False
        
        if reference_time is None:
            logger.debug(f"Schedule {schedule}: no reference_time provided - skipping")
            return False
        
        try:
            now = datetime.now(timezone.utc)
            
            # Get the most recent scheduled time before now
            cron = croniter(schedule, now)
            prev_scheduled_time = cron.get_prev(datetime)
            
            # Ensure prev_scheduled_time is timezone-aware
            if prev_scheduled_time.tzinfo is None:
                prev_scheduled_time = prev_scheduled_time.replace(tzinfo=timezone.utc)
            
            # Ensure reference_time is timezone-aware
            if reference_time.tzinfo is None:
                reference_time = reference_time.replace(tzinfo=timezone.utc)
            
            # If the most recent scheduled time is after the reference, we're due
            is_due = prev_scheduled_time > reference_time
            logger.debug(f"Schedule {schedule}: prev_scheduled={prev_scheduled_time}, reference={reference_time}, due={is_due}")
            return is_due
            
        except Exception as e:
            logger.error(f"Error checking schedule '{schedule}': {e}")
            return False
    
    def get_startup_datasources(self) -> List[Dict[str, Any]]:
        """
        Get datasources that should run on retriever startup.
        
        Returns:
            List of datasource configurations where run_on_startup=true
        """
        return self._get_datasources("run_on_startup = TRUE")
    
    def get_due_datasources(self) -> List[Dict[str, Any]]:
        """
        Get datasources that are due to run based on their cron schedule.
        
        Checks each datasource with a scrape_schedule against its last_scraped_at
        to determine if it should run now.
        
        Returns:
            List of datasource configurations that should run now
        """
        if not CRONITER_AVAILABLE:
            logger.warning("croniter not available - returning no due datasources")
            return []
        
        all_scheduled = self._get_datasources("scrape_schedule IS NOT NULL")
        
        # Filter to only those that are due
        due_datasources = []
        for ds in all_scheduled:
            schedule = ds.get('scrape_schedule')
            last_scraped = ds.get('last_scraped_at')
            # Use last_scraped if available, otherwise fall back to updated_at/created_at
            reference_time = last_scraped or ds.get('updated_at') or ds.get('created_at')
            
            if self.is_schedule_due(schedule, reference_time):
                due_datasources.append(ds)
                logger.debug(f"Datasource {ds['datasource_id']} is due (schedule: {schedule})")
        
        return due_datasources
    
    def get_due_datasources_by_scraper_type(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get due datasources grouped by scraper_type.
        
        Returns:
            Dict mapping scraper_type to list of due datasource configurations
        """
        datasources = self.get_due_datasources()
        return self._group_by_scraper_type(datasources)
    
    def get_startup_datasources_by_scraper_type(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get startup datasources grouped by scraper_type.
        
        Returns:
            Dict mapping scraper_type to list of startup datasource configurations
        """
        datasources = self.get_startup_datasources()
        return self._group_by_scraper_type(datasources)
    
    def _group_by_scraper_type(self, datasources: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group a list of datasources by their scraper_type."""
        grouped = {}
        for ds in datasources:
            scraper_type = ds.get('scraper_type')
            if scraper_type:
                if scraper_type not in grouped:
                    grouped[scraper_type] = []
                grouped[scraper_type].append(ds)
        return grouped
    
    def _get_datasources(self, where_clause: str = "", params: tuple = ()) -> List[Dict[str, Any]]:
        """
        Fetch datasources from system_configuration with a custom WHERE clause.
        
        Args:
            where_clause: SQL WHERE clause (without 'WHERE' keyword), e.g., 'run_on_startup = TRUE'
            params: Parameters to pass to the query for parameterized values
            
        Returns:
            List of datasource configurations matching the criteria
        """
        if not self._ensure_connection():
            return []
        
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                base_query = "SELECT * FROM system_configuration WHERE scraper_type IS NOT NULL"
                if where_clause:
                    query = f"{base_query} AND {where_clause} ORDER BY scraper_type, datasource_id"
                else:
                    query = f"{base_query} ORDER BY scraper_type, datasource_id"
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"Error fetching datasources: {e}")
            return []

    def get_all_scheduled_datasources(self) -> List[Dict[str, Any]]:
        """
        Get all datasources that have a scraper_type configured.
        Used for status/info endpoints.
        
        Returns:
            List of all datasource configurations with scraper_type set
        """
        return self._get_datasources()
    
    def get_datasources_by_scraper_type(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get all datasources with scraper_type grouped by type.
        Used for status/info endpoints.
        
        Returns:
            Dict mapping scraper_type to list of datasource configurations
        """
        datasources = self.get_all_scheduled_datasources()
        return self._group_by_scraper_type(datasources)
    
    def get_full_refresh_datasources(self) -> List[Dict[str, Any]]:
        """
        Get datasources that are due for a full refresh based on their full_refresh_schedule.
        
        Full refresh is used for checking content updates (e.g., weekly scan to detect
        modified documents by comparing content hashes).
        
        Returns:
            List of datasource configurations that should run a full refresh now
        """
        if not CRONITER_AVAILABLE:
            logger.warning("croniter not available - returning no full refresh datasources")
            return []
        
        all_with_refresh = self._get_datasources("full_refresh_schedule IS NOT NULL")
        
        # Filter to only those that are due
        # We use last_scraped_at as the reference (could add a separate last_full_refresh_at column later)
        due_datasources = []
        for ds in all_with_refresh:
            schedule = ds.get('full_refresh_schedule')
            last_scraped = ds.get('last_scraped_at')
            reference_time = last_scraped or ds.get('updated_at') or ds.get('created_at')
            
            if self.is_schedule_due(schedule, reference_time):
                due_datasources.append(ds)
                logger.debug(f"Datasource {ds['datasource_id']} is due for full refresh (schedule: {schedule})")
        
        return due_datasources
    
    def update_last_scraped(self, datasource_id: str):
        """
        Update the last_scraped_at timestamp for a datasource.
        
        Args:
            datasource_id: Identifier for the datasource
        """
        if not self._ensure_connection():
            logger.warning(f"Cannot update last_scraped for {datasource_id}: no database connection")
            return
        
        try:
            with self.conn.cursor() as cur:
                query = """
                UPDATE system_configuration 
                SET last_scraped_at = NOW(),
                    updated_at = NOW()
                WHERE datasource_id = %s
                """
                cur.execute(query, (datasource_id,))
                
                if cur.rowcount > 0:
                    logger.info(f"Updated last_scraped_at for {datasource_id}")
                else:
                    logger.warning(f"Datasource {datasource_id} not found - skipping timestamp update")
        except Exception as e:
            logger.error(f"Error updating last_scraped for {datasource_id}: {e}")
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
