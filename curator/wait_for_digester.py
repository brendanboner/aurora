#!/usr/bin/env python3
"""
Wait for Digester Completion Script

This script monitors RabbitMQ queue and Redis to determine when the digester
has finished processing all messages. It waits until:
1. The RabbitMQ queue is empty (no messages ready)
2. The digester has no active processing (checked via Redis)
3. The queue remains empty for a configurable duration

This ensures curator runs only after all documents have been fully processed.
"""

import time
import sys
import os
from datetime import datetime
import pika
import redis
import json
from typing import Optional


def get_env_int(name: str, default: int) -> int:
    """Get integer from environment with default."""
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def get_env_bool(name: str, default: bool) -> bool:
    """Get boolean from environment with default."""
    value = os.getenv(name, str(default)).lower()
    return value in ('true', '1', 'yes', 'on')


# Configuration from environment
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = get_env_int("RABBITMQ_PORT", 5672)
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "user")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "password")
RABBITMQ_QUEUE = os.getenv("RABBITMQ_QUEUE", "scraped_content")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = get_env_int("REDIS_PORT", 6379)

# Wait for queue to be empty for this duration before proceeding
QUEUE_EMPTY_WAIT_SECONDS = get_env_int("QUEUE_EMPTY_WAIT_SECONDS", 30)

# Maximum time to wait overall (safety timeout)
MAX_WAIT_MINUTES = get_env_int("MAX_WAIT_MINUTES", 60)

# Check interval
CHECK_INTERVAL_SECONDS = 5

# Whether to wait at all (can be disabled for testing)
WAIT_FOR_DIGESTER = get_env_bool("WAIT_FOR_DIGESTER", True)


def log(message: str):
    """Simple logging with timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def check_rabbitmq_queue() -> Optional[int]:
    """
    Check RabbitMQ queue for message count.
    
    Returns:
        Number of messages in queue, or None if error
    """
    try:
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=RABBITMQ_HOST,
                port=RABBITMQ_PORT,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300
            )
        )
        channel = connection.channel()
        
        # Passive declare to get queue info without creating it
        method = channel.queue_declare(queue=RABBITMQ_QUEUE, passive=True)
        message_count = method.method.message_count
        
        connection.close()
        return message_count
        
    except Exception as e:
        log(f"Error checking RabbitMQ queue: {e}")
        return None


def check_digester_state() -> dict:
    """
    Check digester state from Redis.
    
    Returns:
        Dictionary with digester state info
    """
    state = {
        "active": False,
        "heartbeat_age_seconds": None,
        "currently_processing": False
    }
    
    try:
        r = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=5
        )
        r.ping()
        
        # Check heartbeat
        heartbeat = r.get("digester:heartbeat")
        if heartbeat:
            heartbeat_time = float(heartbeat)
            age_seconds = time.time() - heartbeat_time
            state["heartbeat_age_seconds"] = age_seconds
            # Consider digester active if heartbeat is fresh (< 5 minutes)
            state["active"] = age_seconds < 300
        
        # Check if currently processing
        current = r.get("digester:current")
        if current:
            try:
                processing_data = json.loads(current)
                state["currently_processing"] = True
                state["processing_data"] = processing_data
            except json.JSONDecodeError:
                pass
        
    except Exception as e:
        log(f"Warning: Could not check Redis for digester state: {e}")
    
    return state


def wait_for_queue_empty():
    """
    Wait for RabbitMQ queue to be empty and digester to be idle.
    
    Returns:
        True if conditions met, False if timeout
    """
    if not WAIT_FOR_DIGESTER:
        log("WAIT_FOR_DIGESTER is disabled, skipping wait")
        return True
    
    log("=" * 70)
    log("Waiting for digester to complete processing...")
    log(f"Configuration:")
    log(f"  - Queue empty wait time: {QUEUE_EMPTY_WAIT_SECONDS}s")
    log(f"  - Maximum wait time: {MAX_WAIT_MINUTES} minutes")
    log(f"  - Check interval: {CHECK_INTERVAL_SECONDS}s")
    log("=" * 70)
    
    start_time = time.time()
    max_wait_seconds = MAX_WAIT_MINUTES * 60
    
    # Track when queue became empty
    queue_empty_since = None
    
    # Track if we've seen the queue non-empty (indicates actual work being done)
    has_seen_messages = False
    
    while True:
        elapsed_seconds = time.time() - start_time
        elapsed_minutes = elapsed_seconds / 60
        
        # Check timeout
        if elapsed_seconds > max_wait_seconds:
            log(f"ERROR: Maximum wait time of {MAX_WAIT_MINUTES} minutes exceeded")
            return False
        
        # Check queue
        message_count = check_rabbitmq_queue()
        if message_count is None:
            log("WARNING: Could not check queue, retrying...")
            time.sleep(CHECK_INTERVAL_SECONDS)
            continue
        
        # Check digester state
        digester_state = check_digester_state()
        
        # Track if we've seen messages in the queue (indicates retriever has run)
        if message_count > 0:
            has_seen_messages = True
        
        # Log current state
        log(f"[{elapsed_minutes:.1f}m] Queue: {message_count} messages | "
            f"Digester active: {digester_state['active']} | "
            f"Currently processing: {digester_state['currently_processing']}")
        
        # Check if queue is empty and digester is idle
        # If we've never seen messages AND queue is empty, wait a bit longer
        # This handles the case where retriever is still building its list
        if message_count == 0 and not has_seen_messages and elapsed_seconds < 30:
            log(f"  Queue empty but no messages seen yet - waiting for retriever to populate queue...")
            time.sleep(CHECK_INTERVAL_SECONDS)
            continue
        
        is_idle = message_count == 0 and not digester_state['currently_processing']
        
        if is_idle:
            if queue_empty_since is None:
                queue_empty_since = time.time()
                log(f"✓ Queue is empty and digester is idle. "
                    f"Waiting {QUEUE_EMPTY_WAIT_SECONDS}s to confirm...")
            else:
                empty_duration = time.time() - queue_empty_since
                if empty_duration >= QUEUE_EMPTY_WAIT_SECONDS:
                    log(f"✓ Queue has been empty for {empty_duration:.0f}s. "
                        f"Digester processing complete!")
                    return True
                else:
                    remaining = QUEUE_EMPTY_WAIT_SECONDS - empty_duration
                    log(f"  Confirming idle state... {remaining:.0f}s remaining")
        else:
            # Reset if queue is no longer empty or digester becomes active
            if queue_empty_since is not None:
                log("⚠ Queue has new messages or digester became active, resetting timer")
                queue_empty_since = None
        
        time.sleep(CHECK_INTERVAL_SECONDS)


def main():
    """Main entry point."""
    log("Starting wait-for-digester monitor")
    
    try:
        success = wait_for_queue_empty()
        
        if success:
            log("=" * 70)
            log("✓ Digester has completed processing all messages")
            log("✓ Ready to start curator")
            log("=" * 70)
            sys.exit(0)
        else:
            log("=" * 70)
            log("✗ Timeout waiting for digester completion")
            log("=" * 70)
            sys.exit(1)
            
    except KeyboardInterrupt:
        log("Interrupted by user")
        sys.exit(1)
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
