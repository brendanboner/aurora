"""
Shared LLM rate limiter for Azure OpenAI API calls.

This module provides proactive rate limiting for LLM API calls to prevent
hitting Azure OpenAI rate limits. Uses token bucket algorithm with async support.
"""

import time
import asyncio
import logging
from typing import Optional
from collections import deque

logger = logging.getLogger(__name__)


class LLMRateLimiter:
    """
    Token bucket rate limiter for LLM API calls.
    
    This prevents hitting Azure OpenAI TPM (tokens per minute) and RPM (requests per minute)
    limits by proactively throttling requests before they're sent to the API.
    
    Attributes:
        max_requests_per_minute: Maximum requests allowed per minute
        max_tokens_per_minute: Maximum tokens allowed per minute (TPM quota)
        request_times: Deque of request timestamps for sliding window
        token_usage: Deque of (timestamp, tokens) tuples for token tracking
        lock: Asyncio lock for thread-safe operations
    """
    
    def __init__(
        self,
        max_requests_per_minute: int = 60,
        max_tokens_per_minute: int = 10000,
        name: str = "LLMRateLimiter"
    ):
        """
        Initialize LLM rate limiter.
        
        Args:
            max_requests_per_minute: Maximum API requests per minute (RPM quota)
            max_tokens_per_minute: Maximum tokens per minute (TPM quota)
            name: Name for logging purposes
        """
        self.max_requests_per_minute = max_requests_per_minute
        self.max_tokens_per_minute = max_tokens_per_minute
        self.name = name
        self.time_window = 60  # 1 minute window
        
        self.request_times: deque[float] = deque()
        self.token_usage: deque[tuple[float, int]] = deque()
        self._lock = asyncio.Lock()
        
        logger.info(
            f"Initialized {name}: {max_requests_per_minute} req/min, "
            f"{max_tokens_per_minute} tokens/min"
        )
    
    def _cleanup_expired(self, now: float):
        """Remove expired entries from sliding windows."""
        cutoff_time = now - self.time_window
        
        # Clean up request times
        while self.request_times and self.request_times[0] < cutoff_time:
            self.request_times.popleft()
        
        # Clean up token usage
        while self.token_usage and self.token_usage[0][0] < cutoff_time:
            self.token_usage.popleft()
    
    async def acquire(self, estimated_tokens: int = 1000):
        """
        Acquire permission to make an LLM API call.
        
        This will block (sleep) if rate limits would be exceeded, ensuring
        requests stay within the configured RPM and TPM limits.
        
        Args:
            estimated_tokens: Estimated tokens for this request (prompt + completion)
                             Default 1000 tokens is conservative estimate
        """
        async with self._lock:
            now = time.time()
            self._cleanup_expired(now)
            
            # Calculate current usage in the window
            current_requests = len(self.request_times)
            current_tokens = sum(tokens for _, tokens in self.token_usage)
            
            # Check if we need to wait for request limit
            request_wait = 0.0
            if current_requests >= self.max_requests_per_minute:
                oldest_request = self.request_times[0]
                request_wait = (oldest_request + self.time_window) - now
            
            # Check if we need to wait for token limit
            token_wait = 0.0
            if current_tokens + estimated_tokens > self.max_tokens_per_minute:
                # Need to wait until enough tokens expire
                tokens_needed = (current_tokens + estimated_tokens) - self.max_tokens_per_minute
                tokens_freed = 0
                
                for timestamp, tokens in self.token_usage:
                    tokens_freed += tokens
                    if tokens_freed >= tokens_needed:
                        token_wait = (timestamp + self.time_window) - now
                        break
            
            # Wait for the longer of the two constraints
            sleep_time = max(request_wait, token_wait)
            
            if sleep_time > 0:
                logger.info(
                    f"{self.name}: Rate limit approaching "
                    f"(requests: {current_requests}/{self.max_requests_per_minute}, "
                    f"tokens: {current_tokens}/{self.max_tokens_per_minute}), "
                    f"sleeping {sleep_time:.2f}s"
                )
                await asyncio.sleep(sleep_time)
                
                # Recheck after sleeping
                now = time.time()
                self._cleanup_expired(now)
            
            # Record this request and estimated token usage
            self.request_times.append(now)
            self.token_usage.append((now, estimated_tokens))
            
            logger.debug(
                f"{self.name}: Request {len(self.request_times)}/{self.max_requests_per_minute}, "
                f"Tokens: {sum(t for _, t in self.token_usage)}/{self.max_tokens_per_minute}"
            )
    
    def reset(self):
        """Reset the rate limiter (clear all tracked usage)."""
        self.request_times.clear()
        self.token_usage.clear()
        logger.info(f"{self.name}: Rate limiter reset")


# Global singleton instance
_llm_rate_limiter: Optional[LLMRateLimiter] = None


def get_llm_rate_limiter(
    max_requests_per_minute: int = 60,
    max_tokens_per_minute: int = 10000
) -> LLMRateLimiter:
    """
    Get the singleton LLM rate limiter instance.
    
    Args:
        max_requests_per_minute: Maximum API requests per minute (RPM quota)
        max_tokens_per_minute: Maximum tokens per minute (TPM quota)
    
    Returns:
        LLMRateLimiter: The global rate limiter instance
    """
    global _llm_rate_limiter
    if _llm_rate_limiter is None:
        _llm_rate_limiter = LLMRateLimiter(
            max_requests_per_minute=max_requests_per_minute,
            max_tokens_per_minute=max_tokens_per_minute,
            name="AzureOpenAI"
        )
    return _llm_rate_limiter
