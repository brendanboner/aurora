"""Oracle Cache - Multi-level caching for Oracle Service.

Phase 4 of Oracle Service implementation.

This module provides a multi-level caching layer using Redis to improve
performance and reduce redundant computations. It caches:
- Query responses (full results for identical queries)
- Query embeddings (avoid re-embedding the same query)
- Graph context (entity relationships)
- Documents (frequently accessed document metadata)
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Any, TypeVar, Callable
from functools import wraps

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None

from src.settings import settings

logger = logging.getLogger(__name__)

T = TypeVar('T')


# Cache TTLs in seconds
class CacheTTL:
    """Cache time-to-live constants."""
    QUERY_RESPONSE = 300  # 5 minutes - full query responses
    EMBEDDING = 3600  # 1 hour - query embeddings
    GRAPH_CONTEXT = 900  # 15 minutes - entity relationships
    DOCUMENT = 1800  # 30 minutes - document metadata
    ENTITY_RESOLUTION = 600  # 10 minutes - resolved entities


# Cache key prefixes
class CachePrefix:
    """Cache key prefix constants."""
    QUERY = "oracle:query:"
    EMBEDDING = "oracle:embed:"
    GRAPH_CONTEXT = "oracle:graph:"
    DOCUMENT = "oracle:doc:"
    ENTITY = "oracle:entity:"


@dataclass
class CacheStats:
    """Cache statistics for monitoring."""
    hits: int = 0
    misses: int = 0
    errors: int = 0
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class OracleCache:
    """
    Multi-level caching for Oracle Service using Redis.
    
    Provides caching for:
    - Full query responses (identical queries return cached results)
    - Query embeddings (avoid re-computing embeddings)
    - Graph context (cached entity relationships)
    - Document metadata (frequently accessed docs)
    
    Thread-safe and handles Redis unavailability gracefully.
    """
    
    _instance: Optional['OracleCache'] = None
    _redis_client: Optional['redis.Redis'] = None
    
    def __init__(self):
        """Initialize the cache (use get_cache() instead for singleton)."""
        self.enabled = settings.cache_enabled and REDIS_AVAILABLE
        self.stats = {
            "query": CacheStats(),
            "embedding": CacheStats(),
            "graph": CacheStats(),
            "document": CacheStats(),
        }
        self._connected = False
    
    @classmethod
    async def get_cache(cls) -> 'OracleCache':
        """Get or create the singleton cache instance."""
        if cls._instance is None:
            cls._instance = OracleCache()
            await cls._instance._connect()
        return cls._instance
    
    async def _connect(self) -> None:
        """Connect to Redis."""
        if not self.enabled:
            logger.info("Cache is disabled")
            return
        
        try:
            self._redis_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                password=settings.redis_password or None,
                db=settings.redis_db,
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
            )
            # Test connection
            await self._redis_client.ping()
            self._connected = True
            logger.info(f"Connected to Redis at {settings.redis_host}:{settings.redis_port}")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Caching disabled.")
            self._connected = False
            self._redis_client = None
    
    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis_client:
            await self._redis_client.close()
            self._connected = False
    
    def is_available(self) -> bool:
        """Check if cache is available."""
        return self.enabled and self._connected and self._redis_client is not None
    
    # ==================== Query Response Cache ====================
    
    async def get_query_response(
        self,
        query: str,
        mode: str,
        options_hash: str,
    ) -> Optional[dict]:
        """
        Get cached query response.
        
        Args:
            query: The user query
            mode: Response mode (retrieval/answer)
            options_hash: Hash of query options
            
        Returns:
            Cached response dict or None
        """
        if not self.is_available():
            return None
        
        cache_key = self._query_key(query, mode, options_hash)
        
        try:
            cached = await self._redis_client.get(cache_key)
            if cached:
                self.stats["query"].hits += 1
                logger.debug(f"Query cache hit: {cache_key[:50]}...")
                return json.loads(cached)
            
            self.stats["query"].misses += 1
            return None
            
        except Exception as e:
            logger.warning(f"Query cache get error: {e}")
            self.stats["query"].errors += 1
            return None
    
    async def set_query_response(
        self,
        query: str,
        mode: str,
        options_hash: str,
        response: dict,
        ttl: int = CacheTTL.QUERY_RESPONSE,
    ) -> bool:
        """
        Cache a query response.
        
        Args:
            query: The user query
            mode: Response mode
            options_hash: Hash of query options
            response: Response to cache
            ttl: Time-to-live in seconds
            
        Returns:
            True if cached successfully
        """
        if not self.is_available():
            return False
        
        cache_key = self._query_key(query, mode, options_hash)
        
        try:
            await self._redis_client.setex(
                cache_key,
                ttl,
                json.dumps(response, default=str)
            )
            logger.debug(f"Query cached: {cache_key[:50]}...")
            return True
            
        except Exception as e:
            logger.warning(f"Query cache set error: {e}")
            self.stats["query"].errors += 1
            return False
    
    def _query_key(self, query: str, mode: str, options_hash: str) -> str:
        """Generate cache key for query."""
        query_hash = hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]
        return f"{CachePrefix.QUERY}{mode}:{query_hash}:{options_hash}"
    
    # ==================== Embedding Cache ====================
    
    async def get_embedding(self, text: str) -> Optional[list[float]]:
        """
        Get cached embedding for text.
        
        Args:
            text: Text to get embedding for
            
        Returns:
            Cached embedding list or None
        """
        if not self.is_available():
            return None
        
        cache_key = self._embedding_key(text)
        
        try:
            cached = await self._redis_client.get(cache_key)
            if cached:
                self.stats["embedding"].hits += 1
                return json.loads(cached)
            
            self.stats["embedding"].misses += 1
            return None
            
        except Exception as e:
            logger.warning(f"Embedding cache get error: {e}")
            self.stats["embedding"].errors += 1
            return None
    
    async def set_embedding(
        self,
        text: str,
        embedding: list[float],
        ttl: int = CacheTTL.EMBEDDING,
    ) -> bool:
        """
        Cache an embedding.
        
        Args:
            text: Original text
            embedding: Embedding vector
            ttl: Time-to-live in seconds
            
        Returns:
            True if cached successfully
        """
        if not self.is_available():
            return False
        
        cache_key = self._embedding_key(text)
        
        try:
            await self._redis_client.setex(
                cache_key,
                ttl,
                json.dumps(embedding)
            )
            return True
            
        except Exception as e:
            logger.warning(f"Embedding cache set error: {e}")
            self.stats["embedding"].errors += 1
            return False
    
    def _embedding_key(self, text: str) -> str:
        """Generate cache key for embedding."""
        text_hash = hashlib.sha256(text.lower().strip().encode()).hexdigest()[:32]
        return f"{CachePrefix.EMBEDDING}{text_hash}"
    
    # ==================== Graph Context Cache ====================
    
    async def get_graph_context(self, document_urls: list[str]) -> Optional[dict]:
        """
        Get cached graph context for a set of documents.
        
        Args:
            document_urls: List of document URLs
            
        Returns:
            Cached graph context dict or None
        """
        if not self.is_available():
            return None
        
        cache_key = self._graph_context_key(document_urls)
        
        try:
            cached = await self._redis_client.get(cache_key)
            if cached:
                self.stats["graph"].hits += 1
                return json.loads(cached)
            
            self.stats["graph"].misses += 1
            return None
            
        except Exception as e:
            logger.warning(f"Graph context cache get error: {e}")
            self.stats["graph"].errors += 1
            return None
    
    async def set_graph_context(
        self,
        document_urls: list[str],
        context: dict,
        ttl: int = CacheTTL.GRAPH_CONTEXT,
    ) -> bool:
        """
        Cache graph context for a set of documents.
        
        Args:
            document_urls: List of document URLs
            context: Graph context to cache
            ttl: Time-to-live in seconds
            
        Returns:
            True if cached successfully
        """
        if not self.is_available():
            return False
        
        cache_key = self._graph_context_key(document_urls)
        
        try:
            await self._redis_client.setex(
                cache_key,
                ttl,
                json.dumps(context, default=str)
            )
            return True
            
        except Exception as e:
            logger.warning(f"Graph context cache set error: {e}")
            self.stats["graph"].errors += 1
            return False
    
    def _graph_context_key(self, document_urls: list[str]) -> str:
        """Generate cache key for graph context."""
        # Sort URLs for consistent key regardless of order
        sorted_urls = sorted(document_urls)
        urls_str = "|".join(sorted_urls[:10])  # Limit to first 10 URLs
        urls_hash = hashlib.sha256(urls_str.encode()).hexdigest()[:24]
        return f"{CachePrefix.GRAPH_CONTEXT}{urls_hash}"
    
    # ==================== Document Cache ====================
    
    async def get_document(self, url: str) -> Optional[dict]:
        """
        Get cached document metadata.
        
        Args:
            url: Document URL
            
        Returns:
            Cached document dict or None
        """
        if not self.is_available():
            return None
        
        cache_key = self._document_key(url)
        
        try:
            cached = await self._redis_client.get(cache_key)
            if cached:
                self.stats["document"].hits += 1
                return json.loads(cached)
            
            self.stats["document"].misses += 1
            return None
            
        except Exception as e:
            logger.warning(f"Document cache get error: {e}")
            self.stats["document"].errors += 1
            return None
    
    async def set_document(
        self,
        url: str,
        document: dict,
        ttl: int = CacheTTL.DOCUMENT,
    ) -> bool:
        """
        Cache document metadata.
        
        Args:
            url: Document URL
            document: Document metadata to cache
            ttl: Time-to-live in seconds
            
        Returns:
            True if cached successfully
        """
        if not self.is_available():
            return False
        
        cache_key = self._document_key(url)
        
        try:
            await self._redis_client.setex(
                cache_key,
                ttl,
                json.dumps(document, default=str)
            )
            return True
            
        except Exception as e:
            logger.warning(f"Document cache set error: {e}")
            self.stats["document"].errors += 1
            return False
    
    async def get_documents_batch(self, urls: list[str]) -> dict[str, Optional[dict]]:
        """
        Get multiple documents from cache in batch.
        
        Args:
            urls: List of document URLs
            
        Returns:
            Dict mapping URL to cached document (or None if not cached)
        """
        if not self.is_available() or not urls:
            return {url: None for url in urls}
        
        try:
            keys = [self._document_key(url) for url in urls]
            results = await self._redis_client.mget(keys)
            
            output = {}
            for url, result in zip(urls, results):
                if result:
                    self.stats["document"].hits += 1
                    output[url] = json.loads(result)
                else:
                    self.stats["document"].misses += 1
                    output[url] = None
            
            return output
            
        except Exception as e:
            logger.warning(f"Document batch cache get error: {e}")
            self.stats["document"].errors += 1
            return {url: None for url in urls}
    
    def _document_key(self, url: str) -> str:
        """Generate cache key for document."""
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:24]
        return f"{CachePrefix.DOCUMENT}{url_hash}"
    
    # ==================== Entity Resolution Cache ====================
    
    async def get_resolved_entity(self, name: str, entity_type: str) -> Optional[dict]:
        """
        Get cached entity resolution result.
        
        Args:
            name: Entity name to look up
            entity_type: Type of entity (topic, organization, person)
            
        Returns:
            Cached resolution result or None
        """
        if not self.is_available():
            return None
        
        cache_key = self._entity_key(name, entity_type)
        
        try:
            cached = await self._redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
            return None
            
        except Exception as e:
            logger.warning(f"Entity cache get error: {e}")
            return None
    
    async def set_resolved_entity(
        self,
        name: str,
        entity_type: str,
        resolution: dict,
        ttl: int = CacheTTL.ENTITY_RESOLUTION,
    ) -> bool:
        """
        Cache entity resolution result.
        
        Args:
            name: Entity name
            entity_type: Type of entity
            resolution: Resolution result to cache
            ttl: Time-to-live in seconds
            
        Returns:
            True if cached successfully
        """
        if not self.is_available():
            return False
        
        cache_key = self._entity_key(name, entity_type)
        
        try:
            await self._redis_client.setex(
                cache_key,
                ttl,
                json.dumps(resolution, default=str)
            )
            return True
            
        except Exception as e:
            logger.warning(f"Entity cache set error: {e}")
            return False
    
    def _entity_key(self, name: str, entity_type: str) -> str:
        """Generate cache key for entity."""
        name_hash = hashlib.sha256(name.lower().strip().encode()).hexdigest()[:16]
        return f"{CachePrefix.ENTITY}{entity_type}:{name_hash}"
    
    # ==================== Document Content Cache (Phase 5) ====================
    
    async def get_document_content(self, url: str) -> Optional[str]:
        """
        Get cached full document content.
        
        This is used by the Phase 5 enhance feature to cache fetched
        document content to avoid repeated fetches.
        
        Args:
            url: Document URL
            
        Returns:
            Cached content string or None
        """
        if not self.is_available():
            return None
        
        cache_key = self._document_content_key(url)
        
        try:
            cached = await self._redis_client.get(cache_key)
            if cached:
                self.stats["document"].hits += 1
                logger.debug(f"Document content cache hit: {url[:50]}...")
                return cached
            
            self.stats["document"].misses += 1
            return None
            
        except Exception as e:
            logger.warning(f"Document content cache get error: {e}")
            self.stats["document"].errors += 1
            return None
    
    async def set_document_content(
        self,
        url: str,
        content: str,
        ttl: int = 3600,  # 1 hour default
    ) -> bool:
        """
        Cache full document content.
        
        Args:
            url: Document URL
            content: Full document content
            ttl: Time-to-live in seconds (default 1 hour)
            
        Returns:
            True if cached successfully
        """
        if not self.is_available():
            return False
        
        cache_key = self._document_content_key(url)
        
        try:
            await self._redis_client.setex(
                cache_key,
                ttl,
                content
            )
            logger.debug(f"Document content cached: {url[:50]}...")
            return True
            
        except Exception as e:
            logger.warning(f"Document content cache set error: {e}")
            self.stats["document"].errors += 1
            return False
    
    def _document_content_key(self, url: str) -> str:
        """Generate cache key for document content."""
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:24]
        return f"{CachePrefix.DOCUMENT}content:{url_hash}"
    
    # ==================== Cache Management ====================
    
    async def invalidate_query_cache(self, query: str = None) -> int:
        """
        Invalidate query cache entries.
        
        Args:
            query: Specific query to invalidate (None = all queries)
            
        Returns:
            Number of keys deleted
        """
        if not self.is_available():
            return 0
        
        try:
            if query:
                query_hash = hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]
                pattern = f"{CachePrefix.QUERY}*:{query_hash}:*"
            else:
                pattern = f"{CachePrefix.QUERY}*"
            
            keys = []
            async for key in self._redis_client.scan_iter(match=pattern):
                keys.append(key)
            
            if keys:
                await self._redis_client.delete(*keys)
            
            return len(keys)
            
        except Exception as e:
            logger.warning(f"Cache invalidation error: {e}")
            return 0
    
    async def get_stats(self) -> dict:
        """Get cache statistics."""
        stats = {}
        for name, cache_stats in self.stats.items():
            stats[name] = {
                "hits": cache_stats.hits,
                "misses": cache_stats.misses,
                "errors": cache_stats.errors,
                "hit_rate": round(cache_stats.hit_rate, 3),
            }
        
        # Add Redis info if connected
        if self.is_available():
            try:
                info = await self._redis_client.info("memory")
                stats["redis"] = {
                    "used_memory": info.get("used_memory_human", "unknown"),
                    "connected": True,
                }
            except Exception:
                stats["redis"] = {"connected": True}
        else:
            stats["redis"] = {"connected": False}
        
        return stats
    
    async def health_check(self) -> dict:
        """Check cache health."""
        if not self.enabled:
            return {"status": "disabled", "reason": "Cache disabled in settings"}
        
        if not REDIS_AVAILABLE:
            return {"status": "unavailable", "reason": "redis package not installed"}
        
        if not self._connected:
            return {"status": "disconnected", "reason": "Not connected to Redis"}
        
        try:
            await self._redis_client.ping()
            return {"status": "healthy", "connected": True}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}


# ==================== Helper Functions ====================

def hash_options(options: dict) -> str:
    """
    Generate a hash for query options.
    
    Args:
        options: Query options dict
        
    Returns:
        Short hash string
    """
    if not options:
        return "default"
    
    # Sort keys for consistent hashing
    sorted_options = json.dumps(options, sort_keys=True, default=str)
    return hashlib.sha256(sorted_options.encode()).hexdigest()[:12]


async def cached_embedding(
    text: str,
    embed_fn: Callable[[str], list[float]],
) -> list[float]:
    """
    Get embedding with caching.
    
    Args:
        text: Text to embed
        embed_fn: Function to compute embedding if not cached
        
    Returns:
        Embedding vector
    """
    cache = await OracleCache.get_cache()
    
    # Try cache first
    cached = await cache.get_embedding(text)
    if cached is not None:
        return cached
    
    # Compute embedding
    embedding = await embed_fn(text)
    
    # Cache result
    await cache.set_embedding(text, embedding)
    
    return embedding


# Singleton accessor
async def get_cache() -> OracleCache:
    """Get the Oracle cache instance."""
    return await OracleCache.get_cache()
