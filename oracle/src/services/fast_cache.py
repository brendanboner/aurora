"""Fast pipeline cache extensions.

Adds plan, result, and answer caching for the fast retrieval pipeline.
"""

import hashlib
import json
import logging
from typing import Optional, Any
from datetime import datetime, timedelta

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None

from src.models.route_plan import RoutePlan, RouteResult
from src.settings import settings

logger = logging.getLogger(__name__)


class FastCachePrefix:
    """Cache key prefixes for fast pipeline."""
    PLAN = "fast:plan:"
    RESULT = "fast:result:"
    ANSWER = "fast:answer:"


def hash_route_plan(plan: RoutePlan) -> str:
    """
    Generate hash for a route plan.
    
    Args:
        plan: Route plan to hash
        
    Returns:
        SHA256 hash (16 chars)
    """
    # Include key plan attributes
    plan_dict = {
        "route_id": plan.route_id.value,
        "start_date": plan.start_date.isoformat() if plan.start_date else None,
        "end_date": plan.end_date.isoformat() if plan.end_date else None,
        "relative_days": plan.relative_days,
        "workgroups": sorted(plan.workgroups),
        "topics": sorted(plan.topics),
        "organizations": sorted(plan.organizations),
        "people": sorted(plan.people),
        "detail_level": plan.detail_level.value,
        "template_version": plan.template_version,
    }
    
    serialized = json.dumps(plan_dict, sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


def normalize_query(query: str) -> str:
    """
    Normalize query text for caching.
    
    Args:
        query: Raw query text
        
    Returns:
        Normalized query (lowercase, stripped, single spaces)
    """
    return " ".join(query.lower().strip().split())


class FastCache:
    """
    Cache layer for fast pipeline.
    
    Provides three cache tiers:
    - Plan cache: Maps normalized query -> RoutePlan
    - Result cache: Maps RoutePlan hash -> RouteResult (Neo4j results)
    - Answer cache: Maps RoutePlan hash + result digest -> final answer
    """
    
    def __init__(self, redis_client: Optional['redis.Redis'] = None):
        """
        Initialize fast cache.
        
        Args:
            redis_client: Optional Redis client (reuse from OracleCache)
        """
        self.redis_client = redis_client
        self.enabled = settings.cache_enabled and REDIS_AVAILABLE and redis_client is not None
        
        if self.enabled:
            logger.info("FastCache enabled with Redis")
        else:
            logger.info("FastCache disabled (Redis not available)")
    
    # ===== Plan Cache =====
    
    async def get_plan(self, query: str, user_prefs: Optional[dict] = None) -> Optional[RoutePlan]:
        """
        Get cached route plan for a query.
        
        Args:
            query: Normalized user query
            user_prefs: Optional user preferences (for personalization)
            
        Returns:
            Cached RoutePlan or None
        """
        if not self.enabled:
            return None
        
        try:
            # Generate cache key
            cache_key = self._plan_cache_key(query, user_prefs)
            
            # Get from Redis
            cached = await self.redis_client.get(cache_key)
            
            if cached:
                logger.debug(f"Plan cache hit: {cache_key}")
                plan_dict = json.loads(cached)
                return RoutePlan(**plan_dict)
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting cached plan: {e}", exc_info=True)
            return None
    
    async def set_plan(
        self,
        query: str,
        plan: RoutePlan,
        user_prefs: Optional[dict] = None,
        ttl: Optional[int] = None
    ):
        """
        Cache a route plan.
        
        Args:
            query: Normalized user query
            plan: Route plan to cache
            user_prefs: Optional user preferences
            ttl: Time to live in seconds (default from settings)
        """
        if not self.enabled:
            return
        
        try:
            cache_key = self._plan_cache_key(query, user_prefs)
            ttl = ttl or settings.fast_cache_plan_ttl
            
            # Serialize plan (mode='json' handles date/datetime serialization)
            plan_json = json.dumps(plan.model_dump(mode='json'))
            
            # Store in Redis
            await self.redis_client.setex(cache_key, ttl, plan_json)
            
            logger.debug(f"Cached plan: {cache_key} (TTL={ttl}s)")
            
        except Exception as e:
            logger.error(f"Error caching plan: {e}", exc_info=True)
    
    def _plan_cache_key(self, query: str, user_prefs: Optional[dict] = None) -> str:
        """Generate cache key for plan cache."""
        normalized = normalize_query(query)
        
        # Include user prefs hash if present (for personalization)
        prefs_hash = ""
        if user_prefs:
            prefs_str = json.dumps(user_prefs, sort_keys=True)
            prefs_hash = hashlib.sha256(prefs_str.encode()).hexdigest()[:8]
        
        query_hash = hashlib.sha256(normalized.encode()).hexdigest()[:16]
        
        return f"{FastCachePrefix.PLAN}{query_hash}:{prefs_hash}" if prefs_hash else f"{FastCachePrefix.PLAN}{query_hash}"
    
    # ===== Result Cache =====
    
    async def get_result(self, plan: RoutePlan) -> Optional[RouteResult]:
        """
        Get cached route result (Neo4j query results).
        
        Args:
            plan: Route plan
            
        Returns:
            Cached RouteResult or None
        """
        if not self.enabled:
            return None
        
        try:
            cache_key = self._result_cache_key(plan)
            
            cached = await self.redis_client.get(cache_key)
            
            if cached:
                logger.debug(f"Result cache hit: {cache_key}")
                result_dict = json.loads(cached)
                return RouteResult(**result_dict)
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting cached result: {e}", exc_info=True)
            return None
    
    async def set_result(
        self,
        plan: RoutePlan,
        result: RouteResult,
        ttl: Optional[int] = None
    ):
        """
        Cache a route result.
        
        Args:
            plan: Route plan
            result: Route result to cache
            ttl: Time to live in seconds
        """
        if not self.enabled:
            return
        
        try:
            cache_key = self._result_cache_key(plan)
            ttl = ttl or settings.fast_cache_result_ttl
            
            # Mark as cache hit
            result.cache_hit = True
            
            # Serialize result (mode='json' handles date/datetime serialization)
            result_json = json.dumps(result.model_dump(mode='json'))
            
            await self.redis_client.setex(cache_key, ttl, result_json)
            
            logger.debug(f"Cached result: {cache_key} (TTL={ttl}s)")
            
        except Exception as e:
            logger.error(f"Error caching result: {e}", exc_info=True)
    
    def _result_cache_key(self, plan: RoutePlan) -> str:
        """Generate cache key for result cache."""
        plan_hash = hash_route_plan(plan)
        return f"{FastCachePrefix.RESULT}{plan_hash}:{plan.template_version}"
    
    # ===== Answer Cache =====
    
    async def get_answer(self, plan: RoutePlan, result_digest: str) -> Optional[dict]:
        """
        Get cached final answer.
        
        Args:
            plan: Route plan
            result_digest: Hash of result data (for cache key)
            
        Returns:
            Cached answer dict or None
        """
        if not self.enabled:
            return None
        
        try:
            cache_key = self._answer_cache_key(plan, result_digest)
            
            cached = await self.redis_client.get(cache_key)
            
            if cached:
                logger.debug(f"Answer cache hit: {cache_key}")
                return json.loads(cached)
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting cached answer: {e}", exc_info=True)
            return None
    
    async def set_answer(
        self,
        plan: RoutePlan,
        result_digest: str,
        answer: dict,
        ttl: Optional[int] = None
    ):
        """
        Cache a final answer.
        
        Args:
            plan: Route plan
            result_digest: Hash of result data
            answer: Answer dict to cache
            ttl: Time to live in seconds
        """
        if not self.enabled:
            return
        
        try:
            cache_key = self._answer_cache_key(plan, result_digest)
            ttl = ttl or settings.fast_cache_answer_ttl
            
            answer_json = json.dumps(answer)
            
            await self.redis_client.setex(cache_key, ttl, answer_json)
            
            logger.debug(f"Cached answer: {cache_key} (TTL={ttl}s)")
            
        except Exception as e:
            logger.error(f"Error caching answer: {e}", exc_info=True)
    
    def _answer_cache_key(self, plan: RoutePlan, result_digest: str) -> str:
        """Generate cache key for answer cache."""
        plan_hash = hash_route_plan(plan)
        return f"{FastCachePrefix.ANSWER}{plan_hash}:{result_digest[:8]}:{plan.detail_level.value}"
    
    # ===== Invalidation =====
    
    async def invalidate_pattern(self, pattern: str):
        """
        Invalidate cache entries matching a pattern.
        
        Args:
            pattern: Redis key pattern (e.g., "fast:result:*")
        """
        if not self.enabled:
            return
        
        try:
            cursor = 0
            count = 0
            
            while True:
                cursor, keys = await self.redis_client.scan(
                    cursor=cursor,
                    match=pattern,
                    count=100
                )
                
                if keys:
                    await self.redis_client.delete(*keys)
                    count += len(keys)
                
                if cursor == 0:
                    break
            
            logger.info(f"Invalidated {count} cache entries matching: {pattern}")
            
        except Exception as e:
            logger.error(f"Error invalidating cache: {e}", exc_info=True)
    
    async def invalidate_all_fast_cache(self):
        """Invalidate all fast pipeline cache entries."""
        await self.invalidate_pattern("fast:*")
