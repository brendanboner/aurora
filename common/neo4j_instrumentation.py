"""
Neo4j instrumentation for OpenTelemetry.
Wraps Neo4j client to add tracing and metrics.
"""

import time
import os
from typing import Optional, List, Dict, Any
from functools import wraps

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .telemetry import get_tracer, get_meter, hash_text, sanitize_cypher_query

# Get configuration
HASH_CYPHER_QUERIES = os.getenv("OTEL_HASH_CYPHER_QUERIES", "false").lower() in ("true", "1", "yes")


def instrument_neo4j_client(client_class):
    """
    Decorator to instrument Neo4j client class.
    
    Usage:
        @instrument_neo4j_client
        class Neo4jClient:
            ...
    """
    
    original_execute_query = client_class.execute_query
    original_execute_write = client_class.execute_write
    
    def execute_query_instrumented(self, query: str, parameters: Optional[Dict] = None) -> List[Dict]:
        return _execute_with_instrumentation(
            self, original_execute_query, query, parameters, query_type="read"
        )
    
    def execute_write_instrumented(self, query: str, parameters: Optional[Dict] = None) -> List[Dict]:
        return _execute_with_instrumentation(
            self, original_execute_write, query, parameters, query_type="write"
        )
    
    client_class.execute_query = execute_query_instrumented
    client_class.execute_write = execute_write_instrumented
    
    return client_class


def _execute_with_instrumentation(
    client_instance,
    original_method,
    query: str,
    parameters: Optional[Dict],
    query_type: str,
) -> List[Dict]:
    """Execute Neo4j query with instrumentation."""
    
    tracer = get_tracer()
    meter = get_meter()
    
    # Create metrics
    if meter:
        query_counter = meter.create_counter(
            "graph.query.count",
            description="Number of graph queries executed",
            unit="1",
        )
        duration_histogram = meter.create_histogram(
            "graph.query.duration_ms",
            description="Graph query execution duration",
            unit="ms",
        )
        rows_histogram = meter.create_histogram(
            "graph.query.rows_returned",
            description="Number of rows returned by graph query",
            unit="1",
        )
    
    # Prepare attributes
    cypher_repr = sanitize_cypher_query(query, hash_queries=HASH_CYPHER_QUERIES)
    attributes = {
        "db.system": "neo4j",
        "db.operation": query_type,
        "graph.query_type": query_type,
    }
    
    if HASH_CYPHER_QUERIES:
        attributes["graph.cypher_hash"] = cypher_repr
    else:
        # Store full query text (no parameters, already safe)
        attributes["db.statement"] = cypher_repr
        attributes["graph.cypher_hash"] = hash_text(query, prefix="cypher_")
    
    # Execute with tracing
    start_time = time.time()
    
    if tracer:
        with tracer.start_as_current_span("neo4j.query", attributes=attributes) as span:
            try:
                result = original_method(client_instance, query, parameters)
                row_count = len(result) if result else 0
                
                span.set_attribute("graph.query.rows_returned", row_count)
                span.set_status(Status(StatusCode.OK))
                
                # Record metrics
                duration_ms = (time.time() - start_time) * 1000
                if meter:
                    metric_attrs = {
                        "graph.query_type": query_type,
                        "graph.cypher_hash": attributes["graph.cypher_hash"],
                    }
                    query_counter.add(1, metric_attrs)
                    duration_histogram.record(duration_ms, metric_attrs)
                    rows_histogram.record(row_count, metric_attrs)
                
                return result
                
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                
                # Record error metric
                if meter:
                    query_counter.add(1, {
                        "graph.query_type": query_type,
                        "graph.cypher_hash": attributes["graph.cypher_hash"],
                        "error": "true",
                    })
                
                raise
    else:
        # No tracer, execute without instrumentation
        result = original_method(client_instance, query, parameters)
        
        # Still record metrics if available
        if meter:
            row_count = len(result) if result else 0
            duration_ms = (time.time() - start_time) * 1000
            metric_attrs = {
                "graph.query_type": query_type,
                "graph.cypher_hash": hash_text(query, prefix="cypher_"),
            }
            query_counter.add(1, metric_attrs)
            duration_histogram.record(duration_ms, metric_attrs)
            rows_histogram.record(row_count, metric_attrs)
        
        return result
