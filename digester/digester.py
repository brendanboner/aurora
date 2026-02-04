"""
Document Digester Service

This service consumes messages from RabbitMQ, extracts metadata using LLM,
validates and normalizes the data, and inserts it into a Neo4j knowledge graph.
"""

import sys
from typing import Dict, Any
import re
import hashlib
from datetime import datetime
from dateutil.parser import parse as date_parse
import threading
import time
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer

from settings import settings
from utils.logger import setup_logger
from utils.document_parser import DocumentParser
from rabbitmq_client import AsyncRabbitMQConsumer, RabbitMQProducer
from services.metadata_extractor import MetadataExtractor
from services.event_associator import EventAssociator
from utils.model_builder import build_models, build_event_model, BuiltModelsDict
from neo4j_client import Neo4jClient, GraphRepository, NodeDeduplicator

from neo4j_client.models import Person, ResourceUploadedByPerson, ResourceRelatesToEvent
import redis.asyncio as redis
import json

# Import OpenTelemetry instrumentation
from common.telemetry import init_telemetry

logger = setup_logger(__name__, settings.log_level)

# Initialize OpenTelemetry
tracer, meter = init_telemetry(
    service_name="aurora-digester",
    service_version="1.0.0"
)



# Redis TTL constants (in seconds)
REDIS_HEARTBEAT_TTL = 300  # 5 minutes
REDIS_CURRENT_PROCESSING_TTL = 300  # 5 minutes
REDIS_DELIVERY_ATTEMPT_TTL = 7200  # 2 hours (increased from 1 hour to handle slow processing + reconnects)

# Redis list size limits
REDIS_MAX_COMPLETED_ITEMS = 20
REDIS_MAX_FAILED_ITEMS = 20

# Hash truncation length for Redis keys
# Increased from 16 to 32 to reduce collision probability
# 32 hex chars = 128 bits = 2^128 possible values (collision extremely unlikely)
REDIS_HASH_KEY_LENGTH = 32

# Heartbeat update interval (in seconds)
# Only update heartbeat if this many seconds have passed since last update
# This reduces Redis I/O while still maintaining reasonable monitoring granularity
HEARTBEAT_UPDATE_INTERVAL = 30  # 30 seconds


class DocumentDigester:
    """Main orchestrator for the document digestion pipeline."""
    
    def __init__(self):
        logger.info("Initializing Document Digester (ASYNC MODE)...")
        
        # Metrics tracking
        self.total_messages_processed = 0
        self.total_dlq_timeout = 0  # Messages that exceeded processing timeout
        self.total_dlq_redelivery = 0  # Messages that hit redelivery limit
        self.total_dlq_validation = 0  # Messages with validation errors
        self.total_dlq_error = 0  # Messages with unexpected errors
        
        # Initialize components
        self.rabbitmq_consumer = AsyncRabbitMQConsumer(
            host=settings.rabbitmq_host,
            port=settings.rabbitmq_port,
            user=settings.rabbitmq_user,
            password=settings.rabbitmq_password,
            queue=settings.rabbitmq_queue,
            dlq_queue=f"{settings.rabbitmq_queue}-dlq",
            logger_instance=logger,
            max_concurrent=settings.rabbitmq_max_concurrent,
            message_timeout=settings.rabbitmq_message_timeout,
            heartbeat=settings.rabbitmq_heartbeat,
            prefetch_count=settings.rabbitmq_prefetch_count
        )
        
        # Store connection parameters for lazy producer connections
        # Producers are created on-demand to avoid stale idle connections
        self._rabbitmq_config = {
            "host": settings.rabbitmq_host,
            "port": settings.rabbitmq_port,
            "user": settings.rabbitmq_user,
            "password": settings.rabbitmq_password,
        }
        self._dlq_queue = f"{settings.rabbitmq_queue}-dlq"
        self._retry_queue = settings.rabbitmq_queue
        
        self.metadata_extractor = MetadataExtractor()
        
        # Initialize Neo4j client with settings and logger
        self.neo4j_client = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
            logger_instance=logger
        )
        self.graph_repository = None
        self.deduplicator = None
        
        # Initialize async Redis client for monitoring and content caching
        # Connection is lazy - will be established on first use
        self.redis_client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            decode_responses=True,
            socket_connect_timeout=5
        )
        logger.info("Async Redis client initialized (connection will be established on first use)")
        
        # Track last heartbeat update time to avoid excessive Redis I/O
        self._last_heartbeat_time = 0.0
        
        # Initialize document parser for binary files
        self.doc_parser = DocumentParser()
        
        logger.info("Document Digester initialized")
    
    def _handle_video_metadata(self, resource_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and format video-specific metadata."""
        metadata = resource_data.get('metadata', {})
        
        # Debug: Log event metadata presence
        if metadata.get('event_name'):
            logger.info(f"📅 Found event metadata: {metadata.get('event_name')} ({metadata.get('event_year')}) - confidence: {metadata.get('event_confidence')}")
        else:
            logger.debug(f"No event metadata in video metadata keys: {list(metadata.keys())}")
        
        # Add video-specific context to extraction
        video_context = []
        
        if metadata.get('channel_name'):
            video_context.append(f"Channel: {metadata['channel_name']}")
        
        if metadata.get('duration_seconds'):
            duration_min = metadata['duration_seconds'] // 60
            video_context.append(f"Duration: {duration_min} minutes")
        
        if metadata.get('is_segment'):
            video_context.append(
                f"Segment {metadata['segment_number']}/{metadata['total_segments']}"
            )
        
        # Add event context if available
        if metadata.get('event_name'):
            event_desc = f"Event: {metadata['event_name']}"
            if metadata.get('event_year'):
                event_desc += f" {metadata['event_year']}"
            video_context.append(event_desc)
        
        # Add context to title for better extraction
        enhanced_title = resource_data['title']
        if video_context:
            enhanced_title += f" ({', '.join(video_context)})"
        
        return {
            **resource_data,
            'title': enhanced_title,
            'video_metadata': metadata
        }
    
    async def _ensure_redis_connection(self):
        """Ensure Redis connection is established (test with ping)."""
        if self.redis_client:
            try:
                await self.redis_client.ping()
                return True
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}. Monitoring will be disabled.")
                return False
        return False
    
    def initialize_graph(self):
        """
        Initialize Neo4j connection and create repository objects.
        
        Note: Schema creation and base data initialization are now handled
        by the neo4j-init container, which runs before this service starts.
        This method only establishes the connection and creates the repository.
        """
        logger.info("Initializing Neo4j graph repository...")
        
        # Connect to Neo4j
        self.neo4j_client.connect()
        
        # Create repository with logger
        self.graph_repository = GraphRepository(self.neo4j_client, logger_instance=logger)
        
        # Create deduplicator with logger
        self.deduplicator = NodeDeduplicator(self.neo4j_client, logger_instance=logger)
        
        # Create event associator for document-to-event linking
        self.event_associator = EventAssociator(self.graph_repository)
        
        logger.info("Neo4j connection established successfully")
    
    def send_to_dlq(self, message: Dict[str, Any], error: str) -> bool:
        """
        Send a message to the Dead Letter Queue.
        
        Uses a fresh connection each time to avoid stale idle connections.
        Also updates batch progress so the batch can still complete even if
        some messages fail permanently.
        
        Args:
            message: The original message that failed
            error: Error message describing why it failed
            
        Returns:
            True if sent successfully, False otherwise
        """
        try:
            title = self._get_message_title(message)
            
            # Add error metadata
            dlq_message = {
                **message,
                "dlq_error": error,
                "dlq_timestamp": datetime.now().isoformat()
            }
            
            # Use fresh connection to avoid stale idle connection issues
            logger.debug(f"Opening RabbitMQ producer connection to DLQ: {self._dlq_queue}")
            with RabbitMQProducer(
                **self._rabbitmq_config,
                queue=self._dlq_queue,
                logger_instance=logger
            ) as producer:
                producer._ensure_connected()
                producer.publish(dlq_message)
                logger.debug("Closed RabbitMQ producer connection to DLQ")
            
            logger.info(f"Sent document to DLQ: {title} - Reason: {error}")
            
            # Update batch progress even for DLQ items so batch can complete
            batch_id = message.get("batch_id")
            if batch_id:
                message_type = message.get("message_type")
                item_type = "event" if message_type == "event" else "resource"
                self._update_batch_progress(batch_id, item_type=item_type)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to send message to DLQ: {e}", exc_info=True)
            return False
    
    
    async def update_heartbeat(self):
        """
        Update digester heartbeat timestamp in Redis (ASYNC).
        
        Uses time-based caching to avoid excessive Redis I/O - only updates
        if HEARTBEAT_UPDATE_INTERVAL seconds have passed since last update.
        """
        if not self.redis_client:
            return
        
        current_time = time.time()
        time_since_last = current_time - self._last_heartbeat_time
        
        # Only update if enough time has passed since last update
        if time_since_last >= HEARTBEAT_UPDATE_INTERVAL:
            await self._set_redis_value(
                "digester:heartbeat",
                str(current_time),
                REDIS_HEARTBEAT_TTL,
                "update heartbeat"
            )
            self._last_heartbeat_time = current_time
    
    async def update_current_processing(self, message: Dict[str, Any], stage: str):
        """Update current processing status in Redis (ASYNC)."""
        resource_data = message.get("resource_data", {})
        event_data = message.get("event_data", {})
        processing_data = {
            "title": resource_data.get("title") or event_data.get("name") or "Unknown",
            "url": resource_data.get("url") or event_data.get("url") or "",
            "category": resource_data.get("category") or ("event" if event_data else "unknown"),
            "status": "processing",
            "stage": stage,
            "started_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        await self._set_redis_value(
            "digester:current",
            json.dumps(processing_data),
            REDIS_CURRENT_PROCESSING_TTL,
            "update current processing"
        )
    
    async def clear_current_processing(self):
        """Clear current processing status in Redis (ASYNC)."""
        if self.redis_client:
            try:
                await self.redis_client.delete("digester:current")
            except Exception as e:
                logger.warning(f"Failed to clear current processing: {e}")
    
    def _update_batch_progress(self, batch_id: str, item_type: str = "resource"):
        """
        Update batch progress after successfully processing an item.
        
        Increments items_digested and marks batch as completed if all items are digested.
        
        Args:
            batch_id: The ID of the batch being processed
            item_type: Type of item processed - "event" or "resource"
        """
        if not self.graph_repository:
            logger.warning("Graph repository not initialized, skipping batch progress update")
            return
            
        try:
            # Increment digested count and get updated counts
            events_delta = 1 if item_type == "event" else 0
            resources_delta = 1 if item_type == "resource" else 0
                        
            counts = self.graph_repository.increment_batch_digested(
                batch_id,
                events_delta=events_delta,
                resources_delta=resources_delta
            )
                        
            if counts:
                items_digested = counts.get("items_digested", 0)
                items_scraped = counts.get("items_scraped", 0)
                current_status = counts.get("status", "unknown")
                
                logger.debug(f"Batch {batch_id}: {items_digested}/{items_scraped} items digested (status: {current_status})")
                
                # Only mark complete if:
                # 1. All items are digested
                # 2. Batch is currently in 'digesting' status (not already completed)
                # This prevents race conditions where batch is marked complete prematurely
                if (items_scraped > 0 
                    and items_digested >= items_scraped 
                    and current_status == "digesting"):
                    self.graph_repository.update_batch_status(batch_id, "completed")
                    logger.info(f"Batch {batch_id} completed: {items_digested}/{items_scraped} items digested")
            else:
                logger.warning(f"Batch {batch_id} not found when updating progress")
                
        except Exception as e:
            logger.warning(f"Failed to update batch progress for {batch_id}: {e}")
    
    async def record_completed(self, message: Dict[str, Any], metadata: Dict[str, Any] = None):
        """Record successfully completed document in Redis (ASYNC)."""
        resource_data = message.get("resource_data", {})
        event_data = message.get("event_data", {})
        
        completed_data = {
            "title": self._get_message_title(message),
            "url": resource_data.get("url") or event_data.get("url") or "",
            "category": resource_data.get("category") or ("event" if event_data else "unknown"),
            "status": "completed",
            "stage": "inserted",
            "started_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "datasource_id": message.get("datasource_id", ""),
            "publish_date": resource_data.get("publish_date", ""),
            "uploaded_by": message.get("uploaded_by", "")
        }
        
        # Add metadata if provided
        if metadata:
            completed_data["metadata"] = metadata
        
        await self._record_to_redis_list(
            "processing:completed",
            completed_data,
            REDIS_MAX_COMPLETED_ITEMS,
            "completed"
        )
    
    async def record_failed(self, message: Dict[str, Any], error: str):
        """Record failed document in Redis (ASYNC)."""
        resource_data = message.get("resource_data", {})
        event_data = message.get("event_data", {})
        
        failed_data = {
            "title": self._get_message_title(message),
            "url": resource_data.get("url") or event_data.get("url") or "",
            "category": resource_data.get("category") or ("event" if event_data else "unknown"),
            "status": "failed",
            "stage": "error",
            "started_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "error": error
        }
        await self._record_to_redis_list(
            "processing:failed",
            failed_data,
            REDIS_MAX_FAILED_ITEMS,
            "failed"
        )
    
    def validate_resource_message(self, message: Dict[str, Any]) -> None:
        """
        Validate the presence and correctness of required fields in a resource message.

        Args:
            message: The resource message to validate.

        Raises:
            ValueError: If any required field is missing or invalid.
        """
        resource_data = message.get("resource_data", {})
        
        # Ensure keys are present in resource_data
        required_fields = ["title", "url", "category", "content", "publish_date"]
        missing_fields = [field for field in required_fields if field not in resource_data]
        if missing_fields:
            raise ValueError(f"Missing required fields in resource_data: {', '.join(missing_fields)}")
        
        # Ensure top-level fields are present
        required_top_fields = ["datasource_id", "scraped_at"]
        missing_top = [field for field in required_top_fields if field not in message]
        if missing_top:
            raise ValueError(f"Missing required fields: {', '.join(missing_top)}")

        # Only publish_date can be null; if present, must be a non-empty string and valid date/datetime
        if resource_data["publish_date"] is not None:
            if not isinstance(resource_data["publish_date"], str) or not resource_data["publish_date"].strip():
                logger.warning("publish_date is not a valid string, setting to null.")
                resource_data["publish_date"] = None
            else:
                try:
                    date_parse(resource_data["publish_date"])
                except Exception:
                    logger.warning("publish_date could not be parsed, setting to null.")
                    resource_data["publish_date"] = None

        # scraped_at must be a valid Unix timestamp or ISO string
        scraped_at = message["scraped_at"]
        if isinstance(scraped_at, str):
            # ISO format string - try to parse it
            try:
                date_parse(scraped_at)
            except Exception:
                raise ValueError("Field 'scraped_at' must be a valid ISO timestamp string or Unix timestamp.")
        elif not (isinstance(scraped_at, (int, float)) and scraped_at > 0):
            raise ValueError("Field 'scraped_at' must be a valid Unix timestamp (positive integer or float) or ISO string.")

        # url must be a valid URL string (http, https, file, or s3 protocols)
        # Note: S3 URLs may contain spaces in filenames
        url_pattern = re.compile(r'^(https?|file|s3)://.+$')
        if not isinstance(resource_data["url"], str) or not url_pattern.match(resource_data["url"]):
            raise ValueError("Field 'url' must be a valid URL string (http, https, file, or s3 protocol).")

        # uploaded_by is optional; if present, must be a non-empty string
        if "uploaded_by" in message:
            if not isinstance(message["uploaded_by"], str) or not message["uploaded_by"].strip():
                raise ValueError("Field 'uploaded_by' must be a non-empty string if provided.")

        # All other fields must be valid non-empty strings (except content for file:// URLs)
        for field in ["title", "category"]:
            if not isinstance(resource_data[field], str) or not resource_data[field].strip():
                raise ValueError(f"Field '{field}' must be a non-empty string.")
        
        if not isinstance(message["datasource_id"], str) or not message["datasource_id"].strip():
            raise ValueError("Field 'datasource_id' must be a non-empty string.")
        
        # Content can be empty for local file uploads (binary files), but must be a string
        if not isinstance(resource_data["content"], str):
            raise ValueError("Field 'content' must be a string.")

    def validate_event_message(self, message: Dict[str, Any]) -> None:
        """
        Validate the presence and correctness of required fields in an event message.

        Args:
            message: The event message to validate.

        Raises:
            ValueError: If any required field is missing or invalid.
        """
        event_data = message.get("event_data", {})
        
        if not event_data:
            raise ValueError("Missing 'event_data' in event message.")
        
        # Ensure required event fields are present
        required_fields = ["name", "event_type", "start_date"]
        missing_fields = [field for field in required_fields if not event_data.get(field)]
        if missing_fields:
            raise ValueError(f"Missing required fields in event_data: {', '.join(missing_fields)}")
        
        # Ensure top-level fields are present
        required_top_fields = ["datasource_id", "scraped_at"]
        missing_top = [field for field in required_top_fields if field not in message]
        if missing_top:
            raise ValueError(f"Missing required fields: {', '.join(missing_top)}")
        
        # Validate start_date is parseable
        try:
            date_parse(event_data["start_date"])
        except Exception:
            raise ValueError("Field 'start_date' must be a valid date/datetime string.")
        
        # Validate end_date if present
        if event_data.get("end_date"):
            try:
                date_parse(event_data["end_date"])
            except Exception:
                logger.warning("end_date could not be parsed, setting to null.")
                event_data["end_date"] = None
    
    def _get_message_id(self, message: Dict[str, Any]) -> str:
        """Extract a unique identifier from a message for tracking purposes."""
        resource_data = message.get("resource_data", {})
        event_data = message.get("event_data", {})
        # For events, use URL (unique) not name (can be duplicate for recurring events)
        # For resources, use URL
        return resource_data.get("url") or event_data.get("url") or event_data.get("name") or message.get("id", "unknown")
    
    def _get_message_title(self, message: Dict[str, Any]) -> str:
        """Extract a display title from a message for logging purposes."""
        resource_data = message.get("resource_data", {})
        event_data = message.get("event_data", {})
        return resource_data.get("title") or event_data.get("name") or "Unknown"
    
    async def _record_to_redis_list(self, list_key: str, data: Dict[str, Any], max_items: int, operation_name: str):
        """
        Record data to a Redis list with automatic trimming to max size (ASYNC).
        
        Args:
            list_key: Redis list key
            data: Data dict to serialize and store
            max_items: Maximum number of items to keep in the list
            operation_name: Name of operation for logging (e.g., "completed", "failed")
        """
        if self.redis_client:
            try:
                await self.redis_client.lpush(list_key, json.dumps(data))
                await self.redis_client.ltrim(list_key, 0, max_items - 1)
            except Exception as e:
                logger.warning(f"Failed to record {operation_name}: {e}")

    async def _set_redis_value(self, key: str, value: str, ttl: int, operation_name: str):
        """
        Set a Redis key with TTL (ASYNC).
        
        Args:
            key: Redis key
            value: Value to store
            ttl: Time-to-live in seconds
            operation_name: Name of operation for logging
        """
        if self.redis_client:
            try:
                await self.redis_client.setex(key, ttl, value)
            except Exception as e:
                logger.warning(f"Failed to {operation_name}: {e}")

    
    def _get_delivery_attempt_key(self, message: Dict[str, Any]) -> str:
        """Get Redis key for tracking delivery attempts."""
        msg_id = self._get_message_id(message)
        # Use stable hash instead of Python's hash() which varies across runs
        stable_hash = hashlib.sha256(msg_id.encode()).hexdigest()[:REDIS_HASH_KEY_LENGTH]
        return f"delivery_attempts:{stable_hash}"
    
    async def _clear_delivery_attempts(self, message: Dict[str, Any]):
        """Clear delivery attempt counter after successful processing (ASYNC)."""
        if self.redis_client:
            try:
                await self.redis_client.delete(self._get_delivery_attempt_key(message))
            except Exception as e:
                logger.debug(f"Failed to clear delivery attempts: {e}")
    
    async def _check_delivery_attempts(self, message: Dict[str, Any]) -> str:
        """
        Track delivery attempts in Redis to prevent infinite redelivery loops (ASYNC).
        
        This should be called at the START of process_message() to check if this
        message has been redelivered too many times by RabbitMQ.
        
        Key insight: When connection closes during processing, RabbitMQ automatically
        requeues the unacknowledged message. On the next delivery, this counter
        will increment. If processing is slow and TTL expires, the counter resets,
        potentially causing infinite loops.
        
        To prevent this:
        1. Increased hash key length (16→32 chars) to avoid collisions
        2. Increased TTL (1→2 hours) to handle slow processing + reconnects
        3. Increased heartbeat (360→1800s) to allow up to 60 min processing
        
        If over the limit, send to DLQ and indicate to ACK (remove from queue) 
        only if DLQ delivery succeeded.
        
        Returns:
            process if message should be processed,
            dequeue if message was sent to DLQ and should be ACKed,
            requeue if DLQ delivery failed and message should be requeued
        """
        if not self.redis_client:
            return "process"
        
        attempt_key = self._get_delivery_attempt_key(message)
        
        try:
            attempts = await self.redis_client.incr(attempt_key)
            await self.redis_client.expire(attempt_key, REDIS_DELIVERY_ATTEMPT_TTL)
        except Exception as e:
            logger.warning(f"Failed to track delivery attempts in Redis: {e}. Allowing requeue.")
            return "process"  # If Redis fails, allow requeue (fail open)
        
        if attempts > settings.max_message_retries:
            title = self._get_message_title(message)
            error_msg = f"REDELIVERY LOOP: Max delivery attempts ({attempts}) exceeded - RabbitMQ redelivered too many times"
            logger.error(
                f"🔁 REDELIVERY DLQ: Message '{title}' has been redelivered {attempts} times "
                f"(limit: {settings.max_message_retries}), sending to DLQ to prevent infinite loop"
            )
            await self.record_failed(message, error_msg)
            dlq_status = self.send_to_dlq(message, error_msg)
            if dlq_status:
                self.total_dlq_redelivery += 1
                try:
                    await self.redis_client.delete(attempt_key)  # Clean up
                except Exception as e:
                    logger.debug(f"Failed to delete attempt key: {e}")
                logger.info(
                    f"✅ REDELIVERY → DLQ: Message '{title}' sent to DLQ after {attempts} redelivery attempts "
                    f"(total redelivery DLQs: {self.total_dlq_redelivery})"
                )
                return "dequeue"  # ACK to remove from queue
            else:
                logger.error(
                    f"⚠️  Failed to send redelivery message '{title}' to DLQ, will requeue for another DLQ attempt"
                )
                return "requeue"  # NACK to requeue
        
        return "process"
    
    async def _check_stop_flag(self, message: Dict[str, Any]) -> bool:
        """
        Check for external stop/purge signal before doing heavy work (ASYNC).
        
        Args:
            message: Message from RabbitMQ
            
        Returns:
            True if message should be processed, False if service is stopping
        """
        if not self.redis_client:
            return True
        
        stop_value = await self.redis_client.get("digester:stop")
        if stop_value != "1":
            return True
        
        # Stop flag detected
        logger.warning("Digester stop flag detected - acknowledging message without processing and stopping consumer")
        
        try:
            await self.redis_client.delete("digester:stop")
        except Exception as e:
            logger.debug(f"Failed to delete stop flag: {e}")
        
        await self.clear_current_processing()
        
        # Record skipped message
        if self.redis_client:
            try:
                title = self._get_message_title(message)
                skipped_data = {
                    "title": title,
                    "url": message.get("resource_data", {}).get("url") or message.get("event_data", {}).get("url") or "",
                    "status": "skipped",
                    "stage": "stopped",
                    "started_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "reason": "digester stop flag"
                }
                await self._record_to_redis_list(
                    "processing:completed",
                    skipped_data,
                    REDIS_MAX_COMPLETED_ITEMS,
                    "skipped message"
                )
            except Exception as e:
                logger.debug(f"Failed to record skipped message: {e}")
        
        # Stop consumer (async)
        try:
            await self.rabbitmq_consumer.stop()
        except Exception as e:
            logger.error(f"Failed to stop consumer after stop flag: {e}", exc_info=True)
        
        return False

    async def process_message(self, message: Dict[str, Any]) -> bool:
        """
        Route and process a message based on its type (ASYNC VERSION).
        
        Args:
            message: Message from RabbitMQ (event or resource)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Update heartbeat
            await self.update_heartbeat()
            
            # Check delivery attempts FIRST to prevent infinite redelivery loops
            # This tracks how many times RabbitMQ has redelivered this message
            attempt_status = await self._check_delivery_attempts(message)
            if attempt_status == "requeue":
                return False  # DLQ delivery failed, NACK to requeue
            elif attempt_status == "dequeue":
                return True  # Max retries exceeded, ACK to remove from queue
            
            # Check for external stop/purge signal before doing any heavy work
            if not await self._check_stop_flag(message):
                return True  # ACK and stop processing

            # Determine message type and route accordingly
            message_type = message.get("message_type")
            
            # Route to appropriate processor
            if message_type == "event":
                return await self.process_event_message(message)
            elif message_type == "resource":
                return await self.process_resource_message(message)
            else:
                raise ValueError(f"Unknown or missing message_type: {message_type}")
                
        except ValueError as e:
            # Validation errors - send to DLQ (non-retryable)
            title = self._get_message_title(message)
            error_msg = f"VALIDATION ERROR: {str(e)}"
            logger.error(f"❌ VALIDATION DLQ: Message '{title}' has validation error: {error_msg}")
            
            await self.record_failed(message, error_msg)
            await self.clear_current_processing()
            
            # Only ACK if we successfully sent to DLQ
            if self.send_to_dlq(message, error_msg):
                self.total_dlq_validation += 1
                logger.info(
                    f"✅ VALIDATION → DLQ: Message '{title}' sent to DLQ "
                    f"(total validation DLQs: {self.total_dlq_validation})"
                )
                return True  # Ack to remove from main queue
            else:
                logger.error(f"⚠️  Failed to send validation error message '{title}' to DLQ, returning False to trigger requeue")
                return False  # NACK to requeue - don't lose the message
            
        except Exception as e:
            # All other errors (including rate limits after retries) - let consumer requeue
            logger.error(f"Failed to process message: {e}", exc_info=True)
            await self.record_failed(message, str(e))
            await self.clear_current_processing()
            # Return False: consumer will NACK and requeue
            # On next redelivery, attempt counter at top will increment
            return False

    async def process_event_message(self, message: Dict[str, Any]) -> bool:
        """
        Process an event message - validate and insert Event node into Neo4j (ASYNC VERSION).
        
        Events come with structured data from the retriever, so no LLM extraction needed.
        
        Args:
            message: Event message from RabbitMQ with event_data
            
        Returns:
            True if successful, False otherwise
        """
        event_data = message.get("event_data", {})
        event_name = event_data.get("name", "Unknown Event")
        batch_id = message.get("batch_id")
        
        logger.info(f"Processing event: {event_name}")
        await self.update_current_processing(message, "validating")
        
        # Validate event message
        self.validate_event_message(message)
        
        logger.info("Building Event model...")
        await self.update_current_processing(message, "building model")
        
        # Build Event model using model_builder
        event_model = build_event_model(
            event_data=event_data,
            scraped_at=message.get("scraped_at"),
            datasource_id=message.get("datasource_id"),
            batch_id=batch_id
        )
        
        logger.info("Inserting event into knowledge graph...")
        await self.update_current_processing(message, "inserting into graph")
        
        # Wrap Neo4j operation in thread (it's sync, not async yet)
        result = await asyncio.to_thread(
            self.graph_repository.create_node, event_model
        )
        
        logger.info(f"Successfully processed event: {event_name}")
        
        # Update batch tracking
        if batch_id:
            self._update_batch_progress(batch_id, item_type="event")
        
        # Record success
        await self.record_completed(message, None)
        await self.clear_current_processing()
        
        # Clear delivery attempt counter on success
        await self._clear_delivery_attempts(message)
        
        # Track success metric
        self.total_messages_processed += 1
        logger.info(
            f"✅ SUCCESS: Event '{event_name}' processed successfully "
            f"(total processed: {self.total_messages_processed})"
        )
        
        return True

    async def process_resource_message(self, message: Dict[str, Any]) -> bool:
        """
        Process a resource message - extract metadata via LLM and insert into Neo4j (ASYNC VERSION).
        
        Args:
            message: Resource message from RabbitMQ with resource_data
            
        Returns:
            True if successful, False otherwise
        """
        resource_data = message.get("resource_data", {})
        title = resource_data.get("title", "Unknown")
        
        logger.info(f"Processing resource: {title}")
        await self.update_current_processing(message, "validating")
        
        # Handle video-specific processing
        if resource_data.get('category') == 'video' or resource_data.get('doc_type') == 'video':
            resource_data = self._handle_video_metadata(resource_data)
            logger.info(f"Enhanced video metadata for: {resource_data['title']}")
        
        # Validate resource message
        self.validate_resource_message(message)

        # # Step 1.5: Retrieve and parse binary content if file:// URL
        url = resource_data.get("url", "")
        if url.startswith("file:///") and self.redis_client:
            file_type = message.get("metadata", {}).get("file_type", "")
            if not file_type:
                file_type = url.rsplit(".", 1)[-1] if "." in url else ""
            
            logger.info(f"Attempting to retrieve cached content for {url}")
            # Wrap sync doc_parser in thread since it's not async yet
            parsed_content = await asyncio.to_thread(
                self.doc_parser.retrieve_and_parse,
                self.redis_client, url, file_type
            )
            
            if parsed_content:
                logger.info(f"Successfully parsed cached content ({len(parsed_content)} chars)")
                resource_data["content"] = parsed_content
            else:
                logger.warning(f"Could not retrieve/parse cached content for {url}")

        logger.info("Extracting and validating metadata nodes from content...")
        await self.update_current_processing(message, "extracting metadata")
        
        # CHANGED: await the async metadata extraction
        metadata = await self.metadata_extractor.extract_metadata(message)            

        logger.info("Building validated models from metadata...")
        models: BuiltModelsDict = build_models(metadata)

        logger.info("Attempt to relate resource to event if applicable...")
        # Add event relationship if document title contains a date OR if video has event metadata
        resource_node = models["nodes"]["resource"]
        video_metadata = resource_data.get('video_metadata', {})
        
        if resource_node:
            # Check for event metadata from YouTube video
            if video_metadata.get('event_name') and video_metadata.get('event_year'):
                try:
                    logger.info(f"Creating/linking event from video metadata: {video_metadata['event_name']}")
                    
                    # Create Event node from video metadata
                    from datetime import datetime as dt
                    from neo4j_client.models import Event, ResourceRelatesToEvent
                    
                    event_name = video_metadata['event_name']
                    event_year = int(video_metadata['event_year'])
                    event_type = video_metadata.get('event_type', 'conference')
                    
                    # Create event URL from name (for stable ID)
                    event_url_base = event_name.lower().replace(' ', '-').replace('&', 'and')
                    event_url = f"https://event.placeholder/{event_url_base}-{event_year}"
                    
                    # Estimate start date from year (use video publish date if available, otherwise Jan 1)
                    start_date = None
                    if resource_data.get('publish_date'):
                        try:
                            from dateutil.parser import parse as date_parse
                            start_date = date_parse(resource_data['publish_date'])
                        except:
                            pass
                    
                    if not start_date:
                        start_date = dt(event_year, 1, 1)
                    
                    # Create Event node
                    event_node = Event(
                        name=event_name,
                        event_type=event_type,
                        start_date=start_date,
                        url=event_url,
                        description=f"Event detected from video: {resource_data.get('title', '')}",
                        datasource_id=message.get("datasource_id", "youtube"),
                        scraped_at=dt.now(),
                        status="completed" if event_year < dt.now().year else "scheduled"
                    )
                    
                    # Create relationship
                    confidence = video_metadata.get('event_confidence', 0.9)
                    event_relationship = ResourceRelatesToEvent(
                        source_id=resource_node.url_hash,
                        target_id=event_node.url_hash,
                        confidence=confidence,
                        evidence=f"Video title: {resource_data.get('title', '')}",
                        context_type="material"  # Video is material FROM the event
                    )
                    
                    # Add event node and relationship to models
                    models["nodes"]["events"] = models["nodes"].get("events", [])
                    models["nodes"]["events"].append(event_node)
                    models["relationships"].append(event_relationship)
                    
                    logger.info(f"Added event node '{event_name}' and relationship (confidence: {confidence})")
                    
                except Exception as e:
                    logger.warning(f"Failed to create event from video metadata: {e}")
            
            # Fall back to date-based event association for non-video resources
            else:
                try:
                    event_relationship = await self.event_associator.get_event_relationship(
                        resource_url_hash=resource_node.url_hash,
                        resource_title=title,
                        resource_summary=metadata.get("nodes", {}).get("resource", {}).get("summary", ""),
                        datasource_id=message.get("datasource_id", "")
                    )
                    if event_relationship:
                        models["relationships"].append(event_relationship)
                        logger.info(f"Added event relationship to models")
                except Exception as e:
                    logger.warning(f"Failed to get event relationship: {e}")

        logger.info("Deduping nodes...")
        # Deduplicate and replace models dict with deduplicated version
        models = await asyncio.to_thread(self.deduplicator.deduplicate_nodes, models)

        logger.info("Inserting entities into knowledge graph...")
        await self.update_current_processing(message, "inserting into graph")
        
        # Wrap Neo4j operation in thread
        stats = await asyncio.to_thread(self.graph_repository.insert_entities, models)

        # Create UPLOADED_BY relationship if uploaded_by field is present
        uploaded_by = message.get("uploaded_by")
        if uploaded_by:
            try:
                logger.info(f"Creating UPLOADED_BY relationship for user {uploaded_by}...")
                
                # Get resource node from models dict
                resource_node = models["nodes"].get("resource")
                
                if resource_node:
                    # Find the existing Person node by user_uuid
                    find_person_query = """
                    MATCH (p:Person {user_uuid: $user_uuid})
                    RETURN p.person_id as person_id
                    LIMIT 1
                    """
                    person_results = self.graph_repository.client.execute_query(
                        find_person_query, 
                        {"user_uuid": uploaded_by}
                    )
                    
                    if person_results:
                        person_id = person_results[0]["person_id"]
                        
                        uploaded_by_rel = ResourceUploadedByPerson(
                            source_id=resource_node.url_hash,
                            target_id=person_id,
                            uploaded_at=datetime.now().isoformat()
                        )
                        
                        await asyncio.to_thread(self.graph_repository.create_relationship, uploaded_by_rel)
                        logger.info(f"Created UPLOADED_BY relationship for user {uploaded_by}")
                    else:
                        logger.warning(f"Person node not found for user_uuid {uploaded_by}, skipping UPLOADED_BY relationship")
                else:
                    logger.error("Resource node not found in models, cannot create UPLOADED_BY relationship")
                    
            except Exception as e:
                logger.error(f"Failed to create UPLOADED_BY relationship: {e}", exc_info=True)

        # Create RELATES_TO relationships for user-specified event associations
        related_events = message.get("related_events", [])
        if related_events and resource_node:
            logger.info(f"Creating event associations for {len(related_events)} event(s)...")
            for event_url_hash in related_events:
                try:
                    event_rel = ResourceRelatesToEvent(
                        source_id=resource_node.url_hash,
                        target_id=event_url_hash,
                        confidence=0.9,  # High confidence for user-specified associations
                        evidence="User uploaded document for this event",
                        context_type="material"
                    )
                    
                    # Insert the relationship
                    await asyncio.to_thread(
                        self.graph_repository.create_relationship, event_rel
                    )
                    logger.info(f"Created RELATES_TO relationship: Resource {resource_node.url_hash[:8]}... -> Event {event_url_hash[:8]}...")
                    
                except Exception as e:
                    logger.warning(f"Failed to create event relationship to {event_url_hash}: {e}")

        logger.info(f"Successfully processed resource: {title}")
        logger.info(f"Insert stats: {stats}")
        
        # Update batch tracking
        batch_id = message.get("batch_id")
        if batch_id:
            self._update_batch_progress(batch_id, item_type="resource")
        
        # Record success
        await self.record_completed(message, metadata)
        await self.clear_current_processing()
        
        # Clear delivery attempt counter on success
        await self._clear_delivery_attempts(message)
        
        # Track success metric
        self.total_messages_processed += 1
        logger.info(
            f"✅ SUCCESS: Resource '{title}' processed successfully "
            f"(total processed: {self.total_messages_processed})"
        )

        return True
    
    async def run(self):
        """Run the document digester service (ASYNC VERSION)."""
        try:
            logger.info("Starting Document Digester Service (ASYNC MODE)...")

            # Start lightweight health server in background (port 8080)
            self.start_health_server()
            
            # Initialize graph
            self.initialize_graph()
            
            # Start consuming messages
            logger.info("Starting async message consumption from RabbitMQ...")
            
            # Async consumer handles everything, no need for separate stop flag monitor
            await self.rabbitmq_consumer.consume(self.process_message)
            
        except KeyboardInterrupt:
            logger.info("Received shutdown signal...")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            raise
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Cleanup and shutdown (ASYNC VERSION)."""
        logger.info("Shutting down Document Digester Service...")
        
        try:
            await self.rabbitmq_consumer.stop()
        except Exception as e:
            logger.error(f"Error stopping RabbitMQ consumer: {e}", exc_info=True)
        
        try:
            self.neo4j_client.close()
        except Exception as e:
            logger.error(f"Error closing Neo4j connection: {e}", exc_info=True)
        
        logger.info("Shutdown complete")

    def start_health_server(self):
        """Start a minimal HTTP health endpoint on /health (port 8080)."""
        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self_inner):
                if self_inner.path == "/health":
                    self_inner.send_response(200)
                    self_inner.send_header("Content-Type", "application/json")
                    self_inner.end_headers()
                    self_inner.wfile.write(b'{"status":"ok"}')
                else:
                    self_inner.send_response(404)
                    self_inner.end_headers()

            def log_message(self_inner, format, *args):  # suppress default stderr logging
                return

        try:
            server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            logger.info("Health server started on port 8080")
        except Exception as e:
            logger.warning(f"Failed to start health server: {e}")


def main():
    """Main entry point."""
    try:
        digester = DocumentDigester()
        asyncio.run(digester.run())
    except Exception as e:
        logger.error(f"Failed to start Document Digester: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
