"""RabbitMQ Consumer for consuming messages from a queue."""

import pika
import json
from typing import Callable, Dict, Any, Optional
import logging


logger = logging.getLogger(__name__)


class RabbitMQConsumer:
    """Client for consuming messages from RabbitMQ."""
    
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
        Initialize RabbitMQ Consumer.
        
        Args:
            host: RabbitMQ host
            port: RabbitMQ port (default: 5672)
            user: RabbitMQ username
            password: RabbitMQ password
            queue: Queue name to consume from
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
        self.logger.info(f"Connected to RabbitMQ, listening on queue: {self.queue}")
    
    def consume(self, callback: Callable[[Dict[str, Any]], bool], prefetch_count: int = 1):
        """
        Consume messages from the queue.
        
        Args:
            callback: Function to process each message. Should return True if successful.
                     The function receives a dictionary (parsed JSON) as input.
            prefetch_count: Number of messages to prefetch (default: 1)
        """
        if not self.channel:
            self.connect()
        
        def on_message(ch, method, properties, body):
            try:
                # Deserialize JSON message
                message = json.loads(body)
                self.logger.info(f"Received message: {message.get('title', message.get('id', 'Unknown'))}")
                
                # Process message with callback
                success = callback(message)
                
                if success:
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    self.logger.info("Message processed successfully")
                else:
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                    self.logger.warning("Message processing failed, requeued")
                    
            except json.JSONDecodeError as e:
                self.logger.error(f"Failed to decode message as JSON: {e}")
                # Acknowledge to remove invalid message from queue
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                self.logger.error(f"Error processing message: {e}", exc_info=True)
                # Requeue for retry
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        
        # Set QoS
        self.channel.basic_qos(prefetch_count=prefetch_count)
        self.channel.basic_consume(queue=self.queue, on_message_callback=on_message)
        
        self.logger.info(f"Starting to consume messages from queue: {self.queue}")
        try:
            self.channel.start_consuming()
        except KeyboardInterrupt:
            self.logger.info("Received shutdown signal, stopping consumer...")
            self.stop()
    
    def stop(self):
        """Stop consuming and close the connection."""
        if self.channel and self.channel.is_open:
            try:
                self.channel.stop_consuming()
            except Exception as e:
                self.logger.error(f"Error stopping consumer: {e}")
        
        if self.connection and self.connection.is_open:
            try:
                self.connection.close()
            except Exception as e:
                self.logger.error(f"Error closing connection: {e}")
        
        self.logger.info("RabbitMQ consumer connection closed")
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
