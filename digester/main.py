"""
Document Digester Service

This service consumes messages from RabbitMQ, extracts metadata using LLM,
validates and normalizes the data, and inserts it into a Neo4j knowledge graph.
"""

import sys
from typing import Dict, Any

from settings import settings
from utils.logger import setup_logger
from rabbitmq_client import RabbitMQConsumer, RabbitMQProducer
from llm import MetadataExtractor
from normalization import MetadataValidator, MetadataNormalizer
from neo4j_client import Neo4jClient, GraphRepository


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
            logger_instance=logger
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
        self.normalizer = MetadataNormalizer()
        
        # Initialize Neo4j client with settings and logger
        self.neo4j_client = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
            logger_instance=logger
        )
        self.graph_repository = None
        
        logger.info("Document Digester initialized")
    
    def initialize_graph(self):
        """Initialize Neo4j connection and setup base data."""
        logger.info("Initializing Neo4j knowledge graph...")
        
        # Connect to Neo4j
        self.neo4j_client.connect()
        
        # Create constraints
        self.neo4j_client.create_constraints()
        
        # Create repository with logger
        self.graph_repository = GraphRepository(self.neo4j_client, logger_instance=logger)
        
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
                "dlq_timestamp": __import__('datetime').datetime.now().isoformat()
            }
            
            self.dlq_producer.publish(dlq_message)
            logger.info(f"Sent document to DLQ: {title} - Reason: {error}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send message to DLQ: {e}", exc_info=True)
            return False
    
    def process_message(self, message: Dict[str, Any]) -> bool:
        """
        Process a single message through the pipeline.
        
        Args:
            message: Document message from RabbitMQ
            
        Returns:
            True if successful, False otherwise
        """
        
        try:
            title = message.get("title", "Unknown")
            logger.info(f"Processing document: {title}")
            
            # Step 1: Extract metadata using LLM
            logger.info("Step 1: Extracting metadata with LLM...")
            metadata = self.metadata_extractor.extract_metadata(message)
            
            # Step 2: Validate metadata
            logger.info("Step 2: Validating metadata...")
            self.validator.validate_metadata(metadata)
            
            # Step 3: Normalize metadata
            logger.info("Step 3: Normalizing metadata...")
            normalized_metadata = self.normalizer.normalize_metadata(metadata)
            
            # Step 4: Extract entities
            logger.info("Step 4: Extracting entities...")
            resource, topics, standards, standard_editions, datasource_id = self.normalizer.extract_entities(normalized_metadata)
            
            # Step 5: Insert into knowledge graph
            logger.info("Step 5: Inserting into knowledge graph...")
            self.graph_repository.insert_entities(
                resource=resource,
                topics=topics,
                standards=standards,
                standard_editions=standard_editions,
                datasource_id=datasource_id
            )
            
            logger.info(f"Successfully processed document: {title}")
            return True
        
        except ValueError as e:
            # Validation errors (including normalization failures) - send to DLQ
            title = message.get("title", "Unknown")
            logger.error(f"Validation error for document '{title}': {e}")
            self.send_to_dlq(message, str(e))
            return True  # Return True to acknowledge and remove from main queue
            
        except Exception as e:
            logger.error(f"Failed to process message: {e}", exc_info=True)
            # Return False to requeue for retry on other errors
            return False
    
    def run(self):
        """Run the document digester service."""
        try:
            logger.info("Starting Document Digester Service...")
            
            # Initialize graph
            self.initialize_graph()
            
            # Start consuming messages
            logger.info("Starting message consumption from RabbitMQ...")
            self.rabbitmq_consumer.consume(self.process_message)
            
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
