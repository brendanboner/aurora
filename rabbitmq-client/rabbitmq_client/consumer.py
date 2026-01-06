"""RabbitMQ Consumer for consuming messages from a queue."""

import pika
import pika.exceptions
import json
import time
from typing import Callable, Dict, Any, Optional
import logging
from concurrent.futures import ThreadPoolExecutor, Future
import threading
from datetime import datetime
import hashlib

# Import instrumentation from common
import sys
import os
# Add parent directory to path to import from common
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
try:
    from common.rabbitmq_instrumentation import extract_trace_context
    from common.telemetry import get_tracer
    from opentelemetry.context import detach
    INSTRUMENTATION_AVAILABLE = True
except ImportError:
    INSTRUMENTATION_AVAILABLE = False
    def extract_trace_context(properties):
        return None
    def get_tracer():
        return None
    def detach(token):
        pass


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
            heartbeat: Heartbeat interval in seconds (default: 900 = 15 minutes).
                      RabbitMQ will close the connection if no heartbeat is received 
                      within 2x this interval (e.g., 900s heartbeat = 30 min timeout).
                      Note: BlockingConnection has limitations with heartbeats during
                      long callbacks. Consider increasing this significantly if processing
                      takes more than a few minutes.
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
        
        # Enhanced logging state
        self.connection_start_time = None  # Track when connection was established
        self.message_start_times = {}  # Track when each message started processing
        self.message_hashes = {}  # Track message content hashes to detect redeliveries
        self.redelivery_counts = {}  # Count redeliveries per message hash
        self.total_messages_processed = 0
        self.total_messages_failed = 0

        # Initialize thread pool if max_workers is set
        if self.max_workers and self.max_workers > 0:
            self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
            self.logger.info(f"Initialized thread pool with {self.max_workers} workers")
            self.logger.info(f"⚙️  Configuration: heartbeat={self.heartbeat}s (timeout after {self.heartbeat*2}s)")
    
    def connect(self):
        """Establish connection to RabbitMQ."""
        credentials = pika.PlainCredentials(self.user, self.password)
        parameters = pika.ConnectionParameters(
            host=self.host,
            port=self.port,
            credentials=credentials,
            heartbeat=self.heartbeat,
            blocked_connection_timeout=300  # 5 minutes before timing out blocked connection
        )
        
        self.logger.info(f"🔌 Connecting to RabbitMQ at {self.host}:{self.port} (heartbeat={self.heartbeat}s)")
        self.connection = pika.BlockingConnection(parameters)
        self.connection_start_time = time.time()
        
        # Add blocked connection callbacks to detect when server blocks the connection
        self.connection.add_on_connection_blocked_callback(self._on_connection_blocked)
        self.connection.add_on_connection_unblocked_callback(self._on_connection_unblocked)
        
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=self.queue, durable=True)
        self.logger.info(f"✅ Connected to RabbitMQ, listening on queue: {self.queue}")

    def _ensure_channel(self):
        """
        Ensure the connection and channel are open. Reconnect if needed.
        """
        if not self.connection or not self.connection.is_open:
            self.logger.warning("⚠️  Connection was closed, reconnecting...")
            
            # Clean up stale task tracking from previous connection
            if self.active_tasks:
                stale_count = len(self.active_tasks)
                self.logger.warning(
                    f"🧹 Clearing {stale_count} stale task(s) from previous connection. "
                    f"These messages will be automatically requeued by RabbitMQ."
                )
                with self.tasks_lock:
                    self.active_tasks.clear()
                self.message_start_times.clear()
                self.message_hashes.clear()
            
            self.connect()
        elif not self.channel or not self.channel.is_open:
            self.logger.warning("⚠️  Channel was closed, recreating channel...")
            self.channel = self.connection.channel()
            self.channel.queue_declare(queue=self.queue, durable=True)

    
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
                self._ensure_channel()
                
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
                
                # Calculate connection lifetime
                connection_duration = 0
                if self.connection_start_time:
                    connection_duration = time.time() - self.connection_start_time
                
                reconnect_attempts += 1
                
                if self.max_reconnect_attempts > 0 and reconnect_attempts > self.max_reconnect_attempts:
                    self.logger.error(f"❌ Max reconnection attempts ({self.max_reconnect_attempts}) exceeded. Giving up.")
                    raise
                
                # Enhanced logging with connection details
                self.logger.error(
                    f"💔 Connection lost after {connection_duration:.1f}s: {type(e).__name__}: {e}\n"
                    f"   Heartbeat timeout threshold: {self.heartbeat * 2}s\n"
                    f"   Active tasks: {len(self.active_tasks)}\n"
                    f"   Total processed: {self.total_messages_processed}, failed: {self.total_messages_failed}\n"
                    f"   Reconnecting in {self.reconnect_delay}s (attempt {reconnect_attempts})..."
                )
                
                # Log any in-flight messages
                if self.active_tasks:
                    self.logger.warning(f"⚠️  {len(self.active_tasks)} messages were in-flight and will be requeued by RabbitMQ")
                
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
        connection_lifetime = 0
        if self.connection_start_time:
            connection_lifetime = time.time() - self.connection_start_time
            self.logger.info(f"🔌 Cleaning up connection (lived {connection_lifetime:.1f}s)")
        
        try:
            if self.channel and self.channel.is_open:
                self.channel.close()
                self.logger.debug("Channel closed")
        except Exception as e:
            self.logger.debug(f"Error closing channel during cleanup: {e}")
        
        try:
            if self.connection and self.connection.is_open:
                self.connection.close()
                self.logger.debug("Connection closed")
        except Exception as e:
            self.logger.debug(f"Error closing connection during cleanup: {e}")
        
        self.channel = None
        self.connection = None
        self.connection_start_time = None
    
    def _on_connection_blocked(self, method_frame):
        """Callback when RabbitMQ server blocks the connection due to resource constraints."""
        self.logger.error(f"🚫 RabbitMQ connection BLOCKED by server: {method_frame.method.reason}")
        self.logger.error(f"   This means the server is under resource pressure (memory/disk)")
        self.logger.error(f"   Processing may be slower until server resources free up")
    
    def _on_connection_unblocked(self, method_frame):
        """Callback when RabbitMQ server unblocks the connection."""
        self.logger.warning("✅ RabbitMQ connection UNBLOCKED by server - normal operation resumed")
    
    def _consume_sync(self, callback: Callable[[Dict[str, Any]], bool], prefetch_count: int):
        """Synchronous message consumption (original behavior)."""
        def on_message(ch, method, properties, body):
            start_time = time.time()
            delivery_tag = method.delivery_tag
            
            tracer = get_tracer() if INSTRUMENTATION_AVAILABLE else None
            token = None
            span_context = None
            
            # Extract trace context from message properties
            if INSTRUMENTATION_AVAILABLE and properties:
                props_dict = {
                    'headers': properties.headers if properties.headers else {}
                }
                token = extract_trace_context(props_dict)
            
            # Create span for message processing
            if tracer:
                span_context = tracer.start_as_current_span(
                    "rabbitmq.process",
                    attributes={
                        "messaging.system": "rabbitmq",
                        "messaging.source": self.queue,
                        "messaging.operation": "process",
                    }
                )
                span_context.__enter__()
            
            try:
                # Deserialize JSON message
                message = json.loads(body)
                
                # Extract message identifier and create hash for tracking redeliveries
                resource_data = message.get('resource_data', {})
                event_data = message.get('event_data', {})
                msg_id = (
                    resource_data.get('title') or 
                    event_data.get('name') or 
                    message.get('title', message.get('id', 'Unknown'))
                )
                
                # Create a hash of the message to detect redeliveries
                msg_hash = hashlib.md5(json.dumps(message, sort_keys=True).encode()).hexdigest()[:8]
                
                # Track redeliveries
                redelivered = method.redelivered
                if msg_hash in self.redelivery_counts:
                    self.redelivery_counts[msg_hash] += 1
                    self.logger.warning(
                        f"🔄 REDELIVERY DETECTED for '{msg_id}' (hash:{msg_hash}, count:{self.redelivery_counts[msg_hash]})"
                    )
                else:
                    self.redelivery_counts[msg_hash] = 1
                
                # Log connection health
                connection_age = time.time() - self.connection_start_time if self.connection_start_time else 0
                timeout_threshold = self.heartbeat * 2
                time_until_timeout = timeout_threshold - connection_age
                
                self.logger.info(
                    f"📨 Received message [{delivery_tag}]: '{msg_id}' "
                    f"(hash:{msg_hash}, redelivered:{redelivered})"
                )
                self.logger.debug(
                    f"   Connection age: {connection_age:.1f}s / {timeout_threshold}s "
                    f"(timeout in {time_until_timeout:.1f}s)"
                )
                
                # Track message start time
                self.message_start_times[delivery_tag] = start_time
                
                # Process message with callback
                self.logger.info(f"⚙️  Processing message [{delivery_tag}]...")
                success = callback(message)
                
                processing_duration = time.time() - start_time
                
                self._ensure_channel()
                if success:
                    ch.basic_ack(delivery_tag=delivery_tag)
                    self.total_messages_processed += 1
                    self.logger.info(
                        f"✅ Message [{delivery_tag}] processed successfully in {processing_duration:.1f}s "
                        f"(total: {self.total_messages_processed})"
                    )
                    # Clean up redelivery tracking on success
                    self.redelivery_counts.pop(msg_hash, None)
                else:
                    ch.basic_nack(delivery_tag=delivery_tag, requeue=True)
                    self.total_messages_failed += 1
                    self.logger.warning(
                        f"❌ Message [{delivery_tag}] processing failed after {processing_duration:.1f}s, "
                        f"requeued (total failed: {self.total_messages_failed})"
                    )
                
                # Clean up tracking
                self.message_start_times.pop(delivery_tag, None)
                    
            except json.JSONDecodeError as e:
                self.logger.error(f"❌ Failed to decode message [{delivery_tag}] as JSON: {e}")
                # Acknowledge to remove invalid message from queue
                self._ensure_channel()
                ch.basic_ack(delivery_tag=delivery_tag)
                self.message_start_times.pop(delivery_tag, None)
                if span_context:
                    span_context.__exit__(type(e), e, e.__traceback__)
            except (pika.exceptions.AMQPConnectionError,
                    pika.exceptions.AMQPChannelError,
                    pika.exceptions.StreamLostError,
                    pika.exceptions.ConnectionClosedByBroker,
                    pika.exceptions.ChannelClosedByBroker) as e:
                # Connection errors - re-raise to trigger reconnection in outer loop
                processing_duration = time.time() - start_time
                self.logger.error(
                    f"💔 Connection error during message [{delivery_tag}] handling after {processing_duration:.1f}s: {e}"
                )
                self.logger.error(f"   Message will be automatically requeued by RabbitMQ")
                # Message will be automatically requeued by RabbitMQ since it wasn't ACKed
                if span_context:
                    span_context.__exit__(type(e), e, e.__traceback__)
                raise
            except Exception as e:
                processing_duration = time.time() - start_time
                self.logger.error(
                    f"❌ Error processing message [{delivery_tag}] after {processing_duration:.1f}s: {e}",
                    exc_info=True
                )
                # Try to requeue, but if connection is dead this will fail and raise
                try:
                    self._ensure_channel()
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                    self.logger.info(f"🔄 Message [{delivery_tag}] requeued after error")
                except Exception as nack_error:
                    self.logger.warning(f"⚠️  Could not NACK message [{delivery_tag}] - connection may be dead: {nack_error}")
                    # Message will be automatically requeued by RabbitMQ
                    if span_context:
                        span_context.__exit__(type(e), e, e.__traceback__)
                    raise
                finally:
                    self.message_start_times.pop(delivery_tag, None)
                if span_context:
                    span_context.__exit__(type(e), e, e.__traceback__)
            finally:
                # Clean up span and trace context
                if span_context:
                    try:
                        span_context.__exit__(None, None, None)
                    except:
                        pass
                if token and INSTRUMENTATION_AVAILABLE:
                    try:
                        detach(token)
                    except:
                        pass
        
        # Set QoS
        self.channel.basic_qos(prefetch_count=prefetch_count)
        # Explicitly set auto_ack=False for manual acknowledgment
        self.channel.basic_consume(queue=self.queue, on_message_callback=on_message, auto_ack=False)
        
        self.logger.info(f"🚀 Starting to consume messages from queue: {self.queue} (sync mode, prefetch={prefetch_count})")
        self.channel.start_consuming()
    
    def _consume_threaded(self, callback: Callable[[Dict[str, Any]], bool], prefetch_count: int):
        """Multi-threaded message consumption using ThreadPoolExecutor."""
        def on_message(ch, method, properties, body):
            start_time = time.time()
            delivery_tag = method.delivery_tag
            
            try:
                # Deserialize JSON message
                message = json.loads(body)
                
                # Extract message identifier and create hash for tracking redeliveries
                resource_data = message.get('resource_data', {})
                event_data = message.get('event_data', {})
                msg_id = (
                    resource_data.get('title') or 
                    event_data.get('name') or 
                    message.get('title', message.get('id', 'Unknown'))
                )
                
                # Create a hash of the message to detect redeliveries
                msg_hash = hashlib.md5(json.dumps(message, sort_keys=True).encode()).hexdigest()[:8]
                
                # Track redeliveries
                redelivered = method.redelivered
                if msg_hash in self.redelivery_counts:
                    self.redelivery_counts[msg_hash] += 1
                    self.logger.warning(
                        f"🔄 REDELIVERY DETECTED for '{msg_id}' (hash:{msg_hash}, count:{self.redelivery_counts[msg_hash]})"
                    )
                else:
                    self.redelivery_counts[msg_hash] = 1
                
                # Log connection health
                connection_age = time.time() - self.connection_start_time if self.connection_start_time else 0
                timeout_threshold = self.heartbeat * 2
                time_until_timeout = timeout_threshold - connection_age
                
                # Track message start time
                self.message_start_times[delivery_tag] = start_time
                self.message_hashes[delivery_tag] = msg_hash
                
                # Submit to thread pool for processing
                self.logger.info(f"⚙️  Submitting message [{delivery_tag}] to worker thread...")
                future = self.executor.submit(self._process_message_threaded, message, callback, delivery_tag, msg_id, start_time)
                
                # Store the future with its delivery tag and get accurate active count
                with self.tasks_lock:
                    self.active_tasks[method.delivery_tag] = future
                    active_count = len(self.active_tasks)
                
                # Log after adding task to get accurate count
                self.logger.info(
                    f"📨 Received message [{delivery_tag}]: '{msg_id}' "
                    f"(hash:{msg_hash}, redelivered:{redelivered}, active_tasks:{active_count}/{self.max_workers})"
                )
                self.logger.debug(
                    f"   Connection age: {connection_age:.1f}s / {timeout_threshold}s "
                    f"(timeout in {time_until_timeout:.1f}s)"
                )
                
                # Add callback to handle completion
                future.add_done_callback(
                    lambda f, tag=method.delivery_tag, channel=ch: 
                    self._handle_message_completion(f, tag, channel)
                )
                
            except json.JSONDecodeError as e:
                self.logger.error(f"❌ Failed to decode message [{delivery_tag}] as JSON: {e}")
                # Acknowledge to remove invalid message from queue
                try:
                    self._ensure_channel()
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as ack_error:
                    self.logger.warning(f"⚠️  Could not ACK invalid message [{delivery_tag}]: {ack_error}")
            except (pika.exceptions.AMQPConnectionError,
                    pika.exceptions.AMQPChannelError,
                    pika.exceptions.StreamLostError,
                    pika.exceptions.ConnectionClosedByBroker,
                    pika.exceptions.ChannelClosedByBroker) as e:
                # Connection errors - re-raise to trigger reconnection in outer loop
                processing_duration = time.time() - start_time
                self.logger.error(
                    f"💔 Connection error during message [{delivery_tag}] submission after {processing_duration:.1f}s: {e}"
                )
                self.logger.error(f"   Message will be automatically requeued by RabbitMQ")
                # Message will be automatically requeued by RabbitMQ
                raise
            except Exception as e:
                processing_duration = time.time() - start_time
                self.logger.error(
                    f"❌ Error submitting message [{delivery_tag}] to thread pool after {processing_duration:.1f}s: {e}",
                    exc_info=True
                )
                # Try to requeue, but if connection is dead this will fail and raise
                try:
                    self._ensure_channel()
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                    self.logger.info(f"🔄 Message [{delivery_tag}] requeued after submission error")
                except Exception as nack_error:
                    self.logger.warning(f"⚠️  Could not NACK message [{delivery_tag}] - connection may be dead: {nack_error}")
                    # Message will be automatically requeued by RabbitMQ
                    raise
        
        # Set QoS - important for threaded processing
        self.channel.basic_qos(prefetch_count=prefetch_count)
        # Explicitly set auto_ack=False for manual acknowledgment
        self.channel.basic_consume(queue=self.queue, on_message_callback=on_message, auto_ack=False)
        
        self.logger.info(
            f"🚀 Starting to consume messages from queue: {self.queue} "
            f"(threaded mode: {self.max_workers} workers, prefetch={prefetch_count})"
        )
        self.channel.start_consuming()
    
    def _process_message_threaded(self, message: Dict[str, Any], callback: Callable[[Dict[str, Any]], bool], 
                                   delivery_tag: int, msg_id: str, start_time: float) -> bool:
        """
        Process a message in a worker thread.
        
        Args:
            message: The message to process
            callback: The callback function to process the message
            delivery_tag: Delivery tag for logging
            msg_id: Message identifier for logging
            start_time: When processing started
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.logger.info(f"🔧 Worker thread processing message [{delivery_tag}]: '{msg_id}'")
            success = callback(message)
            
            processing_duration = time.time() - start_time
            if success:
                self.logger.info(f"✅ Worker completed message [{delivery_tag}] successfully in {processing_duration:.1f}s")
            else:
                self.logger.warning(f"❌ Worker failed message [{delivery_tag}] after {processing_duration:.1f}s")
            
            return success
        except Exception as e:
            processing_duration = time.time() - start_time
            self.logger.error(
                f"❌ Exception in worker thread processing message [{delivery_tag}] after {processing_duration:.1f}s: {e}",
                exc_info=True
            )
            return False
    
    def _handle_message_completion(self, future: Future, delivery_tag: int, channel):
        """
        Handle completion of a message processing task.
        
        Args:
            future: The completed Future object
            delivery_tag: The delivery tag for acknowledgment
            channel: The channel to send ack/nack
            
        Note: This runs in a worker thread. We must NOT call _ensure_channel() here
        as it would create a new connection that conflicts with other threads.
        If the connection is dead, we simply log and return - RabbitMQ will
        automatically requeue the unacknowledged message.
        """
        # Get message hash for redelivery tracking
        msg_hash = self.message_hashes.get(delivery_tag, "unknown")
        start_time = self.message_start_times.get(delivery_tag, time.time())
        total_duration = time.time() - start_time
        
        try:
            # Get the result (this will raise if the future had an exception)
            success = future.result()

            # Check if connection is still alive - do NOT recreate it
            if not self.connection or not self.connection.is_open:
                self.logger.warning(
                    f"⚠️  Connection closed during message [{delivery_tag}] processing ({total_duration:.1f}s). "
                    f"Message will be automatically requeued by RabbitMQ. "
                    f"Main consumer loop will handle reconnection."
                )
                return
            
            # Use connection.add_callback_threadsafe to ensure thread-safe ack/nack
            if success:
                self.connection.add_callback_threadsafe(
                    lambda: channel.basic_ack(delivery_tag=delivery_tag)
                )
                self.total_messages_processed += 1
                self.logger.info(
                    f"✅ Message [{delivery_tag}] ACKed after {total_duration:.1f}s "
                    f"(total: {self.total_messages_processed})"
                )
                # Clean up redelivery tracking on success
                self.redelivery_counts.pop(msg_hash, None)
            else:
                self.connection.add_callback_threadsafe(
                    lambda: channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
                )
                self.total_messages_failed += 1
                self.logger.warning(
                    f"❌ Message [{delivery_tag}] NACKed and requeued after {total_duration:.1f}s "
                    f"(total failed: {self.total_messages_failed})"
                )
                
        except Exception as e:
            self.logger.error(f"❌ Error in message completion handler for [{delivery_tag}]: {e}", exc_info=True)
            # Do NOT try to reconnect from worker thread - just log and let RabbitMQ requeue
            self.logger.warning(
                f"⚠️  Cannot ACK/NACK message [{delivery_tag}] due to error. "
                f"Message will be automatically requeued by RabbitMQ."
            )
        finally:
            # Remove from active tasks and clean up tracking
            with self.tasks_lock:
                self.active_tasks.pop(delivery_tag, None)
                active_count = len(self.active_tasks)
            
            self.message_start_times.pop(delivery_tag, None)
            self.message_hashes.pop(delivery_tag, None)
            
            self.logger.debug(f"   Active tasks now: {active_count}/{self.max_workers}")
    
    def stop(self):
        """Stop consuming and close the connection."""
        self._should_stop = True
        
        # Log final statistics
        connection_lifetime = 0
        if self.connection_start_time:
            connection_lifetime = time.time() - self.connection_start_time
        
        self.logger.info("🛑 Stopping RabbitMQ consumer...")
        self.logger.info(f"📊 Final Statistics:")
        self.logger.info(f"   Total messages processed: {self.total_messages_processed}")
        self.logger.info(f"   Total messages failed: {self.total_messages_failed}")
        self.logger.info(f"   Connection lifetime: {connection_lifetime:.1f}s")
        self.logger.info(f"   Active tasks at shutdown: {len(self.active_tasks)}")
        
        if self.active_tasks:
            self.logger.warning(f"⚠️  {len(self.active_tasks)} messages still processing at shutdown")
        
        if self.channel and self.channel.is_open:
            try:
                self.channel.stop_consuming()
                self.logger.info("Stopped consuming messages")
            except Exception as e:
                self.logger.error(f"Error stopping consumer: {e}")
        
        # Shutdown thread pool if it exists
        if self.executor:
            self.logger.info("Shutting down thread pool...")
            try:
                # Wait for active tasks to complete (with timeout)
                self.executor.shutdown(wait=True, cancel_futures=False)
                self.logger.info("✅ Thread pool shut down successfully")
            except Exception as e:
                self.logger.error(f"Error shutting down thread pool: {e}")
        
        if self.connection and self.connection.is_open:
            try:
                self.connection.close()
                self.logger.info("Connection closed")
            except Exception as e:
                self.logger.error(f"Error closing connection: {e}")
        
        self.logger.info("✅ RabbitMQ consumer stopped")
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
