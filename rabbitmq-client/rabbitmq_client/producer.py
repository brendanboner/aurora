"""RabbitMQ Producer for publishing messages to a queue."""

import pika
import json
from typing import Dict, Any, List, Optional
import logging


logger = logging.getLogger(__name__)


class RabbitMQProducer:
    """Client for publishing messages to RabbitMQ."""
    
    def __init__(
        self,
        host: str,
        port: int = 5672,
        user: str = "guest",
        password: str = "guest",
        queue: str = "default_queue",
        logger_instance: Optional[logging.Logger] = None
    ):
        """
        Initialize RabbitMQ Producer.
        
        Args:
            host: RabbitMQ host
            port: RabbitMQ port (default: 5672)
            user: RabbitMQ username
            password: RabbitMQ password
            queue: Queue name to publish to
            logger_instance: Optional logger instance. If not provided, uses module logger
        """
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.queue = queue
        self.connection = None
        self.channel = None
        self.logger = logger_instance or logger
    
    def connect(self):
        """Establish connection to RabbitMQ."""
        credentials = pika.PlainCredentials(self.user, self.password)
        parameters = pika.ConnectionParameters(
            host=self.host,
            port=self.port,
            credentials=credentials
        )
        
        self.logger.info(f"Connecting to RabbitMQ at {self.host}:{self.port}")
        self.connection = pika.BlockingConnection(parameters)
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=self.queue, durable=True)
        self.logger.info(f"Connected to RabbitMQ, publishing to queue: {self.queue}")
    
    def publish(self, message: Dict[str, Any], persistent: bool = True):
        """
        Publish a message to the queue.
        
        Args:
            message: Dictionary to publish (will be JSON serialized)
            persistent: If True, message survives broker restart (default: True)
        """
        if not self.channel:
            self.connect()
        
        try:
            # Serialize to JSON
            body = json.dumps(message)
            
            # Set message properties
            properties = pika.BasicProperties(
                delivery_mode=2 if persistent else 1  # 2 = persistent
            )
            
            # Publish
            self.channel.basic_publish(
                exchange='',
                routing_key=self.queue,
                body=body,
                properties=properties
            )
            
            msg_id = message.get('title', message.get('id', message.get('url', 'Unknown')))
            self.logger.info(f"Published message: {msg_id}")
            
        except (TypeError, ValueError) as e:
            self.logger.error(f"Failed to serialize message: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Failed to publish message: {e}", exc_info=True)
            raise
    
    def publish_batch(self, messages: List[Dict[str, Any]], persistent: bool = True):
        """
        Publish multiple messages to the queue.
        
        Args:
            messages: List of dictionaries to publish
            persistent: If True, messages survive broker restart (default: True)
        """
        if not self.channel:
            self.connect()
        
        self.logger.info(f"Publishing batch of {len(messages)} messages")
        
        success_count = 0
        error_count = 0
        
        for message in messages:
            try:
                self.publish(message, persistent=persistent)
                success_count += 1
            except Exception as e:
                self.logger.error(f"Failed to publish message in batch: {e}")
                error_count += 1
        
        self.logger.info(f"Batch publish complete: {success_count} succeeded, {error_count} failed")
        
        if error_count > 0:
            raise Exception(f"Batch publish had {error_count} failures")
    
    def close(self):
        """Close the connection."""
        if self.connection and self.connection.is_open:
            try:
                self.connection.close()
                self.logger.info("RabbitMQ producer connection closed")
            except Exception as e:
                self.logger.error(f"Error closing connection: {e}")
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
