"""RabbitMQ Consumer for consuming messages from a queue."""

import pika
import pika.exceptions
import json
import time
from typing import Callable, Dict, Any, Optional
import logging
from concurrent.futures import ThreadPoolExecutor, Future
import threading


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
        logger_instance: Optional[logging.Logger] = None,
        max_workers: Optional[int] = None,
        heartbeat: int = 900,
        reconnect_delay: float = 5.0,
        max_reconnect_attempts: int = 0
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
            max_workers: Number of worker threads for concurrent processing. 
                        If None, processes messages synchronously (default behavior).
                        If > 0, uses a ThreadPoolExecutor with this many workers.
            heartbeat: Heartbeat interval in seconds (default: 900). Increase this if
                      processing takes longer to prevent connection timeouts.
            reconnect_delay: Delay in seconds between reconnection attempts (default: 5.0)
            max_reconnect_attempts: Maximum reconnection attempts. 0 = unlimited (default: 0)
        """
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.queue = queue
        self.connection = None
        self.channel = None
        self.logger = logger_instance or logger
        self.max_workers = max_workers
        self.heartbeat = heartbeat
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts
        self.executor = None
        self.active_tasks = {}  # Track active futures by delivery_tag
        self.tasks_lock = threading.Lock()  # Thread-safe access to active_tasks
        self._should_stop = False  # Flag to control reconnection loop
    
    def connect(self):
        """Establish connection to RabbitMQ."""
        credentials = pika.PlainCredentials(self.user, self.password)
        parameters = pika.ConnectionParameters(
            host=self.host,
            port=self.port,
            credentials=credentials,
            heartbeat=self.heartbeat
        )
        
        self.logger.info(f"Connecting to RabbitMQ at {self.host}:{self.port}")
        self.connection = pika.BlockingConnection(parameters)
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=self.queue, durable=True)
        self.logger.info(f"Connected to RabbitMQ, listening on queue: {self.queue}")
        
        # Initialize thread pool if max_workers is set
        if self.max_workers and self.max_workers > 0:
            self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
            self.logger.info(f"Initialized thread pool with {self.max_workers} workers")
    
    def consume(self, callback: Callable[[Dict[str, Any]], bool], prefetch_count: int = 1):
        """
        Consume messages from the queue with automatic reconnection.
        
        Args:
            callback: Function to process each message. Should return True if successful.
                     The function receives a dictionary (parsed JSON) as input.
            prefetch_count: Number of messages to prefetch (default: 1).
                          When using multi-threading, set this higher (e.g., max_workers * 2)
                          to keep workers busy.
        """
        self._should_stop = False
        reconnect_attempts = 0
        
        while not self._should_stop:
            try:
                if not self.channel or not self.channel.is_open:
                    self.connect()
                
                # Reset reconnect counter on successful connection
                reconnect_attempts = 0
                
                if self.executor:
                    # Multi-threaded processing
                    self._consume_threaded(callback, prefetch_count)
                else:
                    # Single-threaded processing (original behavior)
                    self._consume_sync(callback, prefetch_count)
                    
            except KeyboardInterrupt:
                self.logger.info("Received shutdown signal, stopping consumer...")
                self._should_stop = True
                break
                
            except (pika.exceptions.AMQPConnectionError,
                    pika.exceptions.AMQPChannelError,
                    pika.exceptions.StreamLostError,
                    pika.exceptions.ConnectionClosedByBroker,
                    pika.exceptions.ChannelClosedByBroker) as e:
                
                if self._should_stop:
                    break
                    
                reconnect_attempts += 1
                
                if self.max_reconnect_attempts > 0 and reconnect_attempts > self.max_reconnect_attempts:
                    self.logger.error(f"Max reconnection attempts ({self.max_reconnect_attempts}) exceeded. Giving up.")
                    raise
                
                self.logger.warning(f"Connection lost: {e}. Reconnecting in {self.reconnect_delay}s (attempt {reconnect_attempts})...")
                
                # Clean up old connection
                self._cleanup_connection()
                
                time.sleep(self.reconnect_delay)
                
            except Exception as e:
                if self._should_stop:
                    break
                self.logger.error(f"Unexpected error in consumer: {e}", exc_info=True)
                raise
        
        self.stop()
    
    def _cleanup_connection(self):
        """Clean up existing connection resources."""
        try:
            if self.channel and self.channel.is_open:
                self.channel.close()
        except Exception as e:
            self.logger.debug(f"Error closing channel during cleanup: {e}")
        
        try:
            if self.connection and self.connection.is_open:
                self.connection.close()
        except Exception as e:
            self.logger.debug(f"Error closing connection during cleanup: {e}")
        
        self.channel = None
        self.connection = None
    
    def _consume_sync(self, callback: Callable[[Dict[str, Any]], bool], prefetch_count: int):
        """Synchronous message consumption (original behavior)."""
        def on_message(ch, method, properties, body):
            try:
                # Deserialize JSON message
                message = json.loads(body)
                # Extract message identifier from nested resource_data/event_data or top-level fields
                resource_data = message.get('resource_data', {})
                event_data = message.get('event_data', {})
                msg_id = (
                    resource_data.get('title') or 
                    event_data.get('name') or 
                    message.get('title', message.get('id', 'Unknown'))
                )
                self.logger.info(f"Received message: {msg_id}")
                
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
            except (pika.exceptions.AMQPConnectionError,
                    pika.exceptions.AMQPChannelError,
                    pika.exceptions.StreamLostError,
                    pika.exceptions.ConnectionClosedByBroker,
                    pika.exceptions.ChannelClosedByBroker) as e:
                # Connection errors - re-raise to trigger reconnection in outer loop
                self.logger.error(f"Connection error during message handling: {e}")
                raise
            except Exception as e:
                self.logger.error(f"Error processing message: {e}", exc_info=True)
                # Try to requeue, but if connection is dead this will fail
                try:
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                except Exception:
                    self.logger.warning("Could not NACK message - connection may be dead")
                    raise
        
        # Set QoS
        self.channel.basic_qos(prefetch_count=prefetch_count)
        self.channel.basic_consume(queue=self.queue, on_message_callback=on_message)
        
        self.logger.info(f"Starting to consume messages from queue: {self.queue}")
        self.channel.start_consuming()
    
    def _consume_threaded(self, callback: Callable[[Dict[str, Any]], bool], prefetch_count: int):
        """Multi-threaded message consumption using ThreadPoolExecutor."""
        def on_message(ch, method, properties, body):
            try:
                # Deserialize JSON message
                message = json.loads(body)
                # Extract message identifier from nested resource_data/event_data or top-level fields
                resource_data = message.get('resource_data', {})
                event_data = message.get('event_data', {})
                msg_id = (
                    resource_data.get('title') or 
                    event_data.get('name') or 
                    message.get('title', message.get('id', 'Unknown'))
                )
                self.logger.info(f"Received message: {msg_id}")
                
                # Submit to thread pool for processing
                future = self.executor.submit(self._process_message_threaded, message, callback)
                
                # Store the future with its delivery tag
                with self.tasks_lock:
                    self.active_tasks[method.delivery_tag] = future
                
                # Add callback to handle completion
                future.add_done_callback(
                    lambda f, tag=method.delivery_tag, channel=ch: 
                    self._handle_message_completion(f, tag, channel)
                )
                
            except json.JSONDecodeError as e:
                self.logger.error(f"Failed to decode message as JSON: {e}")
                # Acknowledge to remove invalid message from queue
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except (pika.exceptions.AMQPConnectionError,
                    pika.exceptions.AMQPChannelError,
                    pika.exceptions.StreamLostError,
                    pika.exceptions.ConnectionClosedByBroker,
                    pika.exceptions.ChannelClosedByBroker) as e:
                # Connection errors - re-raise to trigger reconnection in outer loop
                self.logger.error(f"Connection error during message handling: {e}")
                raise
            except Exception as e:
                self.logger.error(f"Error submitting message to thread pool: {e}", exc_info=True)
                # Try to requeue, but if connection is dead this will fail
                try:
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                except Exception:
                    self.logger.warning("Could not NACK message - connection may be dead")
                    raise
        
        # Set QoS - important for threaded processing
        self.channel.basic_qos(prefetch_count=prefetch_count)
        self.channel.basic_consume(queue=self.queue, on_message_callback=on_message, auto_ack=False)
        
        self.logger.info(f"Starting to consume messages from queue: {self.queue} with {self.max_workers} worker threads")
        self.channel.start_consuming()
    
    def _process_message_threaded(self, message: Dict[str, Any], callback: Callable[[Dict[str, Any]], bool]) -> bool:
        """
        Process a message in a worker thread.
        
        Args:
            message: The message to process
            callback: The callback function to process the message
            
        Returns:
            True if successful, False otherwise
        """
        try:
            success = callback(message)
            return success
        except Exception as e:
            self.logger.error(f"Error in worker thread processing message: {e}", exc_info=True)
            return False
    
    def _handle_message_completion(self, future: Future, delivery_tag: int, channel):
        """
        Handle completion of a message processing task.
        
        Args:
            future: The completed Future object
            delivery_tag: The delivery tag for acknowledgment
            channel: The channel to send ack/nack
        """
        try:
            # Get the result (this will raise if the future had an exception)
            success = future.result()
            
            # Use connection.add_callback_threadsafe to ensure thread-safe ack/nack
            if success:
                self.connection.add_callback_threadsafe(
                    lambda: channel.basic_ack(delivery_tag=delivery_tag)
                )
                self.logger.info(f"Message {delivery_tag} processed successfully")
            else:
                self.connection.add_callback_threadsafe(
                    lambda: channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
                )
                self.logger.warning(f"Message {delivery_tag} processing failed, requeued")
                
        except Exception as e:
            self.logger.error(f"Error in message completion handler: {e}", exc_info=True)
            # Requeue on error
            self.connection.add_callback_threadsafe(
                lambda: channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
            )
        finally:
            # Remove from active tasks
            with self.tasks_lock:
                self.active_tasks.pop(delivery_tag, None)
    
    def stop(self):
        """Stop consuming and close the connection."""
        self._should_stop = True
        
        if self.channel and self.channel.is_open:
            try:
                self.channel.stop_consuming()
            except Exception as e:
                self.logger.error(f"Error stopping consumer: {e}")
        
        # Shutdown thread pool if it exists
        if self.executor:
            self.logger.info("Shutting down thread pool...")
            try:
                # Wait for active tasks to complete (with timeout)
                self.executor.shutdown(wait=True, cancel_futures=False)
                self.logger.info("Thread pool shut down successfully")
            except Exception as e:
                self.logger.error(f"Error shutting down thread pool: {e}")
        
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
