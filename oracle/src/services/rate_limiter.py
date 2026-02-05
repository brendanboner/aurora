"""Rate limiter for YouTube video processing to prevent API throttling."""

import time
import asyncio
import logging
from typing import Optional
from datetime import datetime, timedelta
from collections import deque

from src.settings import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Token bucket rate limiter for controlling request rates.
    
    This prevents hitting API rate limits when processing YouTube videos,
    especially when breaking long videos into multiple segments.
    """
    
    def __init__(
        self,
        max_requests: int,
        time_window: int,
        name: str = "RateLimiter"
    ):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum number of requests allowed in time_window
            time_window: Time window in seconds
            name: Name for logging purposes
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.name = name
        self.request_times = deque()
        self._lock = asyncio.Lock()
        
        logger.info(
            f"Initialized {name}: {max_requests} requests per {time_window}s"
        )
    
    async def acquire(self):
        """
        Acquire permission to make a request.
        
        This will block (sleep) if rate limit would be exceeded,
        ensuring requests stay within the configured limits.
        """
        async with self._lock:
            now = time.time()
            
            # Remove expired timestamps from the window
            cutoff_time = now - self.time_window
            while self.request_times and self.request_times[0] < cutoff_time:
                self.request_times.popleft()
            
            # If we're at the limit, calculate wait time
            if len(self.request_times) >= self.max_requests:
                # Wait until the oldest request expires
                sleep_time = self.request_times[0] + self.time_window - now
                if sleep_time > 0:
                    logger.info(
                        f"{self.name}: Rate limit reached "
                        f"({len(self.request_times)}/{self.max_requests}), "
                        f"sleeping {sleep_time:.2f}s"
                    )
                    await asyncio.sleep(sleep_time)
                    
                    # Recheck after sleeping
                    now = time.time()
                    cutoff_time = now - self.time_window
                    while self.request_times and self.request_times[0] < cutoff_time:
                        self.request_times.popleft()
            
            # Record this request
            self.request_times.append(now)
            
            logger.debug(
                f"{self.name}: Request {len(self.request_times)}/{self.max_requests} "
                f"in current window"
            )
    
    def reset(self):
        """Reset the rate limiter (clear all tracked requests)."""
        self.request_times.clear()
        logger.info(f"{self.name}: Rate limiter reset")


class YouTubeRateLimiter:
    """
    Specialized rate limiter for YouTube API operations.
    
    YouTube API has quotas:
    - Data API v3: 10,000 units/day (not used yet)
    - Transcript API: ~100 requests/hour (community library, conservative limit)
    - RabbitMQ publishing: No hard limit but avoid overwhelming the queue
    """
    
    def __init__(self):
        """Initialize YouTube-specific rate limiters."""
        # Transcript fetching: Conservative limit to avoid issues
        # Configurable via environment variables
        self.transcript_limiter = RateLimiter(
            max_requests=settings.youtube_transcript_max_requests,
            time_window=settings.youtube_transcript_time_window,
            name="YouTubeTranscript"
        )
        
        # RabbitMQ publishing: Prevent overwhelming the queue
        # Configurable via environment variables
        self.rabbitmq_limiter = RateLimiter(
            max_requests=settings.rabbitmq_max_requests,
            time_window=settings.rabbitmq_time_window,
            name="RabbitMQ"
        )
        
        logger.info("Initialized YouTube rate limiters")
    
    async def acquire_transcript(self):
        """Acquire permission to fetch a transcript."""
        await self.transcript_limiter.acquire()
    
    async def acquire_rabbitmq(self):
        """Acquire permission to publish to RabbitMQ."""
        await self.rabbitmq_limiter.acquire()
    
    def reset_all(self):
        """Reset all rate limiters."""
        self.transcript_limiter.reset()
        self.rabbitmq_limiter.reset()


# Global instance for shared rate limiting across requests
_youtube_rate_limiter: Optional[YouTubeRateLimiter] = None


def get_youtube_rate_limiter() -> YouTubeRateLimiter:
    """
    Get the global YouTube rate limiter instance.
    
    Uses singleton pattern to ensure rate limiting is shared
    across all requests in the application.
    """
    global _youtube_rate_limiter
    if _youtube_rate_limiter is None:
        _youtube_rate_limiter = YouTubeRateLimiter()
    return _youtube_rate_limiter
