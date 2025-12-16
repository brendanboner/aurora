"""Redis-backed state storage for OAuth state parameters."""

import json
import redis
from typing import Dict, Any, Optional
from settings import get_settings

settings = get_settings()

# Redis client singleton
_redis_client: Optional[redis.Redis] = None

# State TTL in seconds (5 minutes - enough time for user to log in)
STATE_TTL = 300


def get_redis_client() -> redis.Redis:
    """Get or create Redis client singleton."""
    global _redis_client
    
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            decode_responses=True,  # Automatically decode bytes to strings
            socket_connect_timeout=5,
            socket_timeout=5,
        )
    
    return _redis_client


def store_oauth_state(state: str, data: Dict[str, Any]) -> None:
    """
    Store OAuth state in Redis with automatic expiration.
    
    Args:
        state: The OAuth state parameter (unique identifier)
        data: Dictionary containing ip, user_agent, etc.
    """
    client = get_redis_client()
    key = f"oauth_state:{state}"
    value = json.dumps(data)
    
    # Set with TTL - automatically expires after STATE_TTL seconds
    client.setex(key, STATE_TTL, value)


def get_oauth_state(state: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve OAuth state from Redis.
    
    Args:
        state: The OAuth state parameter to look up
        
    Returns:
        Dictionary with stored data if found, None otherwise
    """
    client = get_redis_client()
    key = f"oauth_state:{state}"
    
    value = client.get(key)
    if value is None:
        return None
    
    return json.loads(value)


def delete_oauth_state(state: str) -> None:
    """
    Delete OAuth state from Redis (called after successful callback).
    
    Args:
        state: The OAuth state parameter to delete
    """
    client = get_redis_client()
    key = f"oauth_state:{state}"
    client.delete(key)


def cleanup_expired_states() -> int:
    """
    Manual cleanup of expired states (not needed with TTL, but useful for monitoring).
    
    Returns:
        Number of states that were still active
    """
    client = get_redis_client()
    pattern = "oauth_state:*"
    
    count = 0
    for key in client.scan_iter(match=pattern):
        count += 1
    
    return count
