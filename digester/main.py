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
from http.server import BaseHTTPRequestHandler, HTTPServer

from settings import settings
from utils.logger import setup_logger
from rabbitmq_client import RabbitMQConsumer, RabbitMQProducer
from llm import MetadataExtractor
from normalization import MetadataValidator, MetadataModelBuilder
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
        
        # Initialize DLQ producer for failed messages
        dlq_name = f"{settings.rabbitmq_queue}-dlq"
        self.dlq_producer = RabbitMQProducer(
            host=settings.rabbitmq_host,
            port=settings.rabbitmq_port,
            user=settings.rabbitmq_user,
            password=settings.rabbitmq_password,
            queue=dlq_name,
            logger_instance=logger
        )
        
        self.metadata_extractor = MetadataExtractor()
        self.validator = MetadataValidator()
        self.model_builder = MetadataModelBuilder()
        
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
        """Initialize Neo4j connection and setup base data."""
        logger.info("Initializing Neo4j knowledge graph...")
        
        # Connect to Neo4j
        self.neo4j_client.connect()
        
        # Create constraints
        self.neo4j_client.setup_schema()
        
        # Create repository with logger
        self.graph_repository = GraphRepository(self.neo4j_client, logger_instance=logger)
        
        # Create deduplicator with logger
        self.deduplicator = NodeDeduplicator(self.neo4j_client, logger_instance=logger)
        
        # Initialize base data (organizations and data sources)
        self.graph_repository.initialize_base_data()
        
        logger.info("Knowledge graph initialized successfully")
    
    def send_to_dlq(self, message: Dict[str, Any], error: str) -> bool:
        """
        Send a message to the Dead Letter Queue.
        
        Args:
            message: The original message that failed
            error: Error message describing why it failed
            
        Returns:
            True if sent successfully, False otherwise
        """
        try:
            title = message.get("title", "Unknown")
            
            # Add error metadata
            dlq_message = {
                **message,
                "dlq_error": error,
                "dlq_timestamp": datetime.now().isoformat()
            }
            
            self.dlq_producer.publish(dlq_message)
            logger.info(f"Sent document to DLQ: {title} - Reason: {error}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send message to DLQ: {e}", exc_info=True)
            return False
    
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
    
    def validate_message(self, message: Dict[str, Any]) -> None:
        """
        Validate the presence and correctness of required fields in the message.

        Args:
            message: The message to validate.

        Raises:
            ValueError: If any required field is missing or invalid.
        """

        # Ensure keys are present
        required_fields = ["title", "url", "category", "content", "datasource_id", "scraped_at", "publish_date"]
        missing_fields = [field for field in required_fields if field not in message]
        if missing_fields:
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")

        # Only publish_date can be null; if present, must be a non-empty string and valid date/datetime
        if message["publish_date"] is not None:
            if not isinstance(message["publish_date"], str) or not message["publish_date"].strip():
                logger.warning("publish_date is not a valid string, setting to null.")
                message["publish_date"] = None
            else:
                try:
                    date_parse(message["publish_date"])
                except Exception:
                    logger.warning("publish_date could not be parsed, setting to null.")
                    message["publish_date"] = None

        # scraped_at must be a valid Unix timestamp (int or float, positive)
        scraped_at = message["scraped_at"]
        if not (isinstance(scraped_at, (int, float)) and scraped_at > 0):
            raise ValueError("Field 'scraped_at' must be a valid Unix timestamp (positive integer or float).")

        # url must be a valid URL string (http, https, or file protocols)
        url_pattern = re.compile(r'^(https?|file)://[^\s]+$')
        if not isinstance(message["url"], str) or not url_pattern.match(message["url"]):
            raise ValueError("Field 'url' must be a valid URL string (http, https, or file protocol).")

        # uploaded_by is optional; if present, must be a non-empty string
        if "uploaded_by" in message:
            if not isinstance(message["uploaded_by"], str) or not message["uploaded_by"].strip():
                raise ValueError("Field 'uploaded_by' must be a non-empty string if provided.")

        # All other fields must be valid non-empty strings (except content for file:// URLs)
        for field in ["title", "category", "datasource_id"]:
            if not isinstance(message[field], str) or not message[field].strip():
                raise ValueError(f"Field '{field}' must be a non-empty string.")
        
        # Content can be empty for local file uploads (binary files), but must be a string
        if not isinstance(message["content"], str):
            raise ValueError("Field 'content' must be a string.")
    
    def process_message(self, message: Dict[str, Any]) -> bool:
        """
        Process a single message through the pipeline.
        
        Args:
            message: Document message from RabbitMQ
            
        Returns:
            True if successful, False otherwise
        """
        
        try:
            # Update heartbeat
            self.update_heartbeat()
            
            logger.info("Step 1: Validate RabbitMQ message...")
            self.update_current_processing(message, "validating")
            self.validate_message(message)

            # Step 1.5: Retrieve and parse binary content if file:// URL
            url = message.get("url", "")
            if url.startswith("file:///") and self.redis_client:
                # Extract file extension from metadata or URL
                file_type = message.get("metadata", {}).get("file_type", "")
                if not file_type:
                    # Try to extract from URL
                    file_type = url.rsplit(".", 1)[-1] if "." in url else ""
                
                logger.info(f"Attempting to retrieve cached content for {url}")
                parsed_content = self.doc_parser.retrieve_and_parse(
                    self.redis_client, url, file_type
                )
                
                if parsed_content:
                    logger.info(f"Successfully parsed cached content ({len(parsed_content)} chars)")
                    # Replace placeholder content with parsed text
                    message["content"] = parsed_content
                else:
                    logger.warning(f"Could not retrieve/parse cached content for {url}")

            logger.info("Step 2: Extracting and validating metadata nodes from content...")
            self.update_current_processing(message, "extracting metadata")
            metadata = self.metadata_extractor.extract_metadata(message)            

            logger.info("Step 3: Building validated models from metadata...")
            models = self.model_builder.build_models(metadata)

            logger.info("Step 4: Deduping nodes...")
            deduped_models = self.deduplicator.deduplicate_nodes(models)

            logger.info("Step 5: Inserting entities into knowledge graph...")
            self.update_current_processing(message, "inserting into graph")
            stats = self.graph_repository.insert_entities(deduped_models)

            # Step 6: Create UPLOADED_BY relationship if uploaded_by field is present
            uploaded_by = message.get("uploaded_by")
            if uploaded_by:
                try:
                    logger.info(f"Step 6: Creating UPLOADED_BY relationship for user {uploaded_by}...")
                    
                    # Create Person node for uploader if doesn't exist
                    person = Person(
                        person_id=uploaded_by,
                        name=uploaded_by
                    )
                    
                    # Find the Resource node from the inserted models
                    resource_node = None
                    for model in deduped_models:
                        if model.__class__.__name__ == "Resource":
                            resource_node = model
                            break
                    
                    if resource_node:
                        # Create UPLOADED_BY relationship
                        uploaded_by_rel = ResourceUploadedByPerson(
                            source=resource_node,
                            target=person,
                            uploaded_at=datetime.now().isoformat()
                        )
                        
                        # Insert Person and relationship
                        upload_models = [person, uploaded_by_rel]
                        deduped_upload = self.graph_repository.deduplicate_nodes(upload_models)
                        upload_stats = self.graph_repository.insert_entities(deduped_upload)
                        
                        logger.info(f"Created UPLOADED_BY relationship: {upload_stats}")
                    else:
                        logger.warning("Resource node not found in models, skipping UPLOADED_BY relationship")
                        
                except Exception as e:
                    logger.warning(f"Failed to create UPLOADED_BY relationship: {e}")
                    # Don't fail the entire process if this step fails

            logger.info(f"Successfully processed document: {message.get('title')}")
            logger.info(f"Insert stats: {stats}")
            
            # Record success and clear current
            self.record_completed(message, metadata)
            self.clear_current_processing()

            return True
        
        except ValueError as e:
            # Validation errors (including token limit and normalization failures) - send to DLQ
            title = message.get("title", "Unknown")
            error_msg = str(e)
            logger.error(f"Validation error for document '{title}': {error_msg}")
            
            # Record failure
            self.record_failed(message, error_msg)
            self.clear_current_processing()
            
            self.send_to_dlq(message, error_msg)
            return True  # Return True to acknowledge and remove from main queue
            
        except Exception as e:
            logger.error(f"Failed to process message: {e}", exc_info=True)
            
            # Record failure
            self.record_failed(message, str(e))
            self.clear_current_processing()
            
            # Return False to requeue for retry on other errors
            return False
    
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
            # Close DLQ producer if connection exists
            if self.dlq_producer.connection and self.dlq_producer.connection.is_open:
                self.dlq_producer.connection.close()
        except Exception as e:
            logger.error(f"Error closing DLQ producer connection: {e}")
        
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
