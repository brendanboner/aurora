"""Async RabbitMQ Consumer using aio-pika for consuming messages from a queue.

This consumer addresses critical issues with the previous BlockingConnection implementation:
- Proper heartbeat handling during long-running message processing
- Per-message timeout to prevent infinite processing
- Automatic DLQ routing for failed/timeout messages
- Semaphore-based concurrency control
- Graceful shutdown handling

FAULT TOLERANCE & RECOVERY:
- Connection failures: Automatic reconnection via connect_robust()
- Channel failures: Automatic recreation in consumer loop
- Long processing: Heartbeats continue during async I/O, no timeout
- Message safety: Unacknowledged messages automatically requeued by RabbitMQ
- Infinite retry: Consumer loop never dies unless explicitly stopped
- DLQ resilience: Channel recreated before DLQ operations if closed

See RECOVERY_BEHAVIOR.md for detailed failure scenarios and recovery patterns.
"""

import asyncio
import aio_pika
from aio_pika import connect_robust, Message, DeliveryMode, ExchangeType
from aio_pika.abc import AbstractIncomingMessage
import json
import time
from typing import Callable, Dict, Any, Optional, Awaitable
import logging
from datetime import datetime
import hashlib


logger = logging.getLogger(__name__)


class AsyncRabbitMQConsumer:
    """Async client for consuming messages from RabbitMQ with proper heartbeat handling."""
    
    def __init__(
        self,
        host: str,
        port: int = 5672,
        user: str = "guest",
        password: str = "guest",
        queue: str = "default_queue",
        dlq_queue: Optional[str] = None,
        logger_instance: Optional[logging.Logger] = None,
        max_concurrent: int = 10,
        message_timeout: float = 1200.0,  # 20 minutes default
        heartbeat: int = 60,
        prefetch_count: int = 20,
        reconnect_delay: float = 5.0
    ):
        """
        Initialize Async RabbitMQ Consumer.
        
        Args:
            host: RabbitMQ host
            port: RabbitMQ port (default: 5672)
            user: RabbitMQ username
            password: RabbitMQ password
            queue: Queue name to consume from
            dlq_queue: Dead Letter Queue name. If None, uses "{queue}-dlq"
            logger_instance: Optional logger instance
            max_concurrent: Maximum concurrent message processing (default: 10)
            message_timeout: Max seconds per message before timeout (default: 1200 = 20 min)
            heartbeat: Heartbeat interval in seconds (default: 60)
            prefetch_count: Number of messages to prefetch (default: 20)
            reconnect_delay: Delay in seconds between reconnection attempts
        """
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.queue = queue
        self.dlq_queue = dlq_queue or f"{queue}-dlq"
        self.logger = logger_instance or logger
        self.max_concurrent = max_concurrent
        self.message_timeout = message_timeout
        self.heartbeat = heartbeat
        self.prefetch_count = prefetch_count
        self.reconnect_delay = reconnect_delay
        
        # Connection state
        self.connection = None
        self.channel = None
        self.queue_obj = None
        self.dlq_channel = None
        self.dlq_exchange = None
        
        # Concurrency control
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
        # Monitoring state
        self.connection_start_time = None
        self.active_tasks = 0
        self.total_messages_processed = 0
        self.total_messages_failed = 0
        self.total_messages_timeout = 0
        self._should_stop = False
        self._active_message_tags = set()
        
        self.logger.info(
            f"⚙️  Async Consumer Configuration:\n"
            f"   Max concurrent: {self.max_concurrent}\n"
            f"   Message timeout: {self.message_timeout}s\n"
            f"   Heartbeat: {self.heartbeat}s\n"
            f"   Prefetch: {self.prefetch_count}"
        )
    
    async def connect(self):
        """Establish connection to RabbitMQ with robust reconnection."""
        connection_url = f"amqp://{self.user}:{self.password}@{self.host}:{self.port}/"
        
        self.logger.info(f"🔌 Connecting to RabbitMQ at {self.host}:{self.port} (async, heartbeat={self.heartbeat}s)")
        
        # Use connect_robust for automatic reconnection
        self.connection = await connect_robust(
            connection_url,
            heartbeat=self.heartbeat,
            client_properties={
                'connection_name': f'async_consumer_{self.queue}'
            }
        )
        
        # Setup connection close callbacks for logging
        self.connection.close_callbacks.add(self._on_connection_closed)
        self.connection.reconnect_callbacks.add(self._on_connection_reconnected)
        
        self.connection_start_time = time.time()
        
        # Create main channel for consuming
        self.channel = await self.connection.channel()
        
        # Setup channel close callback
        self.channel.close_callbacks.add(self._on_channel_closed)
        
        await self.channel.set_qos(prefetch_count=self.prefetch_count)
        
        # Declare main queue
        self.queue_obj = await self.channel.declare_queue(
            self.queue,
            durable=True
        )
        
        # Create DLQ channel and setup
        self.dlq_channel = await self.connection.channel()
        await self._setup_dlq()
        
        self.logger.info(f"✅ Connected to RabbitMQ, listening on queue: {self.queue}")
        self.logger.info(f"   DLQ configured: {self.dlq_queue}")
    
    async def _on_connection_closed(self, connection, exception):
        """Callback when connection is closed."""
        if exception:
            connection_lifetime = 0
            if self.connection_start_time:
                connection_lifetime = time.time() - self.connection_start_time
            
            self.logger.error(
                f"💔 Connection closed unexpectedly after {connection_lifetime:.1f}s: {exception}\n"
                f"   Active tasks: {self.active_tasks}\n"
                f"   In-flight messages will be requeued by RabbitMQ\n"
                f"   connect_robust will automatically reconnect..."
            )
        else:
            self.logger.info("Connection closed normally")
    
    async def _on_connection_reconnected(self, connection):
        """Callback when connection is reconnected."""
        self.logger.info("🔄 Connection reconnected successfully!")
        self.connection_start_time = time.time()
    
    async def _on_channel_closed(self, channel, exception):
        """Callback when channel is closed."""
        if exception:
            self.logger.error(
                f"⚠️  Channel closed unexpectedly: {exception}\n"
                f"   Active tasks: {self.active_tasks}\n"
                f"   Consumer loop will handle reconnection..."
            )
        else:
            self.logger.debug("Channel closed normally")
    
    async def _setup_dlq(self):
        """Setup Dead Letter Queue and exchange."""
        # Declare DLQ
        dlq = await self.dlq_channel.declare_queue(
            self.dlq_queue,
            durable=True
        )
        
        # Create a direct exchange for DLQ
        self.dlq_exchange = await self.dlq_channel.declare_exchange(
            f"{self.dlq_queue}_exchange",
            ExchangeType.DIRECT,
            durable=True
        )
        
        # Bind DLQ to exchange
        await dlq.bind(self.dlq_exchange, routing_key=self.dlq_queue)
        
        self.logger.debug(f"DLQ setup complete: {self.dlq_queue}")
    
    async def _send_to_dlq(
        self,
        message: AbstractIncomingMessage,
        error_reason: str,
        original_body: Dict[str, Any]
    ) -> bool:
        """
        Send a message to the Dead Letter Queue.
        
        Args:
            message: Original aio-pika message
            error_reason: Reason for DLQ routing
            original_body: Parsed message body
            
        Returns:
            True if sent successfully, False otherwise
        """
        try:
            # Check if DLQ channel is still open
            if not self.dlq_channel or self.dlq_channel.is_closed:
                self.logger.warning("⚠️  DLQ channel closed, recreating...")
                try:
                    if self.connection and not self.connection.is_closed:
                        self.dlq_channel = await self.connection.channel()
                        await self._setup_dlq()
                    else:
                        self.logger.error("Cannot recreate DLQ channel - connection is closed")
                        return False
                except Exception as e:
                    self.logger.error(f"Failed to recreate DLQ channel: {e}")
                    return False
            
            # Add DLQ metadata
            dlq_body = {
                **original_body,
                "dlq_error": error_reason,
                "dlq_timestamp": datetime.now().isoformat(),
                "original_queue": self.queue,
                "delivery_tag": message.delivery_tag
            }
            
            # Create new message
            dlq_message = Message(
                body=json.dumps(dlq_body).encode(),
                delivery_mode=DeliveryMode.PERSISTENT,
                headers={
                    "x-original-queue": self.queue,
                    "x-dlq-reason": error_reason,
                    "x-dlq-timestamp": datetime.now().isoformat()
                }
            )
            
            # Publish to DLQ
            await self.dlq_exchange.publish(
                dlq_message,
                routing_key=self.dlq_queue
            )
            
            self.logger.info(f"📮 Sent message to DLQ: {error_reason}")
            return True
            
        except (aio_pika.exceptions.AMQPConnectionError,
                aio_pika.exceptions.AMQPChannelError) as e:
            self.logger.error(f"❌ AMQP error sending to DLQ: {e}")
            return False
        except Exception as e:
            self.logger.error(f"❌ Failed to send message to DLQ: {e}", exc_info=True)
            return False
    
    async def _process_message(
        self,
        message: AbstractIncomingMessage,
        callback: Callable[[Dict[str, Any]], Awaitable[bool]]
    ):
        """
        Process a single message with timeout and error handling.
        
        Args:
            message: Incoming RabbitMQ message
            callback: Async callback function to process message
        """
        start_time = time.time()
        delivery_tag = message.delivery_tag
        msg_body = None
        
        # Track active message
        self._active_message_tags.add(delivery_tag)
        
        try:
            # Parse message
            try:
                msg_body = json.loads(message.body.decode())
            except json.JSONDecodeError as e:
                self.logger.error(f"❌ Invalid JSON in message [{delivery_tag}]: {e}")
                # ACK to remove invalid message
                await message.ack()
                return
            
            # Extract message identifier for logging
            resource_data = msg_body.get('resource_data', {})
            event_data = msg_body.get('event_data', {})
            msg_id = (
                resource_data.get('title') or 
                event_data.get('name') or 
                msg_body.get('title', msg_body.get('id', 'Unknown'))
            )
            
            # Create message hash for tracking
            msg_hash = hashlib.md5(json.dumps(msg_body, sort_keys=True).encode()).hexdigest()[:8]
            
            self.logger.info(
                f"📨 Processing message [{delivery_tag}]: '{msg_id}' "
                f"(hash:{msg_hash}, active:{self.active_tasks}/{self.max_concurrent})"
            )
            
            # Process with timeout
            try:
                success = await asyncio.wait_for(
                    callback(msg_body),
                    timeout=self.message_timeout
                )
                
                processing_duration = time.time() - start_time
                
                if success:
                    await message.ack()
                    self.total_messages_processed += 1
                    self.logger.info(
                        f"✅ Message [{delivery_tag}] processed successfully in {processing_duration:.1f}s "
                        f"(total: {self.total_messages_processed})"
                    )
                else:
                    # Callback returned False - requeue
                    await message.nack(requeue=True)
                    self.total_messages_failed += 1
                    self.logger.warning(
                        f"❌ Message [{delivery_tag}] processing failed after {processing_duration:.1f}s, "
                        f"requeued (total failed: {self.total_messages_failed})"
                    )
                    
            except asyncio.TimeoutError:
                # Message processing timeout - send to DLQ
                processing_duration = time.time() - start_time
                error_msg = f"TIMEOUT: Processing exceeded {processing_duration:.1f}s (limit: {self.message_timeout}s)"
                
                self.logger.error(
                    f"⏱️  TIMEOUT DLQ: Message [{delivery_tag}] exceeded time limit after {processing_duration:.1f}s: '{msg_id}'"
                )
                
                # Send to DLQ with timeout reason
                dlq_success = await self._send_to_dlq(message, error_msg, msg_body)
                
                if dlq_success:
                    # ACK to remove from main queue
                    await message.ack()
                    self.total_messages_timeout += 1
                    self.logger.info(
                        f"✅ TIMEOUT → DLQ: Message [{delivery_tag}] sent to DLQ after {processing_duration:.1f}s "
                        f"(total timeouts: {self.total_messages_timeout})"
                    )
                else:
                    # Failed to send to DLQ - requeue for retry
                    await message.nack(requeue=True)
                    self.logger.warning(f"⚠️  Failed to send timeout message [{delivery_tag}] to DLQ, requeued")
                    
        except asyncio.CancelledError:
            # Task was cancelled (shutdown) - reject and requeue
            self.logger.warning(f"⚠️  Message [{delivery_tag}] processing cancelled, requeuing")
            await message.nack(requeue=True)
            raise
            
        except Exception as e:
            # Unexpected error - log and requeue
            processing_duration = time.time() - start_time
            self.logger.error(
                f"💥 Unexpected error processing message [{delivery_tag}] after {processing_duration:.1f}s: {e}",
                exc_info=True
            )
            
            try:
                # Try to send to DLQ for unexpected errors
                if msg_body:
                    dlq_success = await self._send_to_dlq(message, f"Unexpected error: {str(e)}", msg_body)
                    if dlq_success:
                        await message.ack()
                    else:
                        await message.nack(requeue=True)
                else:
                    await message.nack(requeue=True)
            except Exception as nack_error:
                self.logger.error(f"Failed to NACK message: {nack_error}")
        
        finally:
            self._active_message_tags.discard(delivery_tag)
    
    async def _message_handler(
        self,
        message: AbstractIncomingMessage,
        callback: Callable[[Dict[str, Any]], Awaitable[bool]]
    ):
        """
        Handle incoming message with semaphore-based concurrency control.
        
        Args:
            message: Incoming RabbitMQ message
            callback: Async callback function to process message
        """
        async with self.semaphore:
            self.active_tasks += 1
            try:
                await self._process_message(message, callback)
            finally:
                self.active_tasks -= 1
    
    async def consume(
        self,
        callback: Callable[[Dict[str, Any]], Awaitable[bool]]
    ):
        """
        Start consuming messages from the queue with automatic reconnection.
        
        Args:
            callback: Async function to process each message. Should return True if successful.
                     The function receives a dictionary (parsed JSON) as input and must be async.
        """
        if not self.connection or self.connection.is_closed:
            await self.connect()
        
        self._should_stop = False
        reconnect_attempt = 0
        
        self.logger.info(
            f"🚀 Starting async message consumption from queue: {self.queue}\n"
            f"   Max concurrent: {self.max_concurrent}\n"
            f"   Prefetch count: {self.prefetch_count}\n"
            f"   Message timeout: {self.message_timeout}s"
        )
        
        # Main reconnection loop
        while not self._should_stop:
            try:
                # Ensure we have a valid connection and channel
                if not self.connection or self.connection.is_closed:
                    self.logger.warning("⚠️  Connection lost, reconnecting...")
                    await asyncio.sleep(self.reconnect_delay)
                    await self.connect()
                    reconnect_attempt += 1
                    continue
                
                if not self.channel or self.channel.is_closed:
                    self.logger.warning("⚠️  Channel closed, recreating...")
                    self.channel = await self.connection.channel()
                    self.channel.close_callbacks.add(self._on_channel_closed)
                    await self.channel.set_qos(prefetch_count=self.prefetch_count)
                    self.queue_obj = await self.channel.declare_queue(self.queue, durable=True)
                    reconnect_attempt += 1
                
                # Reset reconnect counter on successful connection
                if reconnect_attempt > 0:
                    self.logger.info(f"✅ Reconnected after {reconnect_attempt} attempt(s)")
                    reconnect_attempt = 0
                
                # Start consuming with async iteration
                self.logger.debug(f"Starting queue iterator for {self.queue}")
                async with self.queue_obj.iterator() as queue_iter:
                    async for message in queue_iter:
                        if self._should_stop:
                            self.logger.info("Stop flag set, breaking consume loop")
                            break
                        
                        # Process message in background task (don't await)
                        asyncio.create_task(
                            self._message_handler(message, callback)
                        )
                
                # If we exit the iterator normally and haven't been told to stop, reconnect
                if not self._should_stop:
                    self.logger.warning("Queue iterator exited unexpectedly, will reconnect...")
                    await asyncio.sleep(self.reconnect_delay)
                    
            except asyncio.CancelledError:
                self.logger.info("Consumer task cancelled, shutting down gracefully...")
                self._should_stop = True
                break
                
            except (aio_pika.exceptions.AMQPConnectionError, 
                    aio_pika.exceptions.AMQPChannelError,
                    ConnectionError) as e:
                if self._should_stop:
                    break
                
                reconnect_attempt += 1
                self.logger.error(
                    f"💔 AMQP error (attempt {reconnect_attempt}): {type(e).__name__}: {e}\n"
                    f"   Active tasks: {self.active_tasks}\n"
                    f"   Reconnecting in {self.reconnect_delay}s..."
                )
                
                # Clean up stale connections
                try:
                    if self.channel and not self.channel.is_closed:
                        await self.channel.close()
                except Exception:
                    pass
                
                self.channel = None
                self.queue_obj = None
                
                await asyncio.sleep(self.reconnect_delay)
                
            except Exception as e:
                if self._should_stop:
                    break
                    
                self.logger.error(f"💥 Unexpected error in consumer loop: {e}", exc_info=True)
                
                # For unexpected errors, wait and retry
                reconnect_attempt += 1
                self.logger.warning(f"Will retry in {self.reconnect_delay}s (attempt {reconnect_attempt})...")
                await asyncio.sleep(self.reconnect_delay)
        
        self.logger.info("Consumer loop exited")
    
    async def stop(self):
        """Stop consuming and close the connection gracefully."""
        self._should_stop = True
        
        # Calculate stats
        connection_lifetime = 0
        if self.connection_start_time:
            connection_lifetime = time.time() - self.connection_start_time
        
        self.logger.info("🛑 Stopping Async RabbitMQ consumer...")
        self.logger.info(
            f"📊 Final Statistics:\n"
            f"   Total processed: {self.total_messages_processed}\n"
            f"   Total failed: {self.total_messages_failed}\n"
            f"   Total timeout: {self.total_messages_timeout}\n"
            f"   Connection lifetime: {connection_lifetime:.1f}s\n"
            f"   Active tasks: {self.active_tasks}"
        )
        
        # Wait for active tasks to complete (with timeout)
        if self.active_tasks > 0:
            self.logger.info(f"⏳ Waiting for {self.active_tasks} active tasks to complete...")
            
            wait_start = time.time()
            max_wait = 30  # Wait up to 30 seconds
            
            while self.active_tasks > 0 and (time.time() - wait_start) < max_wait:
                await asyncio.sleep(0.5)
            
            if self.active_tasks > 0:
                self.logger.warning(f"⚠️  {self.active_tasks} tasks still active after {max_wait}s wait")
        
        # Close connections
        try:
            if self.channel and not self.channel.is_closed:
                await self.channel.close()
                self.logger.debug("Main channel closed")
        except Exception as e:
            self.logger.debug(f"Error closing main channel: {e}")
        
        try:
            if self.dlq_channel and not self.dlq_channel.is_closed:
                await self.dlq_channel.close()
                self.logger.debug("DLQ channel closed")
        except Exception as e:
            self.logger.debug(f"Error closing DLQ channel: {e}")
        
        try:
            if self.connection and not self.connection.is_closed:
                await self.connection.close()
                self.logger.info("Connection closed")
        except Exception as e:
            self.logger.debug(f"Error closing connection: {e}")
        
        self.logger.info("✅ Async RabbitMQ consumer stopped")
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.stop()
