import abc
import aiohttp
import json
import logging
import hashlib
import uuid
import io
from typing import Any, Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime, timezone
import redis
import pypdf
from dateutil.parser import parse as date_parse

from rabbitmq_client.producer import RabbitMQProducer
from neo4j_client.client import Neo4jClient
from neo4j_client import GraphRepository, IngestionBatch, IngestionBatchBelongsToDataSource
from settings import settings
from config_manager import ConfigManager

logger = logging.getLogger(__name__)

@dataclass
class Resource:
    """Base resource data structure that all scrapers should use"""
    title: str
    url: str
    category: str
    content: Optional[str] = None
    publish_date: Optional[str] = None  # ISO 8601 format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
    datasource_id: Optional[str] = None  # Which scraper/site this came from
    batch_id: Optional[str] = None       # Ingestion batch ID for tracking
    scraped_at: Optional[str] = None    # ISO 8601 format (YYYY-MM-DDTHH:MM:SS)
    
    def __post_init__(self):
        """Set scraped_at timestamp if not provided"""
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()
    
    def to_message(self) -> Dict[str, Any]:
        """Convert to RabbitMQ message format"""
        return {
            "message_type": "resource",
            "resource_data": {
                "title": self.title,
                "url": self.url,
                "category": self.category,
                "content": self.content,
                "publish_date": self.publish_date,
            },
            "datasource_id": self.datasource_id,
            "batch_id": self.batch_id,
            "scraped_at": self.scraped_at
        }


@dataclass
class Event:
    """Event data structure for calendar events and scheduled activities"""
    name: str                           # Human-readable event name
    event_type: str                     # 'meeting', 'conference', 'webinar', 'deadline', 'workshop', etc.
    start_date: str                     # ISO 8601 format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
    end_date: Optional[str] = None      # ISO 8601 format
    location: str = ""                  # Physical location or "Virtual" or "Hybrid"
    timezone: Optional[str] = None      # e.g., "America/Los_Angeles", "UTC"
    description: str = ""               # Event details, agenda, etc.
    url: Optional[str] = None           # Event page or registration URL
    status: str = "scheduled"           # 'scheduled', 'cancelled', 'rescheduled'
    datasource_id: Optional[str] = None # Which scraper/source this came from
    batch_id: Optional[str] = None      # Ingestion batch ID for tracking
    scraped_at: Optional[str] = None    # ISO 8601 format (YYYY-MM-DDTHH:MM:SS)
    
    def __post_init__(self):
        """Set scraped_at timestamp if not provided"""
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()
    
    def to_message(self) -> Dict[str, Any]:
        """
        Convert to RabbitMQ message format.
        
        Sanitizes location and description fields if sanitization is enabled
        to remove sensitive meeting information (URLs, passcodes, etc.)
        """
        from settings import settings
        
        location = self.location
        description = self.description
        
        # Sanitize if enabled
        if settings.sanitize_events:
            try:
                from utils.sensitive_info_scrubber import sanitize_event_data
                location, description = sanitize_event_data(self.location, self.description)
            except Exception as e:
                # Log error but don't fail - better to send unsanitized than lose data
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to sanitize event data: {e}. Sending original data.")
        
        return {
            "message_type": "event",
            "event_data": {
                "name": self.name,
                "event_type": self.event_type,
                "start_date": self.start_date,
                "end_date": self.end_date,
                "location": location,
                "timezone": self.timezone,
                "description": description,
                "url": self.url,
                "status": self.status
            },
            "datasource_id": self.datasource_id,
            "batch_id": self.batch_id,
            "scraped_at": self.scraped_at
        }

class BaseScraper:
    """Base class for all scrapers with common RabbitMQ publishing functionality"""
    
    # Subclasses can override this to set their scraper name for file naming
    scraper_name: str = "default"
    
    def __init__(self):
        # Suppress verbose pika logging - only show errors
        logging.getLogger('pika').setLevel(logging.ERROR)
        
        # Initialize RabbitMQ producer using settings
        self.rabbitmq_producer = RabbitMQProducer(
            host=settings.rabbitmq_host,
            port=settings.rabbitmq_port,
            user=settings.rabbitmq_user,
            password=settings.rabbitmq_password,
            queue=settings.rabbitmq_queue
        )
        self.session = None
        
        # Batch tracking for ingestion
        self._current_batch_id: Optional[str] = None
        self._current_datasource_id: Optional[str] = None
        self._batch_scrape_started_at: Optional[datetime] = None
        self._batch_items_count: int = 0
        self._current_datasource_config: Optional[Dict[str, Any]] = None
        
        # Collect mode: when enabled, messages are collected instead of published
        self._collect_mode: bool = False
        self._collected_messages: List[Dict[str, Any]] = []
        
        # Initialize ONE Neo4j client shared by both config_manager and graph operations
        self.neo4j_client: Optional[Neo4jClient] = None
        self.graph_repository: Optional[GraphRepository] = None
        self.config_manager: Optional[ConfigManager] = None
        
        try:
            self.neo4j_client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database=settings.neo4j_database
            )
            self.neo4j_client.connect()
            
            # Share the same Neo4j client with both components
            self.graph_repository = GraphRepository(self.neo4j_client)
            self.config_manager = ConfigManager(neo4j_client=self.neo4j_client)
            
            logger.info("Neo4j connection established for scraper (shared by config and graph operations)")
        except Exception as e:
            logger.warning(f"Failed to connect to Neo4j: {e}. URL deduplication and batch tracking will be disabled.")
            self.neo4j_client = None
        
        # Initialize Redis for monitoring
        try:
            self.redis_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                decode_responses=True,
                socket_connect_timeout=5
            )
            # Test connection
            self.redis_client.ping()
            logger.info("Redis connection established for monitoring")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Monitoring will be disabled.")
            self.redis_client = None
        
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        # Clear heartbeat so curator knows scraping is done
        self.clear_heartbeat()
        
        if self.session:
            await self.session.close()
        if self.neo4j_client:
            self.neo4j_client.close()
        if self.config_manager:
            self.config_manager.close()
    
    def update_heartbeat(self):
        """Update retriever heartbeat timestamp in Redis."""
        if self.redis_client:
            try:
                self.redis_client.set("retriever:heartbeat", datetime.now().timestamp(), ex=300)
            except Exception as e:
                logger.warning(f"Failed to update heartbeat: {e}")

    def clear_heartbeat(self):
        """
        Clear retriever heartbeat from Redis.
        
        Call this when scraping completes so the curator doesn't have to wait
        for the 5-minute TTL to expire before triggering topic organization.
        """
        if self.redis_client:
            try:
                self.redis_client.delete("retriever:heartbeat")
                logger.debug("Cleared retriever heartbeat")
            except Exception as e:
                logger.warning(f"Failed to clear heartbeat: {e}")
    
    def update_current_processing(self, item, stage: str):
        """
        Update current processing status in Redis.
        
        Args:
            item: Resource or Event object being processed
            stage: Current processing stage
        """
        if self.redis_client:
            try:
                # Handle both Resource and Event objects
                if isinstance(item, Event):
                    processing_data = {
                        "title": item.name,  # Use 'title' for consistency with digester
                        "url": item.url or "",
                        "category": "event",  # Events are categorized as 'event'
                        "status": "retrieving",
                        "stage": stage,
                        "started_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat()
                    }
                else:  # Resource
                    processing_data = {
                        "title": item.title,
                        "url": item.url,
                        "category": item.category,
                        "status": "retrieving",
                        "stage": stage,
                        "started_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat()
                    }
                self.redis_client.set("retriever:current", json.dumps(processing_data), ex=300)
            except Exception as e:
                logger.warning(f"Failed to update current processing: {e}")
    
    def clear_current_processing(self):
        """Clear current processing status in Redis."""
        if self.redis_client:
            try:
                self.redis_client.delete("retriever:current")
            except Exception as e:
                logger.warning(f"Failed to clear current processing: {e}")

    def _normalize_datetime(self, value: Any) -> Optional[datetime]:
        """Convert strings/datetimes to timezone-aware UTC datetimes."""
        if value is None:
            return None

        try:
            if isinstance(value, datetime):
                parsed = value
            else:
                parsed = date_parse(str(value))
        except Exception as e:
            logger.debug(f"Could not parse datetime value '{value}': {e}")
            return None

        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _get_lookback_cutoff(self) -> Optional[datetime]:
        """Return the global automated-ingestion cutoff datetime."""
        if not self.config_manager:
            return None

        try:
            return self.config_manager.get_ingestion_lookback_cutoff()
        except Exception as e:
            logger.warning(f"Failed to resolve ingestion lookback cutoff: {e}")
            return None

    def _get_current_datasource_config(self, datasource_id: Optional[str]) -> Dict[str, Any]:
        """Return cached datasource configuration for the active scraper run."""
        if not datasource_id or not self.config_manager:
            return {}

        if (
            self._current_datasource_config is not None
            and self._current_datasource_id == datasource_id
        ):
            return self._current_datasource_config

        config = self.config_manager.get_datasource_config(datasource_id)
        if self._current_datasource_id == datasource_id:
            self._current_datasource_config = config
        return config

    def _is_initial_scrape(self, datasource_id: Optional[str]) -> bool:
        """Return True when the datasource has not yet recorded a successful scrape."""
        config = self._get_current_datasource_config(datasource_id)
        return self._normalize_datetime(config.get("last_scraped_at")) is None

    def _record_filtered_item(
        self,
        item_type: str,
        title: str,
        url: str,
        datasource_id: Optional[str],
        reason: str,
        reference_date: Optional[str]
    ) -> None:
        """Record filtered items to Redis monitoring so operators can see skip reasons."""
        if not self.redis_client:
            return

        try:
            filtered_data = {
                "title": title,
                "url": url or "",
                "category": item_type,
                "status": "skipped",
                "stage": "filtered",
                "started_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "datasource_id": datasource_id or "",
                "publish_date": reference_date or "",
                "reason": reason,
            }
            self.redis_client.lpush("processing:completed", json.dumps(filtered_data))
            self.redis_client.ltrim("processing:completed", 0, 19)
        except Exception as e:
            logger.warning(f"Failed to record filtered item: {e}")

    def _should_skip_by_lookback(
        self,
        item_type: str,
        datasource_id: Optional[str],
        reference_value: Optional[str],
        title: str,
        url: str,
        allow_initial_backfill: bool = False,
    ) -> bool:
        """Determine whether an automated scraper item should be filtered as too old."""
        cutoff = self._get_lookback_cutoff()
        if cutoff is None:
            return False

        if allow_initial_backfill and self._is_initial_scrape(datasource_id):
            return False

        reference_dt = self._normalize_datetime(reference_value)
        if reference_dt is None:
            logger.info(
                f"Allowing {item_type} without temporal metadata for datasource {datasource_id or 'unknown'}: {title}"
            )
            return False

        if reference_dt >= cutoff:
            return False

        lookback = self.config_manager.get_ingestion_lookback() if self.config_manager else {"value": 12, "unit": "months"}
        reason = (
            f"older than automated ingestion lookback ({lookback['value']} {lookback['unit']})"
        )
        logger.info(
            f"Skipping stale {item_type} for datasource {datasource_id or 'unknown'}: "
            f"{title} ({reference_dt.isoformat()} < {cutoff.isoformat()})"
        )
        self._record_filtered_item(
            item_type=item_type,
            title=title,
            url=url,
            datasource_id=datasource_id,
            reason=reason,
            reference_date=reference_dt.isoformat(),
        )
        return True
    
    # =========================================================================
    # Batch Tracking Methods
    # =========================================================================
    
    def start_batch(self, datasource_id: str) -> str:
        """
        Start a new ingestion batch for a datasource.
        Creates the IngestionBatch node in Neo4j with status='retrieving'.
        
        In collect mode, generates a batch_id but does NOT create the batch node
        since items won't be published to the queue.
        
        Args:
            datasource_id: ID of the datasource being scraped
            
        Returns:
            The batch_id (UUID) for this batch
        """
        # CRITICAL: If there's already an active batch, log a warning
        # This should not happen in normal operation - batches should be ended before starting new ones
        if self._current_batch_id:
            logger.warning(
                f"start_batch() called while batch {self._current_batch_id} is still active. "
                f"Previous datasource: {self._current_datasource_id}, New datasource: {datasource_id}. "
                f"This indicates end_batch() was not called properly."
            )
            # Force end the previous batch to prevent state pollution
            self.end_batch(self._batch_items_count)
        
        self._current_batch_id = str(uuid.uuid4())
        self._current_datasource_config = None
        self._current_datasource_id = datasource_id
        self._batch_scrape_started_at = datetime.now()
        self._batch_items_count = 0
        self._current_datasource_config = self._get_current_datasource_config(datasource_id)
        
        # Skip batch node creation in collect mode
        if self._collect_mode:
            logger.debug(f"Collect mode: skipping batch node creation for {datasource_id}")
            return self._current_batch_id
        
        if self.graph_repository:
            try:
                batch = IngestionBatch(
                    batch_id=self._current_batch_id,
                    datasource_id=datasource_id,
                    status="retrieving",
                    scrape_started_at=self._batch_scrape_started_at,
                    items_scraped=0,
                    items_digested=0
                )
                self.graph_repository.create_node(batch)
                logger.debug(f"Created ingestion batch node {self._current_batch_id}")
                
                # Link batch to datasource
                rel = IngestionBatchBelongsToDataSource(
                    source_id=self._current_batch_id,
                    target_id=datasource_id
                )
                self.graph_repository.create_relationship(rel)
                logger.debug(f"Linked batch {self._current_batch_id} to datasource {datasource_id}")
                
            except Exception as e:
                logger.error(f"Failed to create ingestion batch node or relationship: {e}", exc_info=True)
        
        return self._current_batch_id
    
    def end_batch(self, items_scraped: int):
        """
        End the current batch after scraping completes.
        Updates the IngestionBatch node to status='digesting' or 'completed'.
        
        If digester has already processed all items while we were still retrieving,
        the batch is marked as 'completed' directly. This handles the race condition
        where digestion finishes before retrieval completes.
        
        If no items were scraped (items_scraped == 0), the batch is also marked
        as 'completed' directly since there's nothing to digest.
        
        In collect mode, skips batch updates since nothing was published to the queue.
        
        Args:
            items_scraped: Total number of items sent to the queue (or collected) - used for logging
        """
        if not self._current_batch_id:
            logger.warning("end_batch called without active batch")
            return
        
        # Skip batch updates in collect mode
        if self._collect_mode:
            logger.debug(f"Collect mode: skipping batch completion for {self._current_batch_id}")
            # Clear batch state
            self._current_batch_id = None
            self._current_datasource_id = None
            self._batch_scrape_started_at = None
            self._batch_items_count = 0
            return
        
        scrape_completed_at = datetime.now()
        batch_id = self._current_batch_id
        
        # Update batch status in Neo4j (items_scraped already incremented in real-time)
        if self.graph_repository:
            try:
                # Determine appropriate status based on digestion progress
                if items_scraped == 0:
                    # No items to digest - mark as completed immediately
                    status = "completed"
                    logger.debug(f"Batch {batch_id}: no items scraped, marking as completed")
                else:
                    # Check if digester has already finished processing all items
                    # This handles the race condition where digestion completes before retrieval
                    batch_node = IngestionBatch(
                        batch_id=batch_id,
                        datasource_id=self._current_datasource_id or ""
                    )
                    batch_info = self.graph_repository.get_node(batch_node)
                    items_digested = batch_info.get("items_digested", 0) if batch_info else 0
                    
                    if items_digested >= items_scraped:
                        status = "completed"
                        logger.info(
                            f"Batch {batch_id}: digester already finished "
                            f"({items_digested}/{items_scraped} items), marking as completed"
                        )
                    else:
                        status = "digesting"
                        logger.info(
                            f"Batch {batch_id}: {items_digested}/{items_scraped} items digested, "
                            f"setting status to digesting"
                        )
                
                self.graph_repository.update_batch_status(
                    batch_id=batch_id,
                    status=status,
                    scrape_completed_at=scrape_completed_at
                )
                logger.info(
                    f"Batch {batch_id} retrieval complete: "
                    f"{items_scraped} items sent to digester (status={status})"
                )
            except Exception as e:
                logger.error(f"Failed to update batch status: {e}")
        
        # Clear batch state
        logger.debug(f"Clearing batch state for batch_id={batch_id}, datasource_id={self._current_datasource_id}")
        self._current_batch_id = None
        self._current_datasource_id = None
        self._batch_scrape_started_at = None
        self._batch_items_count = 0
        self._current_datasource_config = None
    
    def get_current_batch_id(self) -> Optional[str]:
        """Get the current batch ID, if a batch is active."""
        return self._current_batch_id
    
    def increment_batch_count(self, count: int = 1):
        """
        Increment the item count for the current batch.
        Also updates items_scraped in Neo4j so digester can track progress.
        """
        self._batch_items_count += count
        
        # Update Neo4j batch counter (skip in collect mode)
        if not self._collect_mode and self._current_batch_id and self.graph_repository:
            try:
                self.graph_repository.increment_batch_scraped(self._current_batch_id, count)
            except Exception as e:
                logger.warning(f"Failed to increment batch scraped count in Neo4j: {e}")
    
    # =========================================================================
    # Collect Mode Methods
    # =========================================================================
    
    def enable_collect_mode(self):
        """
        Enable collect mode - messages will be stored instead of published to RabbitMQ.
        Use get_collected_messages() to retrieve collected messages after scraping.
        """
        self._collect_mode = True
        self._collected_messages = []
        logger.info("Collect mode enabled - messages will be collected instead of published")
    
    def disable_collect_mode(self):
        """Disable collect mode - messages will be published to RabbitMQ."""
        self._collect_mode = False
        logger.info("Collect mode disabled - messages will be published to RabbitMQ")
    
    def get_collected_messages(self) -> List[Dict[str, Any]]:
        """
        Get all messages collected during collect mode.
        
        Returns:
            List of message dictionaries (resources and events)
        """
        return self._collected_messages.copy()
    
    def clear_collected_messages(self):
        """Clear all collected messages."""
        self._collected_messages = []
    
    def _compute_url_hash(self, url: str) -> str:
        """
        Compute SHA256 hash of a URL.
        
        Args:
            url: URL to hash
            
        Returns:
            SHA256 hash of the URL as a hex string
        """
        return hashlib.sha256(url.encode('utf-8')).hexdigest()
    
    def url_exists_in_db(self, url: str) -> bool:
        """
        Check if a URL already exists in the Neo4j database.
        
        Args:
            url: URL to check
            
        Returns:
            True if URL exists in database, False otherwise
        """
        if not self.neo4j_client:
            # If Neo4j is not available, assume URL doesn't exist (fail open)
            logger.warning("Neo4j client not available, cannot check for duplicate URLs")
            return False
        
        try:
            url_hash = self._compute_url_hash(url)
            query = """
            MATCH (r:Resource {url_hash: $url_hash})
            RETURN r.url_hash as url_hash
            LIMIT 1
            """
            result = self.neo4j_client.execute_query(query, {"url_hash": url_hash})
            return len(result) > 0
        except Exception as e:
            logger.error(f"Error checking URL existence in Neo4j: {e}")
            # Fail open - if we can't check, assume it doesn't exist
            return False
    
    def batch_check_urls_exist(self, urls: List[str]) -> Dict[str, bool]:
        """
        Check if multiple URLs exist in the Neo4j database in a single query.
        
        Args:
            urls: List of URLs to check
            
        Returns:
            Dictionary mapping each URL to True if it exists, False otherwise
        """
        if not urls:
            return {}
        
        if not self.neo4j_client:
            logger.warning("Neo4j client not available, cannot check for duplicate URLs")
            return {url: False for url in urls}
        
        try:
            # Compute hashes for all URLs
            url_to_hash = {url: self._compute_url_hash(url) for url in urls}
            hash_to_url = {h: u for u, h in url_to_hash.items()}
            url_hashes = list(url_to_hash.values())
            
            query = """
            UNWIND $url_hashes AS hash
            OPTIONAL MATCH (r:Resource WHERE r.url_hash = hash)
            RETURN hash, r IS NOT NULL AS exists
            """
            results = self.neo4j_client.execute_query(query, {"url_hashes": url_hashes})
            
            # Build the result dictionary
            exists_map = {}
            for record in results:
                url_hash = record.get('hash')
                exists = record.get('exists', False)
                url = hash_to_url.get(url_hash)
                if url:
                    exists_map[url] = exists
            
            # Ensure all input URLs have a result (default to False if missing)
            return {url: exists_map.get(url, False) for url in urls}
            
        except Exception as e:
            logger.error(f"Error batch checking URLs in Neo4j: {e}")
            # Fail open - if we can't check, assume they don't exist
            return {url: False for url in urls}
    
    def get_resource_publish_date(self, url: str) -> Optional[str]:
        """
        Get the stored publish_date for a resource by URL.
        
        Used to compare against a new revision date to detect updates.
        
        Args:
            url: Resource URL to look up
            
        Returns:
            publish_date string (YYYY-MM-DD) if found, None otherwise
        """
        if not self.neo4j_client:
            logger.warning("Neo4j client not available, cannot get publish date")
            return None
        
        try:
            url_hash = self._compute_url_hash(url)
            query = """
            MATCH (r:Resource {url_hash: $url_hash})
            RETURN r.publish_date as publish_date
            LIMIT 1
            """
            result = self.neo4j_client.execute_query(query, {"url_hash": url_hash})
            if result and result[0].get('publish_date'):
                return result[0]['publish_date']
            return None
        except Exception as e:
            logger.error(f"Error getting publish date from Neo4j: {e}")
            return None
    
    def is_resource_updated(self, url: str, new_revision_date: str) -> bool:
        """
        Check if a resource has been updated based on revision date.
        
        Compares the new revision date against the stored publish_date.
        Returns True if the resource is new or has been updated.
        
        Args:
            url: Resource URL
            new_revision_date: New revision date (YYYY-MM-DD format)
            
        Returns:
            True if resource is new or updated, False if unchanged
        """
        stored_date = self.get_resource_publish_date(url)
        
        if stored_date is None:
            # Resource doesn't exist - it's new
            return True
        
        # Compare dates (both should be YYYY-MM-DD format)
        try:
            # Normalize to just date part for comparison
            stored_date_str = stored_date[:10] if stored_date else ""
            new_date_str = new_revision_date[:10] if new_revision_date else ""
            
            if new_date_str > stored_date_str:
                logger.debug(f"Resource updated: new revision {new_date_str} > stored {stored_date_str}")
                return True
            else:
                logger.debug(f"Resource unchanged: revision {new_date_str} <= stored {stored_date_str}")
                return False
        except Exception as e:
            logger.warning(f"Error comparing dates: {e}, assuming updated")
            return True
    
    def _compute_content_hash(self, content: str) -> str:
        """
        Compute SHA256 hash of content for change detection.
        
        Args:
            content: Text content to hash
            
        Returns:
            SHA256 hash of the content as a hex string
        """
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def get_content_hash_from_db(self, url: str) -> Optional[str]:
        """
        Get the stored content hash for a resource by URL.
        
        Used for full refresh mode to detect content changes.
        
        Args:
            url: Resource URL to look up
            
        Returns:
            Content hash string if found, None otherwise
        """
        if not self.neo4j_client:
            logger.warning("Neo4j client not available, cannot get content hash")
            return None
        
        try:
            url_hash = self._compute_url_hash(url)
            query = """
            MATCH (r:Resource {url_hash: $url_hash})
            RETURN r.content_hash as content_hash
            LIMIT 1
            """
            result = self.neo4j_client.execute_query(query, {"url_hash": url_hash})
            if result and result[0].get('content_hash'):
                return result[0]['content_hash']
            return None
        except Exception as e:
            logger.error(f"Error getting content hash from Neo4j: {e}")
            return None
    
    def has_content_changed(self, url: str, new_content: str) -> bool:
        """
        Check if content has changed compared to what's stored in the database.
        
        Used for full refresh mode to detect updated documents.
        
        Args:
            url: Resource URL
            new_content: New content to compare
            
        Returns:
            True if content is new or has changed, False if identical
        """
        stored_hash = self.get_content_hash_from_db(url)
        if stored_hash is None:
            # No stored hash means new content
            return True
        
        new_hash = self._compute_content_hash(new_content)
        return new_hash != stored_hash
    
    def filter_new_urls(self, resources: List[Resource]) -> List[Resource]:
        """
        Filter out resources whose URLs already exist in the database.
        
        Args:
            resources: List of Resource objects to filter
            
        Returns:
            List of Resource objects with only new URLs (not in database)
        """
        if not self.neo4j_client:
            logger.warning("Neo4j client not available, skipping URL deduplication")
            return resources
        
        if not resources:
            return resources
        
        # Batch check all URLs at once
        urls = [r.url for r in resources]
        url_exists = self.batch_check_urls_exist(urls)
        
        new_resources = []
        duplicate_count = 0
        
        for resource in resources:
            if not url_exists.get(resource.url, False):
                new_resources.append(resource)
            else:
                duplicate_count += 1
                logger.debug(f"Skipping duplicate URL: {resource.url}")
        
        if duplicate_count > 0:
            logger.info(f"Filtered out {duplicate_count} duplicate URLs, {len(new_resources)} new URLs remain")
        
        return new_resources
    
    def get_event_status_from_db(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Get the status and metadata of an event from Neo4j by its URL.
        
        Args:
            url: Event URL to look up
            
        Returns:
            Dictionary with event status info, or None if event doesn't exist:
            {
                "url_hash": str,
                "status": str,  # 'scheduled', 'cancelled', 'rescheduled', 'completed', 'unconfirmed'
                "start_date": datetime or None
            }
        """
        if not self.neo4j_client:
            logger.warning("Neo4j client not available, cannot check event status")
            return None
        
        try:
            url_hash = self._compute_url_hash(url)
            query = """
            MATCH (e:Event {url_hash: $url_hash})
            RETURN e.url_hash as url_hash, e.status as status, e.start_date as start_date
            LIMIT 1
            """
            result = self.neo4j_client.execute_query(query, {"url_hash": url_hash})
            if result:
                return result[0]
            return None
        except Exception as e:
            logger.error(f"Error checking event status in Neo4j: {e}")
            return None
    
    def batch_get_event_statuses(self, urls: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Get the status and metadata of multiple events from Neo4j in a single query.
        
        Args:
            urls: List of event URLs to look up
            
        Returns:
            Dictionary mapping each URL to its status info, or None if event doesn't exist
        """
        if not urls:
            return {}
        
        if not self.neo4j_client:
            logger.warning("Neo4j client not available, cannot check event statuses")
            return {url: None for url in urls}
        
        try:
            # Compute hashes for all URLs
            url_to_hash = {url: self._compute_url_hash(url) for url in urls}
            hash_to_url = {h: u for u, h in url_to_hash.items()}
            url_hashes = list(url_to_hash.values())
            
            query = """
            UNWIND $url_hashes AS hash
            OPTIONAL MATCH (e:Event {url_hash: hash})
            RETURN hash, e.url_hash as url_hash, e.status as status, e.start_date as start_date
            """
            results = self.neo4j_client.execute_query(query, {"url_hashes": url_hashes})
            
            # Build the result dictionary
            status_map = {}
            for record in results:
                lookup_hash = record.get('hash')
                url = hash_to_url.get(lookup_hash)
                if url:
                    if record.get('url_hash'):
                        # Event exists
                        status_map[url] = {
                            "url_hash": record.get('url_hash'),
                            "status": record.get('status'),
                            "start_date": record.get('start_date')
                        }
                    else:
                        # Event doesn't exist
                        status_map[url] = None
            
            # Ensure all input URLs have a result (default to None if missing)
            return {url: status_map.get(url) for url in urls}
            
        except Exception as e:
            logger.error(f"Error batch checking event statuses in Neo4j: {e}")
            return {url: None for url in urls}
    
    def filter_events(self, events: List[Event]) -> List[Event]:
        """
        Smart event filtering to reduce unnecessary processing.
        
        Logic:
        - Future events are ALWAYS published (digester handles create/update via MERGE)
        - Past events are only skipped if they exist AND are already marked "completed"
        - New past events we've never seen get published with status="completed"
        - Existing past events not yet marked completed get published to update their status
        
        Args:
            events: List of Event objects to filter
            
        Returns:
            List of Event objects that should be published
        """
        if not self.neo4j_client:
            logger.warning("Neo4j client not available, publishing all events")
            return events
        
        if not events:
            return events
        
        now = datetime.now()
        events_to_publish = []
        past_events = []  # Events that need status lookup
        skipped_count = 0
        
        # First pass: categorize events into future (publish immediately) and past (need lookup)
        for event in events:
            # Parse start_date to determine if event is in the past
            try:
                if event.start_date:
                    if isinstance(event.start_date, str):
                        from dateutil.parser import parse as date_parse
                        start_dt = date_parse(event.start_date)
                    else:
                        start_dt = event.start_date
                else:
                    # No start date - treat as future event (publish it)
                    events_to_publish.append(event)
                    continue
            except Exception as e:
                logger.warning(f"Could not parse start_date for event {event.name}: {e}")
                events_to_publish.append(event)
                continue
            
            is_past_event = start_dt < now
            
            if not is_past_event:
                # Future event - always publish
                events_to_publish.append(event)
            else:
                # Past event - need to check status
                past_events.append(event)
        
        # Batch lookup statuses for all past events
        if past_events:
            past_urls = [e.url for e in past_events]
            status_map = self.batch_get_event_statuses(past_urls)
            
            for event in past_events:
                existing = status_map.get(event.url)
                
                if existing is None:
                    # New past event - publish with status=completed
                    event.status = "completed"
                    events_to_publish.append(event)
                    logger.debug(f"New past event: {event.name}")
                elif existing.get("status") != "completed":
                    # Existing past event not yet completed - publish to update
                    events_to_publish.append(event)
                    logger.debug(f"Updating past event: {event.name}")
                else:
                    # Existing past event already completed - skip
                    skipped_count += 1
                    logger.debug(f"Skipping already completed event: {event.name}")
        
        if skipped_count > 0:
            logger.info(f"Filtered out {skipped_count} completed past events, {len(events_to_publish)} events to publish")
        
        return events_to_publish
    
    def should_scrape_datasource(self, datasource_id: str) -> bool:
        """
        Check if a datasource should be scraped based on its configuration.
        
        Args:
            datasource_id: Identifier for the datasource (e.g., 'wfa_resource_page')
            
        Returns:
            True if scraping should proceed, False if it should be skipped
        """
        return self.config_manager.should_scrape(datasource_id)
    
    def mark_datasource_scraped(self, datasource_id: str):
        """
        Update the last_scraped_at timestamp for a datasource after successful scraping.
        
        Args:
            datasource_id: Identifier for the datasource
        """
        self.config_manager.update_last_scraped(datasource_id)
    
    def get_datasource_config(self, datasource_id: str) -> Dict[str, Any]:
        """
        Get the full configuration for a datasource.
        
        Args:
            datasource_id: Identifier for the datasource
            
        Returns:
            Configuration dict with scrape_frequency, check_content_hash, weights, etc.
        """
        return self.config_manager.get_datasource_config(datasource_id)
    
    def get_scraper_delay(self, datasource_id: str) -> float:
        """
        Get the scraper delay (in seconds) for a specific datasource.
        Defaults to 0.5 seconds if not configured in database.
        
        Args:
            datasource_id: Identifier for the datasource
            
        Returns:
            Delay in seconds between requests
        """
        config = self.get_datasource_config(datasource_id)
        return config.get('scraper_delay', 0.5)  # Default: 0.5 seconds
    
    def get_max_resources(self, datasource_id: str) -> int:
        """
        Get the max_resources limit for a specific datasource.
        Defaults to 150 if not configured in database.
        
        Args:
            datasource_id: Identifier for the datasource
            
        Returns:
            Maximum number of resources to scrape (-1 = unlimited)
        """
        config = self.get_datasource_config(datasource_id)
        return config.get('max_resources', -1)  # Default: -1 (unlimited)
    
    def get_max_redirects(self, datasource_id: str) -> int:
        """
        Get the max_redirects limit for a specific datasource.
        Defaults to 10 if not configured in database.
        
        Args:
            datasource_id: Identifier for the datasource
            
        Returns:
            Maximum number of redirects to follow
        """
        config = self.get_datasource_config(datasource_id)
        return config.get('max_redirects', 10)  # Default: 10 redirects

    # =========================================================================
    # PDF Extraction Methods
    # =========================================================================
    
    def extract_pdf_text_from_bytes(self, pdf_bytes: bytes, include_page_markers: bool = True) -> str:
        """
        Extract text content from PDF bytes.
        
        This is the consolidated PDF extraction method used by all scrapers.
        
        Args:
            pdf_bytes: Raw PDF file bytes
            include_page_markers: If True, adds "--- Page N ---" markers between pages
            
        Returns:
            Extracted text content, or error message if extraction fails
        """
        text_parts = []
        
        try:
            pdf_file = io.BytesIO(pdf_bytes)
            pdf_reader = pypdf.PdfReader(pdf_file)
            
            for i, page in enumerate(pdf_reader.pages):
                try:
                    text = page.extract_text()
                    if text and text.strip():
                        if include_page_markers:
                            text_parts.append(f"--- Page {i+1} ---\n{text}")
                        else:
                            text_parts.append(text)
                except Exception as e:
                    logger.warning(f"Could not extract text from page {i+1}: {e}")
            
            separator = '\n\n' if include_page_markers else '\n'
            return separator.join(text_parts) or "[PDF content could not be extracted - may be scanned images]"
            
        except Exception as e:
            logger.error(f"Error extracting PDF text: {e}")
            return "[PDF text extraction failed]"
    
    async def fetch_and_extract_pdf(self, pdf_url: str, include_page_markers: bool = False) -> str:
        """
        Fetch a PDF from URL and extract its text content.
        
        Convenience method that combines HTTP fetch with PDF extraction.
        
        Args:
            pdf_url: URL of the PDF to fetch
            include_page_markers: If True, adds "--- Page N ---" markers between pages
            
        Returns:
            Extracted text content, or error message if fetch/extraction fails
        """
        try:
            async with self.session.get(pdf_url) as response:
                if response.status == 200:
                    pdf_bytes = await response.read()
                    return self.extract_pdf_text_from_bytes(pdf_bytes, include_page_markers)
                else:
                    return f"Failed to fetch PDF: HTTP {response.status}"
                    
        except Exception as e:
            logger.error(f"Error fetching PDF from {pdf_url}: {e}")
            return f"Error fetching PDF: {str(e)}"

    
    def publish_resource(self, resource: Resource, additional_fields: Optional[Dict[str, Any]] = None):
        """
        Publish a resource to RabbitMQ, or collect it if collect_mode is enabled.
        
        Args:
            resource: The Resource object to publish
            additional_fields: Optional dict of additional fields to include in the message
        """
        # Set batch_id if a batch is active
        if self._current_batch_id and not resource.batch_id:
            resource.batch_id = self._current_batch_id
        
        # Get base message from resource
        message = resource.to_message()

        if self._should_skip_by_lookback(
            item_type="resource",
            datasource_id=resource.datasource_id or self._current_datasource_id,
            reference_value=resource.publish_date or resource.scraped_at,
            title=resource.title,
            url=resource.url,
            allow_initial_backfill=True,
        ):
            return

        if self._is_initial_scrape(resource.datasource_id or self._current_datasource_id):
            message["allow_historical_ingest"] = True
        
        # Add any additional fields provided by the specific scraper
        if additional_fields:
            message.update(additional_fields)
        
        # Collect mode: store message instead of publishing
        if self._collect_mode:
            self._collected_messages.append(message)
            logger.debug(f"Collected resource: {resource.title}")
        else:
            try:
                # Log publication at INFO level
                logger.info(f"Publishing resource: {resource.title}")
                # Log details at DEBUG level
                log_message = message.copy()
                if 'resource_data' in log_message and log_message['resource_data'].get('content'):
                    content = log_message['resource_data']['content']
                    log_message['resource_data'] = log_message['resource_data'].copy()
                    log_message['resource_data']['content'] = content[:50] + "..." if len(content) > 50 else content
                logger.debug(f"Resource message: {json.dumps(log_message, default=str)}")
                self.rabbitmq_producer.publish(message)
            except Exception as e:
                logger.error(f"Error publishing to RabbitMQ queue '{settings.rabbitmq_queue}': {e}")
                raise
        
        # Track item count for batch
        self.increment_batch_count(1)
    
    def publish_event(self, event: Event):
        """
        Publish an event to RabbitMQ, or collect it if collect_mode is enabled.
        
        Args:
            event: The Event object to publish
        """
        # Set batch_id if a batch is active
        if self._current_batch_id and not event.batch_id:
            event.batch_id = self._current_batch_id
        
        message = event.to_message()

        if self._should_skip_by_lookback(
            item_type="event",
            datasource_id=event.datasource_id or self._current_datasource_id,
            reference_value=event.start_date or event.scraped_at,
            title=event.name,
            url=event.url or "",
            allow_initial_backfill=False,
        ):
            return
        
        # Collect mode: store message instead of publishing
        if self._collect_mode:
            self._collected_messages.append(message)
            logger.debug(f"Collected event: {event.name}")
        else:
            try:
                # Log with truncated description for readability
                log_message = message.copy()
                if 'event_data' in log_message and log_message['event_data'].get('description'):
                    desc = log_message['event_data']['description']
                    log_message['event_data'] = log_message['event_data'].copy()
                    log_message['event_data']['description'] = desc[:50] + "..." if len(desc) > 50 else desc
                logger.debug(f"Publishing event to RabbitMQ: {json.dumps(log_message, default=str)}")
                self.rabbitmq_producer.publish(message)
            except Exception as e:
                logger.error(f"Error publishing event to RabbitMQ: {e}")
                raise
        
        # Track item count for batch
        self.increment_batch_count(1)
    
    @abc.abstractmethod
    async def run_scraper(self):
        """Abstract method that each scraper must implement for scraping execution"""
        pass
    
    @abc.abstractmethod
    async def scrape_resource(self, resource: Resource) -> Resource:
        """Abstract method that each scraper must implement to scrape individual resources"""
        pass
