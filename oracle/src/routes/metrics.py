"""Prometheus metrics endpoint for Oracle Service."""

from fastapi import APIRouter, Response
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
    REGISTRY,
)

router = APIRouter(tags=["metrics"])

# Define Prometheus metrics
# These complement the OpenTelemetry metrics but are directly scrapeable by Prometheus

# Query metrics
QUERY_COUNT = Counter(
    'oracle_query_total',
    'Total number of Oracle queries',
    ['intent', 'mode', 'personalized']
)

QUERY_LATENCY = Histogram(
    'oracle_query_latency_seconds',
    'Query processing latency in seconds',
    ['intent', 'mode'],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

QUERY_CONFIDENCE = Histogram(
    'oracle_query_confidence',
    'Distribution of answer confidence scores',
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)

DOCUMENTS_RETURNED = Histogram(
    'oracle_documents_returned',
    'Number of documents returned per query',
    buckets=[0, 1, 2, 5, 10, 20, 50]
)

CACHE_HITS = Counter(
    'oracle_cache_hits_total',
    'Total cache hits',
    ['hit']  # 'true' or 'false'
)

# Feedback metrics
FEEDBACK_COUNT = Counter(
    'oracle_feedback_total',
    'Total feedback submissions',
    ['type']  # 'helpful' or 'not_helpful'
)

# Personalization metrics
PERSONALIZATION_COUNT = Counter(
    'oracle_personalization_total',
    'Total queries with personalization decisions',
    ['applied', 'reason']
)

# Active queries gauge
ACTIVE_QUERIES = Gauge(
    'oracle_active_queries',
    'Number of currently processing queries'
)


def record_query(
    intent: str,
    mode: str,
    latency_seconds: float,
    confidence: float | None,
    documents_count: int,
    cache_hit: bool,
    personalized: bool
):
    """Record metrics for a completed query."""
    QUERY_COUNT.labels(
        intent=intent,
        mode=mode,
        personalized=str(personalized).lower()
    ).inc()
    
    QUERY_LATENCY.labels(intent=intent, mode=mode).observe(latency_seconds)
    
    if confidence is not None:
        QUERY_CONFIDENCE.observe(confidence)
    
    DOCUMENTS_RETURNED.observe(documents_count)
    CACHE_HITS.labels(hit=str(cache_hit).lower()).inc()


def record_personalization(applied: bool, reason: str):
    """Record personalization decision."""
    PERSONALIZATION_COUNT.labels(
        applied=str(applied).lower(),
        reason=reason
    ).inc()


def record_feedback(feedback_type: str):
    """Record user feedback."""
    FEEDBACK_COUNT.labels(type=feedback_type).inc()


@router.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST
    )
