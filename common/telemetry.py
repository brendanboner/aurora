"""
OpenTelemetry instrumentation for Aurora services.
Provides centralized trace and metrics configuration.
"""

import os
import logging
import hashlib
from typing import Optional, Dict, Any
from contextlib import contextmanager

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION, SERVICE_INSTANCE_ID
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

# Try multiple import paths for exporter and instrumentation (different package versions)
OTLPSpanExporter = None
OTLPMetricExporter = None
OTLPLogExporter = None
FastAPIInstrumentor = None
HTTPXClientInstrumentor = None
Psycopg2Instrumentor = None
RedisInstrumentor = None

try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as _OTLPSpanExporter
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter as _OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter as _OTLPLogExporter
    OTLPSpanExporter = _OTLPSpanExporter
    OTLPMetricExporter = _OTLPMetricExporter
    OTLPLogExporter = _OTLPLogExporter
except ImportError:
    try:
        from opentelemetry.exporter.otlp.trace_exporter import OTLPSpanExporter as _OTLPSpanExporter
        from opentelemetry.exporter.otlp.metric_exporter import OTLPMetricExporter as _OTLPMetricExporter
        OTLPSpanExporter = _OTLPSpanExporter
        OTLPMetricExporter = _OTLPMetricExporter
    except ImportError:
        pass

try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor as _FastAPIInstrumentor
    FastAPIInstrumentor = _FastAPIInstrumentor
except ImportError:
    pass

try:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor as _HTTPXClientInstrumentor
    HTTPXClientInstrumentor = _HTTPXClientInstrumentor
except ImportError:
    pass

try:
    from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor as _Psycopg2Instrumentor
    Psycopg2Instrumentor = _Psycopg2Instrumentor
except ImportError:
    pass

try:
    from opentelemetry.instrumentation.redis import RedisInstrumentor as _RedisInstrumentor
    RedisInstrumentor = _RedisInstrumentor
except ImportError:
    pass
from opentelemetry.trace import Status, StatusCode

logger = logging.getLogger(__name__)

# Global flags
_instrumentation_enabled = False
_tracer: Optional[trace.Tracer] = None
_meter: Optional[metrics.Meter] = None


def init_telemetry(
    service_name: str,
    service_version: str = "1.0.0",
    otlp_endpoint: Optional[str] = None,
    sample_rate: Optional[float] = None,
) -> tuple[Optional[trace.Tracer], Optional[metrics.Meter]]:
    """
    Initialize OpenTelemetry instrumentation for a service.
    
    Args:
        service_name: Name of the service (e.g., 'aurora-backend')
        service_version: Version of the service
        otlp_endpoint: OTLP collector endpoint (default: from env OTEL_ENDPOINT)
        sample_rate: Trace sampling rate 0.0-1.0 (default: from env OTEL_SAMPLE_RATE or 1.0)
    
    Returns:
        Tuple of (tracer, meter) or (None, None) if disabled
    """
    global _instrumentation_enabled, _tracer, _meter
    
    # Check if telemetry is enabled
    enabled = os.getenv("OTEL_ENABLED", "true").lower() in ("true", "1", "yes")
    if not enabled:
        logger.info("OpenTelemetry instrumentation disabled via OTEL_ENABLED")
        return None, None
    
    # Get configuration from environment
    if otlp_endpoint is None:
        otlp_endpoint = os.getenv("OTEL_ENDPOINT", "http://otel-collector:4317")
    
    if sample_rate is None:
        sample_rate = float(os.getenv("OTEL_SAMPLE_RATE", "1.0"))
    
    try:
        # Create resource with service information
        resource = Resource.create({
            SERVICE_NAME: service_name,
            SERVICE_VERSION: service_version,
            SERVICE_INSTANCE_ID: os.getenv("HOSTNAME", "unknown"),
            "environment": os.getenv("ENVIRONMENT", "development"),
        })
        
        # Configure tracing
        trace_provider = TracerProvider(
            resource=resource,
            sampler=_create_sampler(sample_rate),
        )
        
        try:
            if OTLPSpanExporter:
                span_exporter = OTLPSpanExporter(
                    endpoint=otlp_endpoint,
                    insecure=True,  # Use TLS in production
                    timeout=10,
                )
                span_processor = BatchSpanProcessor(
                    span_exporter,
                    max_queue_size=2048,
                    max_export_batch_size=512,
                    schedule_delay_millis=5000,
                )
                trace_provider.add_span_processor(span_processor)
        except Exception as e:
            logger.warning(f"Failed to configure trace exporter: {e}. Tracing will be disabled.")
        
        trace.set_tracer_provider(trace_provider)
        _tracer = trace.get_tracer(service_name, service_version)
        
        # Configure metrics
        try:
            if OTLPMetricExporter:
                metric_exporter = OTLPMetricExporter(
                    endpoint=otlp_endpoint,
                    insecure=True,
                    timeout=10,
                )
                metric_reader = PeriodicExportingMetricReader(
                    metric_exporter,
                    export_interval_millis=15000,  # Export every 15s
                )
                meter_provider = MeterProvider(
                    resource=resource,
                    metric_readers=[metric_reader],
                )
                metrics.set_meter_provider(meter_provider)
                _meter = metrics.get_meter(service_name, service_version)
        except Exception as e:
            logger.warning(f"Failed to configure metrics exporter: {e}. Metrics will be disabled.")
        
        # Configure logging
        try:
            if OTLPLogExporter:
                log_exporter = OTLPLogExporter(
                    endpoint=otlp_endpoint,
                    insecure=True,
                    timeout=10,
                )
                logger_provider = LoggerProvider(resource=resource)
                logger_provider.add_log_record_processor(
                    BatchLogRecordProcessor(log_exporter)
                )
                set_logger_provider(logger_provider)
                
                # Attach OTLP handler to root logger
                handler = LoggingHandler(
                    level=logging.INFO,
                    logger_provider=logger_provider,
                )
                logging.getLogger().addHandler(handler)
                logger.debug("Configured OpenTelemetry log export to OTLP")
        except Exception as e:
            logger.warning(f"Failed to configure log exporter: {e}. Log export will be disabled.")
        
        # Auto-instrument common libraries
        try:
            HTTPXClientInstrumentor().instrument()
            logger.debug("Instrumented httpx")
        except Exception as e:
            logger.debug(f"Could not instrument httpx: {e}")
        
        try:
            Psycopg2Instrumentor().instrument()
            logger.debug("Instrumented psycopg2")
        except Exception as e:
            logger.debug(f"Could not instrument psycopg2: {e}")
        
        try:
            RedisInstrumentor().instrument()
            logger.debug("Instrumented redis")
        except Exception as e:
            logger.debug(f"Could not instrument redis: {e}")
        
        _instrumentation_enabled = True
        logger.info(f"OpenTelemetry instrumentation enabled for {service_name} (sample_rate={sample_rate})")
        
        return _tracer, _meter
    
    except Exception as e:
        logger.error(f"Failed to initialize OpenTelemetry: {e}", exc_info=True)
        return None, None


def _create_sampler(sample_rate: float):
    """Create a sampler based on sample rate."""
    from opentelemetry.sdk.trace.sampling import (
        TraceIdRatioBased,
        ParentBased,
    )
    
    if sample_rate >= 1.0:
        from opentelemetry.sdk.trace.sampling import ALWAYS_ON
        return ParentBased(root=ALWAYS_ON)
    elif sample_rate <= 0.0:
        from opentelemetry.sdk.trace.sampling import ALWAYS_OFF
        return ParentBased(root=ALWAYS_OFF)
    else:
        return ParentBased(root=TraceIdRatioBased(sample_rate))


def instrument_fastapi(app):
    """Instrument a FastAPI application."""
    if _instrumentation_enabled and FastAPIInstrumentor:
        try:
            FastAPIInstrumentor.instrument_app(app)
            logger.debug("Instrumented FastAPI application")
        except Exception as e:
            logger.warning(f"Failed to instrument FastAPI: {e}")


def get_tracer() -> Optional[trace.Tracer]:
    """Get the global tracer instance."""
    return _tracer


def get_meter() -> Optional[metrics.Meter]:
    """Get the global meter instance."""
    return _meter


@contextmanager
def trace_operation(name: str, attributes: Optional[Dict[str, Any]] = None):
    """
    Context manager for tracing an operation.
    
    Usage:
        with trace_operation("process_document", {"doc_id": doc_id}):
            # Your code here
            pass
    """
    if _tracer is None:
        yield None
        return
    
    with _tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, value)
        try:
            yield span
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


def hash_text(text: str, prefix: str = "") -> str:
    """
    Create a SHA256 hash of text for safe logging.
    
    Args:
        text: Text to hash
        prefix: Optional prefix for the hash
    
    Returns:
        Hash string like "sha256:abc123..."
    """
    if not text:
        return ""
    hash_value = hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
    return f"{prefix}sha256:{hash_value}" if prefix else f"sha256:{hash_value}"


def sanitize_cypher_query(query: str, hash_queries: bool = False) -> str:
    """
    Sanitize Cypher query for observability.
    
    Args:
        query: The Cypher query
        hash_queries: If True, return hash. If False, return query without parameters.
    
    Returns:
        Sanitized query or hash
    """
    if hash_queries:
        return hash_text(query, prefix="cypher_")
    else:
        # Return query text without parameters (already safe)
        return query.strip()


def record_exception(exception: Exception, span: Optional[trace.Span] = None):
    """Record an exception in the current span."""
    if span:
        span.set_status(Status(StatusCode.ERROR, str(exception)))
        span.record_exception(exception)


def log_structured(
    level: str,
    message: str,
    attributes: Optional[Dict[str, Any]] = None,
    logger_name: str = "aurora",
):
    """
    Log structured data that will be sent to Loki via OpenTelemetry.
    
    Args:
        level: Log level (INFO, WARNING, ERROR, etc.)
        message: Log message
        attributes: Additional structured attributes
        logger_name: Logger name for categorization
    """
    log = logging.getLogger(logger_name)
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    # Add attributes as extra fields for structured logging
    extra = {"attributes": attributes} if attributes else {}
    log.log(log_level, message, extra=extra)


def log_llm_request(
    prompt_type: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    duration_ms: float,
    status: str = "success",
    error: Optional[str] = None,
):
    """
    Log LLM request details to Loki.
    
    Args:
        prompt_type: Type of prompt (e.g., 'linkedin_parse', 'query_parse')
        model: Model name
        prompt_tokens: Number of prompt tokens
        completion_tokens: Number of completion tokens
        duration_ms: Request duration in milliseconds
        status: Request status ('success' or 'error')
        error: Error message if failed
    """
    attributes = {
        "llm.prompt_type": prompt_type,
        "llm.model": model,
        "llm.prompt_tokens": prompt_tokens,
        "llm.completion_tokens": completion_tokens,
        "llm.total_tokens": prompt_tokens + completion_tokens,
        "llm.duration_ms": duration_ms,
        "llm.status": status,
    }
    if error:
        attributes["llm.error"] = error
    
    level = "ERROR" if status == "error" else "INFO"
    message = f"LLM request completed: {prompt_type} using {model} ({prompt_tokens + completion_tokens} tokens in {duration_ms:.1f}ms)"
    log_structured(level, message, attributes, logger_name="aurora.llm")


def log_neo4j_query(
    query_type: str,
    cypher: str,
    duration_ms: float,
    rows_returned: int,
    status: str = "success",
    error: Optional[str] = None,
):
    """
    Log Neo4j query details to Loki.
    
    Args:
        query_type: Type of query ('read' or 'write')
        cypher: Cypher query (will be hashed if configured)
        duration_ms: Query duration in milliseconds
        rows_returned: Number of rows returned
        status: Query status ('success' or 'error')
        error: Error message if failed
    """
    hash_queries = os.getenv("OTEL_HASH_CYPHER_QUERIES", "false").lower() in ("true", "1", "yes")
    
    attributes = {
        "graph.query_type": query_type,
        "graph.duration_ms": duration_ms,
        "graph.rows_returned": rows_returned,
        "graph.status": status,
    }
    
    # Extract first meaningful part of query for context
    query_preview = cypher.strip().split('\n')[0][:80] if cypher else "unknown"
    
    if hash_queries:
        attributes["graph.cypher_hash"] = hash_text(cypher, prefix="cypher_")
        query_context = f"hash:{hash_text(cypher, prefix='cypher_')[:12]}"
    else:
        attributes["graph.cypher"] = cypher[:500]  # Truncate to 500 chars
        query_context = query_preview
    
    if error:
        attributes["graph.error"] = error
    
    # Use DEBUG for successful queries, ERROR for failures
    # Use INFO only for slow queries (>100ms) or large result sets (>1000 rows)
    if status == "error":
        level = "ERROR"
        message = f"Neo4j {query_type} query FAILED in {duration_ms:.1f}ms: {query_context}"
    elif duration_ms > 100 or rows_returned > 1000:
        level = "INFO"
        message = f"Neo4j {query_type} query (SLOW/LARGE): {rows_returned} rows in {duration_ms:.1f}ms - {query_context}"
    else:
        level = "DEBUG"
        message = f"Neo4j {query_type}: {rows_returned} rows in {duration_ms:.1f}ms - {query_context}"
    
    log_structured(level, message, attributes, logger_name="aurora.neo4j")
