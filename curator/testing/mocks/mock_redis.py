"""
Mock Redis Client for testing.

Provides an in-memory implementation that mimics the redis.Redis interface
without requiring an actual Redis server.
"""

from typing import Any, Dict, Optional
from datetime import datetime, timedelta
import logging


class MockRedisClient:
    """
    Mock Redis client that stores data in memory.
    
    Implements common Redis operations used by the curator service.
    """
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        decode_responses: bool = True,
        socket_connect_timeout: int = 5,
    ):
        self.host = host
        self.port = port
        self.decode_responses = decode_responses
        
        # In-memory storage
        self._data: Dict[str, Any] = {}
        self._expiry: Dict[str, datetime] = {}
        
        # Track operations for assertions
        self.operation_history: list = []
        
        self.logger = logging.getLogger(__name__)
    
    def _record_operation(self, op: str, key: str, **kwargs):
        """Record an operation for test assertions."""
        self.operation_history.append({
            "operation": op,
            "key": key,
            "timestamp": datetime.now(),
            **kwargs
        })
    
    def _check_expiry(self, key: str) -> bool:
        """Check if a key has expired. Returns True if expired."""
        if key in self._expiry:
            if datetime.now() > self._expiry[key]:
                del self._data[key]
                del self._expiry[key]
                return True
        return False
    
    def get(self, key: str) -> Optional[str]:
        """Get a value by key."""
        self._record_operation("get", key)
        
        if self._check_expiry(key):
            return None
        
        value = self._data.get(key)
        
        # Simulate decode_responses behavior
        if value is not None and self.decode_responses and isinstance(value, bytes):
            return value.decode("utf-8")
        
        return value
    
    def set(
        self,
        key: str,
        value: Any,
        ex: Optional[int] = None,
        px: Optional[int] = None,
        nx: bool = False,
        xx: bool = False,
    ) -> Optional[bool]:
        """
        Set a key-value pair.
        
        Args:
            key: The key
            value: The value
            ex: Expire time in seconds
            px: Expire time in milliseconds
            nx: Only set if key doesn't exist
            xx: Only set if key exists
        """
        self._record_operation("set", key, value=value, ex=ex, nx=nx, xx=xx)
        
        # Handle nx/xx flags
        exists = key in self._data and not self._check_expiry(key)
        
        if nx and exists:
            return False
        if xx and not exists:
            return False
        
        self._data[key] = value
        
        # Handle expiry
        if ex is not None:
            self._expiry[key] = datetime.now() + timedelta(seconds=ex)
        elif px is not None:
            self._expiry[key] = datetime.now() + timedelta(milliseconds=px)
        elif key in self._expiry:
            del self._expiry[key]
        
        return True
    
    def delete(self, *keys: str) -> int:
        """Delete one or more keys."""
        deleted = 0
        for key in keys:
            self._record_operation("delete", key)
            if key in self._data:
                del self._data[key]
                if key in self._expiry:
                    del self._expiry[key]
                deleted += 1
        return deleted
    
    def exists(self, *keys: str) -> int:
        """Check if keys exist."""
        count = 0
        for key in keys:
            self._record_operation("exists", key)
            if key in self._data and not self._check_expiry(key):
                count += 1
        return count
    
    def expire(self, key: str, seconds: int) -> bool:
        """Set an expiry on a key."""
        self._record_operation("expire", key, seconds=seconds)
        
        if key not in self._data or self._check_expiry(key):
            return False
        
        self._expiry[key] = datetime.now() + timedelta(seconds=seconds)
        return True
    
    def ttl(self, key: str) -> int:
        """Get time-to-live for a key."""
        self._record_operation("ttl", key)
        
        if key not in self._data or self._check_expiry(key):
            return -2  # Key doesn't exist
        
        if key not in self._expiry:
            return -1  # No expiry set
        
        remaining = (self._expiry[key] - datetime.now()).total_seconds()
        return max(0, int(remaining))
    
    def incr(self, key: str) -> int:
        """Increment a key's integer value."""
        self._record_operation("incr", key)
        
        if self._check_expiry(key):
            self._data[key] = 0
        
        current = self._data.get(key, 0)
        if isinstance(current, str):
            current = int(current)
        
        new_value = current + 1
        self._data[key] = new_value
        return new_value
    
    def decr(self, key: str) -> int:
        """Decrement a key's integer value."""
        self._record_operation("decr", key)
        
        if self._check_expiry(key):
            self._data[key] = 0
        
        current = self._data.get(key, 0)
        if isinstance(current, str):
            current = int(current)
        
        new_value = current - 1
        self._data[key] = new_value
        return new_value
    
    def setnx(self, key: str, value: Any) -> bool:
        """Set key only if it doesn't exist."""
        return self.set(key, value, nx=True) or False
    
    def setex(self, key: str, seconds: int, value: Any) -> bool:
        """Set key with expiry in seconds."""
        return self.set(key, value, ex=seconds) or False
    
    def ping(self) -> bool:
        """Ping the server."""
        self._record_operation("ping", "")
        return True
    
    def flushall(self):
        """Clear all data."""
        self._record_operation("flushall", "")
        self._data.clear()
        self._expiry.clear()
    
    def flushdb(self):
        """Clear current database."""
        self.flushall()
    
    # Test helper methods
    def clear(self):
        """Clear all data and history (test helper)."""
        self._data.clear()
        self._expiry.clear()
        self.operation_history.clear()
    
    def get_operation_count(self, operation: str) -> int:
        """Get count of specific operation (test helper)."""
        return sum(1 for op in self.operation_history if op["operation"] == operation)
    
    def was_key_accessed(self, key: str) -> bool:
        """Check if a key was ever accessed (test helper)."""
        return any(op["key"] == key for op in self.operation_history)
