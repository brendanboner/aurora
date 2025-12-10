"""
Topic Threshold Monitor

Monitors the count of new topics created since the last curation run.
Triggers topic organization when the threshold is reached.
"""

from datetime import datetime
from typing import Optional, Tuple

import redis

from settings import settings
from utils.logger import setup_logger
from neo4j_client import Neo4jClient

logger = setup_logger(__name__)

# Redis keys
REDIS_KEY_LAST_CURATION = "curator:topic:last_curation_timestamp"
REDIS_KEY_CURATION_RUNNING = "curator:topic:running"
REDIS_KEY_RETRIEVER_HEARTBEAT = "retriever:heartbeat"  # Set by retriever scrapers
REDIS_KEY_RETRIEVER_IDLE_SINCE = "curator:retriever_idle_since"  # Tracks when retriever went idle

# Grace period (seconds) after retriever goes idle before triggering cleanup
# This prevents triggering cleanup during brief gaps between scraper tasks
RETRIEVER_IDLE_GRACE_PERIOD_SECONDS = 60


class TopicThresholdMonitor:
    """
    Monitors new topic creation and determines when threshold is met.
    
    Uses Redis to track:
    - Last curation timestamp (ISO format)
    - Whether curation is currently running (lock)
    
    Uses Neo4j to count topics created since last curation.
    """
    
    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        neo4j_client: Optional[Neo4jClient] = None,
    ):
        """
        Initialize the threshold monitor.
        
        Args:
            redis_client: Redis client instance (created if not provided)
            neo4j_client: Neo4j client instance (created if not provided)
        """
        # Initialize Redis
        if redis_client:
            self.redis = redis_client
        else:
            self.redis = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                decode_responses=True,
                socket_connect_timeout=5,
            )
        
        # Initialize Neo4j (lazy - only when needed)
        self._neo4j_client = neo4j_client
        self._owns_neo4j = neo4j_client is None
    
    @property
    def neo4j(self) -> Neo4jClient:
        """Lazy initialization of Neo4j client."""
        if self._neo4j_client is None:
            self._neo4j_client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database=settings.neo4j_database,
            )
            self._neo4j_client.connect()
        return self._neo4j_client
    
    def get_last_curation_timestamp(self) -> Optional[datetime]:
        """
        Get the timestamp of the last successful curation.
        
        Returns:
            datetime if set, None if never curated
        """
        try:
            timestamp_str = self.redis.get(REDIS_KEY_LAST_CURATION)
            if timestamp_str:
                return datetime.fromisoformat(timestamp_str)
            return None
        except Exception as e:
            logger.error(f"Error getting last curation timestamp: {e}")
            return None
    
    def set_last_curation_timestamp(self, timestamp: Optional[datetime] = None):
        """
        Set the last curation timestamp.
        
        Args:
            timestamp: Timestamp to set (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        try:
            self.redis.set(REDIS_KEY_LAST_CURATION, timestamp.isoformat())
            logger.info(f"Updated last curation timestamp: {timestamp.isoformat()}")
        except Exception as e:
            logger.error(f"Error setting last curation timestamp: {e}")
    
    def count_topics_since(self, since: Optional[datetime] = None) -> int:
        """
        Count topics created since a given timestamp.
        
        Only counts topics created by the digester, excluding topics created
        by the curator itself to prevent self-triggering loops.
        
        Args:
            since: Count topics created after this time. If None, counts all topics.
            
        Returns:
            Number of digester-created topics since the timestamp
        """
        try:
            if since is None:
                # Count all digester topics
                # Use IS NOT NULL check to avoid Neo4j warning when property doesn't exist yet
                query = """
                MATCH (t:Topic)
                WHERE t.created_by IS NOT NULL AND t.created_by = 'digester'
                RETURN count(t) as count
                """
                result = self.neo4j.execute_query(query)
            else:
                # Count digester topics created after timestamp
                # Use IS NOT NULL check to avoid Neo4j warning when property doesn't exist yet
                query = """
                MATCH (t:Topic)
                WHERE t.created_at > datetime($since)
                  AND t.created_by IS NOT NULL AND t.created_by = 'digester'
                RETURN count(t) as count
                """
                result = self.neo4j.execute_query(
                    query,
                    {"since": since.isoformat()}
                )
            
            if result and len(result) > 0:
                return result[0]["count"]
            return 0
            
        except Exception as e:
            logger.error(f"Error counting topics: {e}")
            return 0
    
    def is_curation_running(self) -> bool:
        """Check if curation is currently running."""
        try:
            return self.redis.get(REDIS_KEY_CURATION_RUNNING) == "true"
        except Exception as e:
            logger.error(f"Error checking curation status: {e}")
            return False
    
    def set_curation_running(self, running: bool):
        """Set the curation running status."""
        try:
            if running:
                # Set with expiry (safety net if process crashes)
                # Short TTL since we extend via heartbeat during cluster processing
                self.redis.setex(REDIS_KEY_CURATION_RUNNING, 1800, "true")  # 30 min expiry
            else:
                self.redis.delete(REDIS_KEY_CURATION_RUNNING)
        except Exception as e:
            logger.error(f"Error setting curation status: {e}")
    
    def extend_curation_lock(self, ttl_seconds: int = 1800):
        """
        Extend the curation lock expiry (heartbeat).
        
        Call this periodically during long-running curation to prevent
        the lock from expiring while still processing.
        
        Args:
            ttl_seconds: New TTL to set (default 30 minutes)
        """
        try:
            if self.redis.exists(REDIS_KEY_CURATION_RUNNING):
                self.redis.expire(REDIS_KEY_CURATION_RUNNING, ttl_seconds)
                logger.debug(f"Extended curation lock TTL to {ttl_seconds}s")
        except Exception as e:
            logger.error(f"Error extending curation lock: {e}")
    
    def is_retriever_active(self) -> bool:
        """
        Check if the retriever is actively scraping.
        
        The retriever sets a heartbeat key with a 5-minute TTL during scraping.
        If the key exists, the retriever is active.
        
        Returns:
            True if retriever heartbeat exists (actively scraping)
        """
        try:
            return self.redis.exists(REDIS_KEY_RETRIEVER_HEARTBEAT) > 0
        except Exception as e:
            logger.error(f"Error checking retriever heartbeat: {e}")
            return False
    
    def is_retriever_idle_past_grace_period(self) -> bool:
        """
        Check if retriever has been idle long enough to trigger cleanup.
        
        This implements a grace period to avoid triggering cleanup during
        brief gaps between scraper tasks (e.g., between datasources).
        
        Logic:
        1. If retriever is active (heartbeat exists), clear idle tracking, return False
        2. If retriever just went idle, record the timestamp, return False
        3. If retriever has been idle for > grace period, return True
        
        Returns:
            True if retriever has been idle for longer than the grace period
        """
        try:
            if self.is_retriever_active():
                # Retriever is active - clear any idle tracking
                self.redis.delete(REDIS_KEY_RETRIEVER_IDLE_SINCE)
                return False
            
            # Retriever is not active - check/set idle timestamp
            idle_since_str = self.redis.get(REDIS_KEY_RETRIEVER_IDLE_SINCE)
            
            if idle_since_str is None:
                # Just went idle - record timestamp
                self.redis.set(REDIS_KEY_RETRIEVER_IDLE_SINCE, datetime.now().isoformat())
                logger.debug("Retriever went idle, starting grace period")
                return False
            
            # Check if grace period has passed
            idle_since = datetime.fromisoformat(idle_since_str)
            idle_duration = datetime.now() - idle_since
            
            if idle_duration.total_seconds() >= RETRIEVER_IDLE_GRACE_PERIOD_SECONDS:
                logger.debug(
                    f"Retriever idle for {idle_duration.total_seconds():.0f}s "
                    f"(grace period: {RETRIEVER_IDLE_GRACE_PERIOD_SECONDS}s)"
                )
                return True
            
            logger.debug(
                f"Retriever idle for {idle_duration.total_seconds():.0f}s, "
                f"waiting for grace period ({RETRIEVER_IDLE_GRACE_PERIOD_SECONDS}s)"
            )
            return False
            
        except Exception as e:
            logger.error(f"Error checking retriever idle status: {e}")
            return False
    
    def clear_retriever_idle_tracking(self):
        """Clear the retriever idle timestamp after cleanup triggers."""
        try:
            self.redis.delete(REDIS_KEY_RETRIEVER_IDLE_SINCE)
        except Exception as e:
            logger.error(f"Error clearing retriever idle tracking: {e}")

    def all_batches_completed(self) -> bool:
        """
        Check if all active ingestion batches have completed.
        
        This is used in conjunction with retriever idle detection to
        verify that all digestion has finished before triggering cleanup.
        
        Returns:
            True if no batches are in 'scraping' or 'digesting' status
        """
        try:
            query = """
            MATCH (b:IngestionBatch)
            WHERE b.status IN ['retrieving', 'digesting']
            RETURN count(b) as active_count
            """
            
            result = self.neo4j.execute_query(query)
            if result and len(result) > 0:
                active_count = result[0].get("active_count", 0)
                if active_count > 0:
                    logger.debug(f"{active_count} batches still in progress")
                return active_count == 0
            return True
            
        except Exception as e:
            logger.error(f"Error checking batch completion status: {e}")
            return False

    def should_trigger_curation(self) -> Tuple[bool, int, str]:
        """
        Check if topic organization should be triggered.
        
        Triggers when:
        1. Topic count threshold is reached (e.g., 50 new topics) - always triggers
        2. Retriever is idle (past grace period), all batches complete, and pending topics exist
        
        Returns:
            Tuple of (should_trigger, new_topic_count, trigger_reason)
        """
        # Don't trigger if curation is already running
        if self.is_curation_running():
            logger.debug("Curation already running, skipping threshold check")
            return False, 0, ""
        
        # Get last curation time
        last_curation = self.get_last_curation_timestamp()
        
        # Count new topics
        new_count = self.count_topics_since(last_curation)
        
        # Check threshold
        threshold = settings.topic_threshold_count
        
        # Reason 1: Threshold reached - always triggers regardless of retriever status
        if new_count >= threshold:
            logger.info(
                f"Topic threshold reached: {new_count} new topics "
                f"(threshold: {threshold})"
            )
            # Clear idle tracking since we're triggering
            self.clear_retriever_idle_tracking()
            return True, new_count, f"threshold ({new_count} >= {threshold})"
        
        # Reason 2: Retriever idle cleanup
        # Only trigger if: retriever idle past grace period + all batches done + pending topics
        if new_count > 0:
            if self.is_retriever_active():
                logger.debug(
                    f"Retriever active, waiting for threshold: {new_count}/{threshold}"
                )
            elif self.is_retriever_idle_past_grace_period():
                if self.all_batches_completed():
                    logger.info(
                        f"Retriever idle with {new_count} pending topics - "
                        f"triggering cleanup organization"
                    )
                    # Clear idle tracking since we're triggering
                    self.clear_retriever_idle_tracking()
                    return True, new_count, f"cleanup ({new_count} pending, retriever idle)"
                else:
                    logger.debug(
                        "Retriever idle but batches still processing"
                    )
        
        logger.debug(
            f"Topic threshold not reached: {new_count}/{threshold} new topics"
        )
        return False, new_count, ""
    
    def close(self):
        """Clean up resources."""
        if self._owns_neo4j and self._neo4j_client:
            self._neo4j_client.close()
            self._neo4j_client = None
