"""
Example: Async RabbitMQ Consumer Usage

This demonstrates how to use the AsyncRabbitMQConsumer with various scenarios.
"""

import asyncio
import logging
from rabbitmq_client import AsyncRabbitMQConsumer

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Example 1: Simple async message handler
async def simple_handler(message: dict) -> bool:
    """
    Simple message handler that processes messages quickly.
    
    Returns:
        True if successful, False to requeue
    """
    logger.info(f"Processing message: {message.get('title', 'Unknown')}")
    
    # Simulate some async work
    await asyncio.sleep(1)
    
    return True


# Example 2: Handler with error handling
async def robust_handler(message: dict) -> bool:
    """
    Handler with comprehensive error handling.
    
    Returns:
        True: Success (ACK)
        False: Temporary failure (NACK + requeue)
        Raises: Fatal error (send to DLQ)
    """
    try:
        logger.info(f"Processing: {message}")
        
        # Simulate async work (API call, database query, etc.)
        await asyncio.sleep(2)
        
        # Simulate occasional failures
        if message.get('simulate_retry'):
            logger.warning("Simulated retry scenario")
            return False  # Will be requeued
        
        if message.get('simulate_fatal'):
            raise ValueError("Simulated fatal error")  # Will go to DLQ
        
        return True
        
    except ValueError as e:
        # Fatal errors - raise to send to DLQ
        logger.error(f"Fatal error: {e}")
        raise
    except Exception as e:
        # Temporary errors - return False to requeue
        logger.warning(f"Temporary error: {e}")
        return False


# Example 3: Handler that simulates long processing
async def slow_handler(message: dict) -> bool:
    """
    Handler that simulates slow processing (for timeout testing).
    
    If message contains 'duration', will process for that many seconds.
    """
    duration = message.get('duration', 5)
    logger.info(f"Starting slow processing for {duration}s...")
    
    # Simulate long-running work
    await asyncio.sleep(duration)
    
    logger.info(f"Completed after {duration}s")
    return True


# Example 4: Basic usage with context manager
async def example_basic():
    """Basic consumer usage with context manager."""
    logger.info("=== Example 1: Basic Usage ===")
    
    consumer = AsyncRabbitMQConsumer(
        host="localhost",
        port=5672,
        user="guest",
        password="guest",
        queue="test_queue",
        max_concurrent=5,
        message_timeout=30.0
    )
    
    async with consumer:
        # This will run until interrupted (Ctrl+C)
        await consumer.consume(simple_handler)


# Example 5: Manual connection management
async def example_manual():
    """Consumer with manual connection management."""
    logger.info("=== Example 2: Manual Management ===")
    
    consumer = AsyncRabbitMQConsumer(
        host="localhost",
        queue="test_queue",
        max_concurrent=10
    )
    
    try:
        await consumer.connect()
        await consumer.consume(robust_handler)
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        await consumer.stop()


# Example 6: Production configuration
async def example_production():
    """Production-ready configuration for digester."""
    logger.info("=== Example 3: Production Config ===")
    
    consumer = AsyncRabbitMQConsumer(
        host="aurora-rabbitmq",
        port=5672,
        user="production_user",
        password="secure_password",
        queue="scraped_content",
        dlq_queue="scraped_content-dlq",
        max_concurrent=10,           # 10 messages at once
        message_timeout=1200.0,      # 20 minute timeout
        heartbeat=60,                # 60 second heartbeat
        prefetch_count=20,           # Prefetch 20 messages
        reconnect_delay=5.0          # 5s between reconnects
    )
    
    try:
        async with consumer:
            await consumer.consume(robust_handler)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise


# Example 7: Testing timeout behavior
async def example_timeout():
    """Demonstrate timeout handling."""
    logger.info("=== Example 4: Timeout Testing ===")
    
    consumer = AsyncRabbitMQConsumer(
        host="localhost",
        queue="test_queue",
        max_concurrent=3,
        message_timeout=10.0,  # Short timeout for testing
        heartbeat=60
    )
    
    async with consumer:
        # Use slow_handler - messages with duration > 10s will timeout
        await consumer.consume(slow_handler)


# Example 8: High throughput configuration
async def example_high_throughput():
    """High throughput configuration for fast messages."""
    logger.info("=== Example 5: High Throughput ===")
    
    consumer = AsyncRabbitMQConsumer(
        host="localhost",
        queue="fast_queue",
        max_concurrent=50,       # Process 50 at once
        message_timeout=60.0,    # 1 minute timeout
        heartbeat=30,            # 30 second heartbeat
        prefetch_count=100       # Prefetch 100 messages
    )
    
    async with consumer:
        await consumer.consume(simple_handler)


# Example 9: Multiple consumers
async def example_multiple_consumers():
    """Run multiple consumers concurrently."""
    logger.info("=== Example 6: Multiple Consumers ===")
    
    consumer1 = AsyncRabbitMQConsumer(
        host="localhost",
        queue="queue1",
        max_concurrent=5
    )
    
    consumer2 = AsyncRabbitMQConsumer(
        host="localhost",
        queue="queue2",
        max_concurrent=5
    )
    
    async with consumer1, consumer2:
        # Run both consumers concurrently
        await asyncio.gather(
            consumer1.consume(simple_handler),
            consumer2.consume(robust_handler)
        )


# Main entry point
async def main():
    """Run examples."""
    # Choose which example to run
    # await example_basic()
    # await example_manual()
    await example_production()
    # await example_timeout()
    # await example_high_throughput()
    # await example_multiple_consumers()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown complete")
