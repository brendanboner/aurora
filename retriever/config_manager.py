"""
Configuration manager for scrapers.
Loads datasource configuration from Neo4j to control scraping behavior.
Handles cron-based scheduling for datasource scraping.
"""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from neo4j_client.client import Neo4jClient
from neo4j_client import GraphRepository
from settings import settings

try:
    from croniter import croniter
    CRONITER_AVAILABLE = True
except ImportError:
    CRONITER_AVAILABLE = False

logger = logging.getLogger(__name__)

if not CRONITER_AVAILABLE:
    logger.warning("croniter not installed - cron scheduling will be disabled")


class ConfigManager:
    """
    Manages scraper configuration from Neo4j.
    
    Handles cron-based scheduling:
    - get_due_datasources(): Returns datasources that should run NOW
    - get_startup_datasources(): Returns datasources with run_on_startup=true
    - is_schedule_due(): Checks if a cron schedule is due (or was missed)
    """
    
    def __init__(self):
        """Initialize ConfigManager with Neo4j connection."""
        self.neo4j_client = None
        self.graph_repository = None
        self._connect(settings)
    
    def _connect(self, settings):
        """Establish Neo4j connection."""
        try:
            self.neo4j_client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database=settings.neo4j_database
            )
            self.neo4j_client.connect()
            self.graph_repository = GraphRepository(self.neo4j_client)
            logger.info("Connected to Neo4j for configuration management")
        except Exception as e:
            logger.warning(f"Failed to connect to Neo4j: {e}. Using default configuration.")
            self.neo4j_client = None
            self.graph_repository = None
    
    def _ensure_connection(self) -> bool:
        """Ensure Neo4j connection is active, reconnect if needed."""
        if self.graph_repository is None or self.neo4j_client is None:
            logger.debug("No connection, attempting to connect...")
            self._connect(settings)
        
        if self.graph_repository is None:
            return False
        
        try:
            # Test connection with a simple query
            self.neo4j_client.execute_query("RETURN 1 as test")
            return True
        except Exception as e:
            # Connection lost, try to reconnect
            logger.warning(f"Neo4j connection lost ({e}), attempting to reconnect...")
            self._connect(settings)
            if self.graph_repository is not None:
                logger.info("Successfully reconnected to Neo4j")
            return self.graph_repository is not None
    
    def get_datasource_config(self, datasource_id: str) -> Dict[str, Any]:
        """
        Get configuration for a specific datasource.
        
        Args:
            datasource_id: Identifier for the datasource (e.g., 'wfa_resource_page')
            
        Returns:
            Configuration dict with all columns from DataSource node
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
            result = self.graph_repository.get_datasource_config(datasource_id)
            return result if result else default_config
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
        if not self._ensure_connection():
            return []
        
        try:
            return self.graph_repository.get_startup_datasources()
        except Exception as e:
            logger.error(f"Error fetching startup datasources: {e}")
            return []
    
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
        
        if not self._ensure_connection():
            return []
        
        try:
            all_scheduled = self.graph_repository.get_scheduled_datasources()
        except Exception as e:
            logger.error(f"Error fetching scheduled datasources: {e}")
            return []
        
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
    
    def get_all_scheduled_datasources(self) -> List[Dict[str, Any]]:
        """
        Get all datasources that have a scraper_type configured.
        Used for status/info endpoints.
        
        Returns:
            List of all datasource configurations with scraper_type set
        """
        if not self._ensure_connection():
            return []
        
        try:
            return self.graph_repository.get_all_datasources_with_scraper()
        except Exception as e:
            logger.error(f"Error fetching all datasources: {e}")
            return []
    
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
        
        if not self._ensure_connection():
            return []
        
        try:
            all_with_refresh = self.graph_repository.get_full_refresh_datasources()
        except Exception as e:
            logger.error(f"Error fetching full refresh datasources: {e}")
            return []
        
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
            self.graph_repository.update_datasource_last_scraped(datasource_id)
        except Exception as e:
            logger.error(f"Error updating last_scraped for {datasource_id}: {e}")
    
    def close(self):
        """Close Neo4j connection."""
        if self.neo4j_client:
            self.neo4j_client.close()
            self.neo4j_client = None
            self.graph_repository = None
