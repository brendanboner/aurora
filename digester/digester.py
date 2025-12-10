"""
Document Digester Service

This service consumes messages from RabbitMQ, extracts metadata using LLM,
validates and normalizes the data, and inserts it into a Neo4j knowledge graph.
"""

import sys
from typing import Dict, Any
import re
from datetime import datetime
from dateutil.parser import parse as date_parse
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from settings import settings
from utils.logger import setup_logger
from rabbitmq_client import RabbitMQConsumer, RabbitMQProducer
from services.metadata_extractor import MetadataExtractor
from services.event_associator import EventAssociator
from utils.model_builder import build_models, build_event_model, BuiltModelsDict
from neo4j_client import Neo4jClient, GraphRepository, NodeDeduplicator

from neo4j_client.models import Person, ResourceUploadedByPerson
import redis
import json


logger = setup_logger(__name__, settings.log_level)


class DocumentDigester:
    """Main orchestrator for the document digestion pipeline."""
    
    def __init__(self):
        logger.info("Initializing Document Digester...")
        
        # Initialize components
        self.rabbitmq_consumer = RabbitMQConsumer(
            host=settings.rabbitmq_host,
            port=settings.rabbitmq_port,
            user=settings.rabbitmq_user,
            password=settings.rabbitmq_password,
            queue=settings.rabbitmq_queue,
            logger_instance=logger,
            max_workers=settings.rabbitmq_max_workers,
            heartbeat=settings.rabbitmq_heartbeat
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
        
        # Initialize Redis for monitoring and content caching
        try:
            self.redis_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                decode_responses=True,
                socket_connect_timeout=5
            )
            # Test connection
            self.redis_client.ping()
            logger.info("Redis connection established for monitoring and caching")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Monitoring will be disabled.")
            self.redis_client = None
        
        # Initialize document parser for binary files
        from utils.document_parser import DocumentParser
        self.doc_parser = DocumentParser()
        
        logger.info("Document Digester initialized")
    
    def initialize_graph(self):
        """
        Initialize Neo4j connection and create repository objects.
        
        Note: Schema creation and base data initialization are now handled
        by the neo4j-init container, which runs before this service starts.
        This method only establishes the connection and creates the repository.
        """
        logger.info("Connecting to Neo4j knowledge graph...")
        
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
            title = message.get("resource_data", {}).get("title", 
                    message.get("event_data", {}).get("name", "Unknown"))
            
            # Add error metadata
            dlq_message = {
                **message,
                "dlq_error": error,
                "dlq_timestamp": datetime.now().isoformat()
            }
            
            # Use fresh connection to avoid stale idle connection issues
            with RabbitMQProducer(
                **self._rabbitmq_config,
                queue=self._dlq_queue,
                logger_instance=logger
            ) as producer:
                producer.publish(dlq_message)
            
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
    
    def requeue_for_retry(self, message: Dict[str, Any], error: str) -> bool:
        """
        Republish a message to the main queue with incremented retry count.
        
        Uses a fresh connection each time to avoid stale idle connections.
        This is the proper way to implement retries - we ACK the original message
        and publish a new one with updated retry metadata, rather than using
        RabbitMQ's requeue which doesn't persist our modifications.
        
        Args:
            message: The original message that failed
            error: Error message describing why it failed
            
        Returns:
            True if republished successfully, False otherwise
        """
        try:
            retry_count = message.get("retry_count", 0) + 1
            max_retries = settings.max_message_retries
            
            title = message.get("resource_data", {}).get("title", 
                    message.get("event_data", {}).get("name", "Unknown"))
            
            # Check if max retries exceeded
            if retry_count > max_retries:
                error_msg = f"Max retries ({max_retries}) exceeded: {error}"
                logger.error(f"Sending to DLQ after {retry_count - 1} retries: {title}")
                return self.send_to_dlq(message, error_msg)
            
            # Add retry metadata to message
            retry_message = {
                **message,
                "retry_count": retry_count,
                "last_error": error,
                "last_retry_at": datetime.now().isoformat()
            }
            
            # Use fresh connection to avoid stale idle connection issues
            with RabbitMQProducer(
                **self._rabbitmq_config,
                queue=self._retry_queue,
                logger_instance=logger
            ) as producer:
                producer.publish(retry_message)
            
            logger.info(f"Requeued message for retry ({retry_count}/{max_retries}): {title}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to requeue message for retry: {e}", exc_info=True)
            # If we can't requeue, try to send to DLQ as fallback
            return self.send_to_dlq(message, f"Requeue failed: {e}, Original error: {error}")
    
    def update_heartbeat(self):
        """Update digester heartbeat timestamp in Redis."""
        if self.redis_client:
            try:
                self.redis_client.setex("digester:heartbeat", 300, datetime.now().timestamp())
            except Exception as e:
                logger.warning(f"Failed to update heartbeat: {e}")
    
    def update_current_processing(self, message: Dict[str, Any], stage: str):
        """Update current processing status in Redis."""
        if self.redis_client:
            try:
                processing_data = {
                    "title": message.get("title", "Unknown"),
                    "url": message.get("url", ""),
                    "category": message.get("category", "unknown"),
                    "status": "processing",
                    "stage": stage,
                    "started_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat()
                }
                self.redis_client.setex("digester:current", 300, json.dumps(processing_data))
            except Exception as e:
                logger.warning(f"Failed to update current processing: {e}")
    
    def clear_current_processing(self):
        """Clear current processing status in Redis."""
        if self.redis_client:
            try:
                self.redis_client.delete("digester:current")
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
                    logger.info(f"Batch {batch_id} completed: {items_digested} items digested")
            else:
                logger.warning(f"Batch {batch_id} not found when updating progress")
                
        except Exception as e:
            logger.warning(f"Failed to update batch progress for {batch_id}: {e}")
    
    def record_completed(self, message: Dict[str, Any], metadata: Dict[str, Any] = None):
        """Record successfully completed document in Redis."""
        if self.redis_client:
            try:
                completed_data = {
                    "title": message.get("title", "Unknown"),
                    "url": message.get("url", ""),
                    "category": message.get("category", "unknown"),
                    "status": "completed",
                    "stage": "inserted",
                    "started_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "datasource_id": message.get("datasource_id", ""),
                    "publish_date": message.get("publish_date", ""),
                    "uploaded_by": message.get("uploaded_by", "")
                }
                
                # Add metadata if provided
                if metadata:
                    completed_data["metadata"] = metadata
                
                # Keep last 20 completed items
                self.redis_client.lpush("processing:completed", json.dumps(completed_data))
                self.redis_client.ltrim("processing:completed", 0, 19)
            except Exception as e:
                logger.warning(f"Failed to record completed: {e}")
    
    def record_failed(self, message: Dict[str, Any], error: str):
        """Record failed document in Redis."""
        if self.redis_client:
            try:
                failed_data = {
                    "title": message.get("title", "Unknown"),
                    "url": message.get("url", ""),
                    "category": message.get("category", "unknown"),
                    "status": "failed",
                    "stage": "error",
                    "started_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "error": error
                }
                # Keep last 20 failed items
                self.redis_client.lpush("processing:failed", json.dumps(failed_data))
                self.redis_client.ltrim("processing:failed", 0, 19)
            except Exception as e:
                logger.warning(f"Failed to record failure: {e}")
    
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

        # url must be a valid URL string (http, https, or file protocols)
        url_pattern = re.compile(r'^(https?|file)://[^\s]+$')
        if not isinstance(resource_data["url"], str) or not url_pattern.match(resource_data["url"]):
            raise ValueError("Field 'url' must be a valid URL string (http, https, or file protocol).")

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
    
    def _get_delivery_attempt_key(self, message: Dict[str, Any]) -> str:
        """Get Redis key for tracking delivery attempts."""
        msg_id = self._get_message_id(message)
        return f"delivery_attempts:{hash(msg_id)}"
    
    def _clear_delivery_attempts(self, message: Dict[str, Any]):
        """Clear delivery attempt counter after successful processing."""
        if self.redis_client:
            try:
                self.redis_client.delete(self._get_delivery_attempt_key(message))
            except Exception as e:
                logger.debug(f"Failed to clear delivery attempts: {e}")

    def process_message(self, message: Dict[str, Any]) -> bool:
        """
        Route and process a message based on its type.
        
        Args:
            message: Message from RabbitMQ (event or resource)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Update heartbeat
            self.update_heartbeat()
            
            # Track delivery attempts in Redis to prevent infinite redelivery loops
            # This catches cases where the channel dies mid-processing and the message
            # gets redelivered without our retry_count metadata
            if self.redis_client:
                attempt_key = self._get_delivery_attempt_key(message)
                attempts = self.redis_client.incr(attempt_key)
                self.redis_client.expire(attempt_key, 3600)  # 1 hour TTL
                
                if attempts > settings.max_message_retries:
                    resource_data = message.get("resource_data", {})
                    event_data = message.get("event_data", {})
                    title = resource_data.get("title", event_data.get("name", "Unknown"))
                    error_msg = f"Max delivery attempts ({attempts}) exceeded - possible infinite redelivery loop"
                    logger.error(f"Sending to DLQ after {attempts} delivery attempts: {title}")
                    self.record_failed(message, error_msg)
                    self.send_to_dlq(message, error_msg)
                    self.redis_client.delete(attempt_key)  # Clean up
                    return True  # ACK to remove from queue

            # Check for external stop / purge signal before doing any heavy work
            if self.redis_client and self.redis_client.get("digester:stop") == "1":
                logger.warning("Digester stop flag detected - acknowledging message without processing and stopping consumer")
                try:
                    self.redis_client.delete("digester:stop")
                except Exception as e:
                    logger.debug(f"Failed to delete stop flag: {e}")
                self.clear_current_processing()
                if self.redis_client:
                    try:
                        skipped_data = {
                            "title": message.get("resource_data", {}).get("title", message.get("event_data", {}).get("name", "Skipped")),
                            "url": message.get("resource_data", {}).get("url", message.get("event_data", {}).get("url", "")),
                            "status": "skipped",
                            "stage": "stopped",
                            "started_at": datetime.now().isoformat(),
                            "updated_at": datetime.now().isoformat(),
                            "reason": "digester stop flag"
                        }
                        self.redis_client.lpush("processing:completed", json.dumps(skipped_data))
                        self.redis_client.ltrim("processing:completed", 0, 19)
                    except Exception as e:
                        logger.debug(f"Failed to record skipped message: {e}")
                try:
                    threading.Thread(target=self.rabbitmq_consumer.stop, daemon=True).start()
                except Exception as e:
                    logger.error(f"Failed to stop consumer after stop flag: {e}")
                return True

            # Determine message type and route accordingly
            message_type = message.get("message_type")
            
            # Route to appropriate processor
            if message_type == "event":
                return self.process_event_message(message)
            elif message_type == "resource":
                return self.process_resource_message(message)
            else:
                raise ValueError(f"Unknown or missing message_type: {message_type}")
                
        except ValueError as e:
            # Validation errors - send to DLQ (non-retryable)
            title = message.get("resource_data", {}).get("title", message.get("event_data", {}).get("name", "Unknown"))
            error_msg = str(e)
            logger.error(f"Validation error for '{title}': {error_msg}")
            
            self.record_failed(message, error_msg)
            self.clear_current_processing()
            
            # Only ACK if we successfully sent to DLQ
            if self.send_to_dlq(message, error_msg):
                return True  # Ack to remove from main queue
            else:
                logger.error(f"Failed to send to DLQ, returning False to trigger requeue")
                return False  # NACK to requeue - don't lose the message
            
        except Exception as e:
            # All other errors (including rate limits after retries) - requeue for retry
            logger.error(f"Failed to process message: {e}", exc_info=True)
            self.record_failed(message, str(e))
            self.clear_current_processing()
            
            # Republish message with incremented retry count (or send to DLQ if max exceeded)
            # Only ACK if requeue/DLQ was successful
            if self.requeue_for_retry(message, str(e)):
                return True  # ACK - retry is handled by republishing
            else:
                logger.error(f"Failed to requeue or send to DLQ, returning False to trigger requeue")
                return False  # NACK to requeue - don't lose the message

    def process_event_message(self, message: Dict[str, Any]) -> bool:
        """
        Process an event message - validate and insert Event node into Neo4j.
        
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
        self.update_current_processing({"title": event_name, "url": event_data.get("url", ""), "category": "event"}, "validating")
        
        # Validate event message
        self.validate_event_message(message)
        
        logger.info("Building Event model...")
        self.update_current_processing({"title": event_name, "url": event_data.get("url", ""), "category": "event"}, "building model")
        
        # Build Event model using model_builder
        event_model = build_event_model(
            event_data=event_data,
            scraped_at=message.get("scraped_at"),
            datasource_id=message.get("datasource_id"),
            batch_id=batch_id
        )
        
        # logger.info("Inserting event into knowledge graph...")
        self.update_current_processing({"title": event_name, "url": event_data.get("url", ""), "category": "event"}, "inserting into graph")
        
        # create_node automatically creates INGESTED_FROM relationship via datasource_id
        result = self.graph_repository.create_node(event_model)
        
        logger.info(f"Successfully processed event: {event_name}")
        
        # Update batch tracking
        if batch_id:
            self._update_batch_progress(batch_id, item_type="event")
        
        # # Record success
        self.record_completed({"title": event_name, "url": event_data.get("url", ""), "category": "event", "datasource_id": message.get("datasource_id", "")}, None)
        self.clear_current_processing()
        
        # Clear delivery attempt counter on success
        self._clear_delivery_attempts(message)
        
        return True

    def process_resource_message(self, message: Dict[str, Any]) -> bool:
        """
        Process a resource message - extract metadata via LLM and insert into Neo4j.
        
        Args:
            message: Resource message from RabbitMQ with resource_data
            
        Returns:
            True if successful, False otherwise
        """
        resource_data = message.get("resource_data", {})
        title = resource_data.get("title", "Unknown")
        
        logger.info(f"Processing resource: {title}")
        self.update_current_processing({"title": title, "url": resource_data.get("url", ""), "category": resource_data.get("category", "unknown")}, "validating")
        
        # Validate resource message
        self.validate_resource_message(message)

        # # Step 1.5: Retrieve and parse binary content if file:// URL
        url = resource_data.get("url", "")
        if url.startswith("file:///") and self.redis_client:
            file_type = message.get("metadata", {}).get("file_type", "")
            if not file_type:
                file_type = url.rsplit(".", 1)[-1] if "." in url else ""
            
            logger.info(f"Attempting to retrieve cached content for {url}")
            parsed_content = self.doc_parser.retrieve_and_parse(
                self.redis_client, url, file_type
            )
            
            if parsed_content:
                logger.info(f"Successfully parsed cached content ({len(parsed_content)} chars)")
                resource_data["content"] = parsed_content
            else:
                logger.warning(f"Could not retrieve/parse cached content for {url}")

        logger.info("Extracting and validating metadata nodes from content...")
        self.update_current_processing({"title": title, "url": resource_data.get("url", ""), "category": resource_data.get("category", "unknown")}, "extracting metadata")
        metadata = self.metadata_extractor.extract_metadata(message)            

        logger.info("Building validated models from metadata...")
        models: BuiltModelsDict = build_models(metadata)

        logger.info("Attempt to relate resource to event if applicable...")
        # Add event relationship if document title contains a date
        resource_node = models["nodes"]["resource"]
        if resource_node:
            try:
                event_relationship = self.event_associator.get_event_relationship(
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
        deduped_models = self.deduplicator.deduplicate_nodes(models)

        logger.info("Inserting entities into knowledge graph...")
        self.update_current_processing({"title": title, "url": resource_data.get("url", ""), "category": resource_data.get("category", "unknown")}, "inserting into graph")
        stats = self.graph_repository.insert_entities(deduped_models)

        # # Create UPLOADED_BY relationship if uploaded_by field is present
        uploaded_by = message.get("uploaded_by")
        if uploaded_by:
            try:
                logger.info(f"Creating UPLOADED_BY relationship for user {uploaded_by}...")
                
                person = Person(
                    person_id=uploaded_by,
                    name=uploaded_by
                )
                
                resource_node = None
                for model in deduped_models:
                    if model.__class__.__name__ == "Resource":
                        resource_node = model
                        break
                
                if resource_node:
                    uploaded_by_rel = ResourceUploadedByPerson(
                        source=resource_node,
                        target=person,
                        uploaded_at=datetime.now().isoformat()
                    )
                    
                    upload_models = [person, uploaded_by_rel]
                    deduped_upload = self.deduplicator.deduplicate_nodes(upload_models)
                    upload_stats = self.graph_repository.insert_entities(deduped_upload)
                    
                    logger.info(f"Created UPLOADED_BY relationship: {upload_stats}")
                else:
                    logger.warning("Resource node not found in models, skipping UPLOADED_BY relationship")
                    
            except Exception as e:
                logger.warning(f"Failed to create UPLOADED_BY relationship: {e}")

        logger.info(f"Successfully processed resource: {title}")
        logger.info(f"Insert stats: {stats}")
        
        # Update batch tracking
        batch_id = message.get("batch_id")
        if batch_id:
            self._update_batch_progress(batch_id, item_type="resource")
        
        # Record success
        record_msg = {"title": title, "url": resource_data.get("url", ""), "category": resource_data.get("category", "unknown"), "datasource_id": message.get("datasource_id", ""), "publish_date": resource_data.get("publish_date", ""), "uploaded_by": message.get("uploaded_by", "")}
        self.record_completed(record_msg, metadata)
        self.clear_current_processing()
        
        # Clear delivery attempt counter on success
        self._clear_delivery_attempts(message)

        return True
    
    def run(self):
        """Run the document digester service."""
        try:
            logger.info("Starting Document Digester Service...")

            # Start lightweight health server in background (port 8080)
            self.start_health_server()
            
            # Initialize graph
            self.initialize_graph()
            
            # Start consuming messages
            logger.info("Starting message consumption from RabbitMQ...")
            # Background monitor for stop flag to allow immediate shutdown even when queue empty
            if self.redis_client:
                def monitor_stop_flag():
                    while True:
                        try:
                            if self.redis_client.get("digester:stop") == "1":
                                logger.warning("Digester stop flag detected by monitor - stopping consumer")
                                try:
                                    self.redis_client.delete("digester:stop")
                                except Exception as e:
                                    logger.debug(f"Failed to delete stop flag in monitor: {e}")
                                try:
                                    self.rabbitmq_consumer.stop()
                                except Exception as e:
                                    logger.error(f"Error stopping consumer from monitor: {e}")
                                break
                        except Exception as e:
                            logger.debug(f"Stop flag monitor error: {e}")
                        time.sleep(2)
                threading.Thread(target=monitor_stop_flag, daemon=True).start()
            self.rabbitmq_consumer.consume(
                self.process_message,
                prefetch_count=settings.rabbitmq_prefetch_count
            )
            
        except KeyboardInterrupt:
            logger.info("Received shutdown signal...")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            sys.exit(1)
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Cleanup and shutdown."""
        logger.info("Shutting down Document Digester Service...")
        
        try:
            self.rabbitmq_consumer.stop()
        except Exception as e:
            logger.error(f"Error stopping RabbitMQ consumer: {e}")
        
        try:
            self.neo4j_client.close()
        except Exception as e:
            logger.error(f"Error closing Neo4j connection: {e}")
        
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
        digester.run()
    except Exception as e:
        logger.error(f"Failed to start Document Digester: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
