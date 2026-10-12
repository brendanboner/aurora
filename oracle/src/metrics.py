"""
Oracle Service Prometheus Metrics.

Defines custom metrics for Oracle-specific tracking:
- Query counts by intent and mode
- Confidence score distribution
- Document retrieval counts
- Cache hit rates
- Latency measurements
- User feedback tracking

Phase 6 of Oracle Service implementation.
"""

import logging
from typing import Optional
from enum import Enum

from common.telemetry import get_meter

logger = logging.getLogger(__name__)

# Metric instances (initialized lazily)
_metrics_initialized = False
_query_counter = None
_confidence_histogram = None
_documents_histogram = None
_suggestions_counter = None
_query_latency_histogram = None
_enhance_latency_histogram = None
_cache_hit_counter = None
_feedback_counter = None
_retrieval_strategy_counter = None


class MetricLabels:
    """Standard label names for Oracle metrics."""
    INTENT = "oracle.intent"
    MODE = "oracle.mode"
    CACHE_HIT = "oracle.cache_hit"
    HAS_SUGGESTIONS = "oracle.has_suggestions"
    CONFIDENCE_LEVEL = "oracle.confidence_level"
    FEEDBACK_TYPE = "oracle.feedback_type"
    STRATEGY = "oracle.retrieval_strategy"
    ERROR = "oracle.error"


def _initialize_metrics():
    """Initialize all Oracle metrics. Called lazily on first use."""
    global _metrics_initialized, _query_counter, _confidence_histogram
    global _documents_histogram, _suggestions_counter, _query_latency_histogram
    global _enhance_latency_histogram, _cache_hit_counter, _feedback_counter
    global _retrieval_strategy_counter
    
    if _metrics_initialized:
        return
    
    meter = get_meter()
    if not meter:
        logger.warning("Meter not available, metrics will be disabled")
        _metrics_initialized = True
        return
    
    try:
        # Query counts by intent and mode
        _query_counter = meter.create_counter(
            name="oracle.query.count",
            description="Number of Oracle queries by intent and mode",
            unit="1",
        )
        
        # Confidence score distribution (0.0 to 1.0)
        _confidence_histogram = meter.create_histogram(
            name="oracle.confidence.score",
            description="Distribution of answer confidence scores",
            unit="1",
        )
        
        # Documents returned per query
        _documents_histogram = meter.create_histogram(
            name="oracle.documents.returned",
            description="Number of documents returned per query",
            unit="1",
        )
        
        # Suggestions shown counter
        _suggestions_counter = meter.create_counter(
            name="oracle.suggestions.shown",
            description="Number of queries where refinement suggestions were shown",
            unit="1",
        )
        
        # Query latency (milliseconds)
        _query_latency_histogram = meter.create_histogram(
            name="oracle.query.latency_ms",
            description="Query processing latency in milliseconds",
            unit="ms",
        )
        
        # Enhance latency (milliseconds)
        _enhance_latency_histogram = meter.create_histogram(
            name="oracle.enhance.latency_ms",
            description="Enhance request processing latency in milliseconds",
            unit="ms",
        )
        
        # Cache hit/miss counter
        _cache_hit_counter = meter.create_counter(
            name="oracle.cache.operations",
            description="Cache hit/miss counts",
            unit="1",
        )
        
        # User feedback counter
        _feedback_counter = meter.create_counter(
            name="oracle.feedback.count",
            description="User feedback counts (helpful/not_helpful)",
            unit="1",
        )
        
        # Retrieval strategy usage
        _retrieval_strategy_counter = meter.create_counter(
            name="oracle.retrieval.strategy",
            description="Usage count by retrieval strategy",
            unit="1",
        )
        
        _metrics_initialized = True
        logger.info("Oracle metrics initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize Oracle metrics: {e}")
        _metrics_initialized = True  # Don't retry on failure


def record_query_metrics(
    intent: str,
    mode: str,
    documents_count: int,
    confidence_score: Optional[float],
    latency_ms: float,
    cache_hit: bool,
    has_suggestions: bool,
    strategies_used: list[str],
    error: bool = False,
):
    """
    Record metrics for a completed query.
    
    Args:
        intent: Query intent (e.g., 'entity_focused', 'topic_discovery')
        mode: Response mode ('answer' or 'retrieval')
        documents_count: Number of documents returned
        confidence_score: Answer confidence score (0.0-1.0) or None
        latency_ms: Processing time in milliseconds
        cache_hit: Whether response was served from cache
        has_suggestions: Whether query suggestions were shown
        strategies_used: List of retrieval strategies used
        error: Whether the query resulted in an error
    """
    _initialize_metrics()
    
    if not _query_counter:
        return
    
    try:
        # Base labels for all metrics
        base_labels = {
            MetricLabels.INTENT: intent,
            MetricLabels.MODE: mode,
            MetricLabels.CACHE_HIT: str(cache_hit).lower(),
            MetricLabels.ERROR: str(error).lower(),
        }
        
        # Record query count
        _query_counter.add(1, base_labels)
        
        # Record latency
        _query_latency_histogram.record(latency_ms, base_labels)
        
        # Record documents returned
        _documents_histogram.record(documents_count, {
            MetricLabels.INTENT: intent,
            MetricLabels.MODE: mode,
        })
        
        # Record confidence score (only for answer mode)
        if confidence_score is not None and _confidence_histogram:
            confidence_level = _get_confidence_level(confidence_score)
            _confidence_histogram.record(confidence_score, {
                MetricLabels.INTENT: intent,
                MetricLabels.CONFIDENCE_LEVEL: confidence_level,
            })
        
        # Record suggestions shown
        if has_suggestions and _suggestions_counter:
            _suggestions_counter.add(1, {
                MetricLabels.INTENT: intent,
                MetricLabels.MODE: mode,
            })
        
        # Record cache operations
        if _cache_hit_counter:
            _cache_hit_counter.add(1, {
                MetricLabels.CACHE_HIT: str(cache_hit).lower(),
            })
        
        # Record retrieval strategies used
        if _retrieval_strategy_counter and strategies_used:
            for strategy in strategies_used:
                _retrieval_strategy_counter.add(1, {
                    MetricLabels.STRATEGY: strategy,
                    MetricLabels.INTENT: intent,
                })
                
    except Exception as e:
        logger.warning(f"Failed to record query metrics: {e}")


def record_enhance_metrics(
    latency_ms: float,
    documents_fetched: int,
    chunks_used: int,
    confidence_score: Optional[float],
    error: bool = False,
):
    """
    Record metrics for an enhance request.
    
    Args:
        latency_ms: Processing time in milliseconds
        documents_fetched: Number of documents successfully fetched
        chunks_used: Number of chunks used for answer generation
        confidence_score: Answer confidence score or None
        error: Whether the request resulted in an error
    """
    _initialize_metrics()
    
    if not _enhance_latency_histogram:
        return
    
    try:
        labels = {
            MetricLabels.ERROR: str(error).lower(),
        }
        
        _enhance_latency_histogram.record(latency_ms, labels)
        
        if confidence_score is not None and _confidence_histogram:
            confidence_level = _get_confidence_level(confidence_score)
            _confidence_histogram.record(confidence_score, {
                MetricLabels.CONFIDENCE_LEVEL: confidence_level,
                "request_type": "enhance",
            })
            
    except Exception as e:
        logger.warning(f"Failed to record enhance metrics: {e}")


def record_feedback_metrics(
    feedback_type: str,
    intent: Optional[str] = None,
    mode: Optional[str] = None,
):
    """
    Record user feedback metrics.
    
    Args:
        feedback_type: Type of feedback ('helpful' or 'not_helpful')
        intent: Query intent if available
        mode: Response mode if available
    """
    _initialize_metrics()
    
    if not _feedback_counter:
        return
    
    try:
        labels = {
            MetricLabels.FEEDBACK_TYPE: feedback_type,
        }
        if intent:
            labels[MetricLabels.INTENT] = intent
        if mode:
            labels[MetricLabels.MODE] = mode
            
        _feedback_counter.add(1, labels)
        
    except Exception as e:
        logger.warning(f"Failed to record feedback metrics: {e}")


def _get_confidence_level(score: float) -> str:
    """Convert confidence score to a level label."""
    if score >= 0.75:
        return "high"
    elif score >= 0.4:
        return "medium"
    else:
        return "low"
