"""RabbitMQ Producer for publishing messages to a queue."""

import pika
import json
import time
from typing import Dict, Any, List, Optional
import logging

# Import instrumentation from common
import sys
import os
# Add parent directory to path to import from common
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
try:
    from common.rabbitmq_instrumentation import inject_trace_context
    from common.telemetry import get_tracer
    INSTRUMENTATION_AVAILABLE = True
except ImportError:
    INSTRUMENTATION_AVAILABLE = False
    def inject_trace_context(properties):
        return properties
    def get_tracer():
        return None


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
    
    def connect(self, max_retries: int = 5, retry_delay: float = 2.0):
        """
        Establish connection to RabbitMQ with retry logic.
        
        Args:
            max_retries: Maximum number of connection attempts (default: 5)
            retry_delay: Initial delay between retries in seconds (default: 2.0)
        """
        credentials = pika.PlainCredentials(self.user, self.password)
        parameters = pika.ConnectionParameters(
            host=self.host,
            port=self.port,
            credentials=credentials
        )
        
        last_exception = None
        for attempt in range(1, max_retries + 1):
            try:
                self.logger.info(f"Connecting to RabbitMQ at {self.host}:{self.port} (attempt {attempt}/{max_retries})")
                self.connection = pika.BlockingConnection(parameters)
                self.channel = self.connection.channel()
                self.channel.queue_declare(queue=self.queue, durable=True)
                self.logger.info(f"Connected to RabbitMQ, publishing to queue: {self.queue}")
                return  # Success, exit function
            except Exception as e:
                last_exception = e
                if attempt < max_retries:
                    wait_time = retry_delay * (2 ** (attempt - 1))  # Exponential backoff
                    self.logger.warning(f"Failed to connect to RabbitMQ (attempt {attempt}/{max_retries}): {e}")
                    self.logger.info(f"Retrying in {wait_time:.1f} seconds...")
                    time.sleep(wait_time)
                else:
                    self.logger.error(f"Failed to connect to RabbitMQ after {max_retries} attempts: {e}")
        
        # If we get here, all retries failed
        raise last_exception
    
    def _ensure_connected(self):
        """Ensure connection and channel are open, reconnecting if necessary."""
        if not self.channel or not self.channel.is_open:
            if self.connection and self.connection.is_open:
                try:
                    self.connection.close()
                except Exception as e:
                    self.logger.debug(f"Error closing stale connection: {e}")
            self.logger.info("Channel is closed, reconnecting...")
            self.connect()

    def publish(self, message: Dict[str, Any], persistent: bool = True):
        """
        Publish a message to the queue.
        
        Args:
            message: Dictionary to publish (will be JSON serialized)
            persistent: If True, message survives broker restart (default: True)
        """
        self._ensure_connected()
        
        tracer = get_tracer() if INSTRUMENTATION_AVAILABLE else None
        
        # Create span for message publish
        span_context = None
        if tracer:
            span_context = tracer.start_as_current_span(
                "rabbitmq.publish",
                attributes={
                    "messaging.system": "rabbitmq",
                    "messaging.destination": self.queue,
                    "messaging.operation": "publish",
                }
            )
            span_context.__enter__()
        
        try:
            # Serialize to JSON
            body = json.dumps(message)
            
            # Set message properties
            properties_dict = {
                'delivery_mode': 2 if persistent else 1,  # 2 = persistent
                'headers': {}
            }
            
            # Inject trace context into headers
            if INSTRUMENTATION_AVAILABLE:
                properties_dict = inject_trace_context(properties_dict)
            
            properties = pika.BasicProperties(
                delivery_mode=properties_dict['delivery_mode'],
                headers=properties_dict.get('headers', {})
            )
            
            # Publish
            self.channel.basic_publish(
                exchange='',
                routing_key=self.queue,
                body=body,
                properties=properties
            )
            
            # Extract message identifier from nested resource_data/event_data or top-level fields
            resource_data = message.get('resource_data', {})
            event_data = message.get('event_data', {})
            msg_id = (
                resource_data.get('title') or 
                event_data.get('name') or 
                message.get('title', message.get('id', message.get('url', 'Unknown')))
            )
            self.logger.info(f"Published message: {msg_id}")
            
        except (TypeError, ValueError) as e:
            self.logger.error(f"Failed to serialize message: {e}")
            if span_context:
                span_context.__exit__(type(e), e, e.__traceback__)
            raise
        except Exception as e:
            self.logger.error(f"Failed to publish message: {e}", exc_info=True)
            if span_context:
                span_context.__exit__(type(e), e, e.__traceback__)
            raise
        finally:
            if span_context:
                try:
                    span_context.__exit__(None, None, None)
                except:
                    pass
    
    def publish_batch(self, messages: List[Dict[str, Any]], persistent: bool = True):
        """
        Publish multiple messages to the queue.
        
        Args:
            messages: List of dictionaries to publish
            persistent: If True, messages survive broker restart (default: True)
        """
        self._ensure_connected()
        
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
