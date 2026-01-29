# OpenTelemetry Implementation Guide

This document describes the production-grade OpenTelemetry instrumentation added to the Aurora microservices system.

## Architecture Overview

The implementation provides comprehensive observability through:
- **Distributed Tracing**: End-to-end request tracing across all microservices
- **Metrics**: Custom business and infrastructure metrics
- **Logging**: Structured logs correlated with traces
- **Sampling**: Configurable global sampling rate
- **Privacy Controls**: Optional Cypher query hashing, no raw prompts or PII

## Observability Stack

### Infrastructure Components

All observability infrastructure is defined in `docker-compose.yml`:

1. **OpenTelemetry Collector** (Port 4317, 4318, 8889)
   - Receives traces and metrics via OTLP
   - Exports to Prometheus, Tempo, and Loki
   - Configuration: `observability/otel-collector-config.yaml`

2. **Prometheus** (Port 9090)
   - Metrics storage and querying
   - Scrapes collector every 15s
   - Configuration: `observability/prometheus.yml`

3. **Tempo** (Port 3200)
   - Distributed tracing backend
   - 48-hour trace retention
   - Configuration: `observability/tempo.yaml`

4. **Loki** (Port 3100)
   - Log aggregation and storage
   - Correlated with traces

5. **Grafana** (Port 3001)
   - Visualization dashboards
   - Pre-configured data sources
   - Configuration: `observability/grafana-datasources.yml`

### Environment Variables

All application services support the following OpenTelemetry environment variables:

```bash
OTEL_ENABLED=true                              # Enable/disable instrumentation
OTEL_ENDPOINT=http://otel-collector:4317      # OTLP gRPC endpoint
OTEL_SAMPLE_RATE=1.0                          # Sampling rate (0.0-1.0)
OTEL_HASH_CYPHER_QUERIES=false                # Hash Neo4j queries vs store full text
```

## Shared Telemetry Libraries

### Core Module: `common/telemetry.py`

Provides centralized initialization for all services:

```python
from common.telemetry import init_telemetry, instrument_fastapi

# Initialize telemetry (call once at service startup)
tracer, meter = init_telemetry(
    service_name="aurora-backend",
    service_version="1.0.0"
)

# Instrument FastAPI app
instrument_fastapi(app)
```

**Key Functions**:
- `init_telemetry()`: Initializes OTLP exporter, sets up tracing and metrics
- `instrument_fastapi()`: Auto-instruments FastAPI with HTTP tracing
- `get_tracer()`, `get_meter()`: Get tracer/meter instances
- `trace_operation()`: Context manager for manual spans
- `sanitize_cypher_query()`: Optionally hashes Cypher queries

### Neo4j Instrumentation: `common/neo4j_instrumentation.py`

Automatic instrumentation for Neo4j queries:

```python
from common.neo4j_instrumentation import instrument_neo4j_client

@instrument_neo4j_client
class Neo4jClient:
    # All execute_query() and execute_write() calls are automatically traced
    pass
```

**Emitted Metrics**:
- `graph.query.count` - Number of queries
- `graph.query.duration_ms` - Query duration
- `graph.query.rows_returned` - Result set size

**Span Attributes**:
- `db.system` = "neo4j"
- `graph.query_type` = "read" | "write"
- `graph.cypher_hash` - SHA256 hash of query (if hashing enabled)
- `db.statement` - Full Cypher query (if hashing disabled)

### LLM Instrumentation: `common/llm_instrumentation.py`

Tracks Azure OpenAI LLM calls with token usage:

```python
from common.llm_instrumentation import create_llm_span_manually

with create_llm_span_manually(
    prompt_type="query_parsing",
    model_provider="azure_openai"
) as span:
    response = client.chat.completions.create(...)
    
    # Record token usage
    if span and response.usage:
        span.set_attribute("llm.tokens.prompt", response.usage.prompt_tokens)
        span.set_attribute("llm.tokens.completion", response.usage.completion_tokens)
        span.set_attribute("llm.tokens.total", response.usage.total_tokens)
```

**Emitted Metrics**:
- `llm.request.count` - Number of LLM requests
- `llm.request.duration_ms` - Request duration
- `llm.tokens.prompt` - Prompt tokens consumed
- `llm.tokens.completion` - Completion tokens generated
- `llm.tokens.total` - Total tokens used

**Span Attributes**:
- `llm.provider` - "azure_openai"
- `llm.prompt_type` - e.g., "query_parsing", "summarization", "extract", "meta_query"
- `llm.model` - Model deployment name

### RabbitMQ Instrumentation: `common/rabbitmq_instrumentation.py`

Propagates trace context across message queues:

```python
from common.rabbitmq_instrumentation import inject_trace_context, extract_trace_context

# Producer - inject trace context into message headers
with tracer.start_as_current_span("rabbitmq.publish") as span:
    properties = inject_trace_context(pika.BasicProperties())
    channel.basic_publish(exchange, routing_key, body, properties)

# Consumer - extract trace context from message headers
def on_message(ch, method, properties, body):
    context = extract_trace_context(properties)
    with tracer.start_as_current_span("rabbitmq.process", context=context):
        # Process message
        pass
```

## Service-by-Service Implementation

### 1. Backend Service (`backend/`)

**Instrumented Components**:
- `src/api.py`: FastAPI instrumentation + orchestration metrics
- `src/services/llm_service.py`: All 3 LLM calls instrumented (query parsing, meta-query, summarization)

**Key Metrics**:
- `orchestrator.pipeline.count` - Query pipeline executions
- `orchestrator.pipeline.duration_ms` - End-to-end query duration
- `orchestrator.pipeline.total_ms` (span attribute) - Full pipeline time

**Trace Flow**:
```
HTTP Request → Query Parsing (LLM) → Neo4j Query → Summarization (LLM) → Response
```

### 2. Digester Service (`digester/`)

**Instrumented Components**:
- `digester.py`: Telemetry initialization
- `utils/llm_helpers.py`: LLM calls for metadata extraction

**Key Metrics**:
- `llm.request.count` with `prompt_type=extract`
- `llm.tokens.total` - Token usage for metadata extraction

**Trace Flow**:
```
RabbitMQ Message → Extract Trace Context → Metadata Extraction (LLM) → Neo4j Write
```

### 3. Content Creator Service (`content_creator_service/`)

**Instrumented Components**:
- `src/api.py`: FastAPI instrumentation
- `src/services/scheduler.py`: Agent execution tracking
- `src/services/feed_service.py`: Feed generation metrics

**Key Metrics**:
- `agent.execution.count` - Agent run count (by `agent.name`)
- `agent.execution.duration_ms` - Agent execution time
- `feed.generation.count` - Feed generations (by `user.id`, `feed.sort`)
- `feed.generation.duration_ms` - Feed rendering time

**Span Attributes**:
- `agent.name` - Agent handle (not ID for cardinality control)
- `agent.post.generated` - Boolean indicating success
- `agent.post.id` - Generated post ID
- `feed.items.generated` - Number of posts in feed
- `feed.content.avg_age_ms` - Average content freshness

### 4. Auth Service (`auth/`)

**Instrumented Components**:
- `auth.py`: FastAPI instrumentation

**Automatic Tracing**:
- All HTTP endpoints (login, callback, token validation)
- Outbound httpx calls to Cognito

### 5. Retriever Service (`retriever/`)

**Instrumented Components**:
- `retriever.py`: FastAPI instrumentation

**Automatic Tracing**:
- Document submission endpoints
- Scheduled scraper runs
- RabbitMQ message publishing

### 6. Curator Service (`curator/`)

**Instrumented Components**:
- `api.py`: FastAPI instrumentation

**Automatic Tracing**:
- Topic organization jobs
- Event reconciliation runs

### 7. Neo4j Client (`neo4j-client/`)

**Instrumented Components**:
- `neo4j_client/client.py`: Decorated with `@instrument_neo4j_client`

**Automatic Behavior**:
- All queries traced with duration and row counts
- Cypher queries hashed or stored based on `OTEL_HASH_CYPHER_QUERIES`

### 8. RabbitMQ Client (`rabbitmq-client/`)

**Instrumented Components**:
- `rabbitmq_client/producer.py`: Trace context injection
- `rabbitmq_client/consumer.py`: Trace context extraction

**Automatic Behavior**:
- All published messages include trace context in AMQP headers
- Consumers create child spans linked to producer spans

## Configuration

### Global Sampling

Set `OTEL_SAMPLE_RATE` environment variable (0.0 to 1.0):
- `1.0` = 100% sampling (recommended for development)
- `0.1` = 10% sampling (recommended for production)
- `0.01` = 1% sampling (high-volume production)

Sampling is applied at the root span level using `ParentBased(TraceIdRatioBased)`.

### Cypher Query Privacy

Set `OTEL_HASH_CYPHER_QUERIES` environment variable:
- `false` (default) = Store full Cypher queries in spans
- `true` = Store SHA256 hash of queries instead

### Disabling Instrumentation

Set `OTEL_ENABLED=false` to completely disable instrumentation. Services will run normally without tracing/metrics.

## Accessing Observability Data

### Grafana Dashboards (http://localhost:3001)

Default credentials: admin/admin

Pre-configured data sources:
- **Prometheus**: Metrics queries and dashboards
- **Tempo**: Distributed trace viewing
- **Loki**: Log exploration with trace correlation

### Prometheus Queries (http://localhost:9090)

Example queries:

```promql
# LLM token usage by prompt type
sum by (llm_prompt_type) (llm_tokens_total)

# Neo4j query duration P95
histogram_quantile(0.95, rate(graph_query_duration_ms_bucket[5m]))

# Agent execution rate
rate(agent_execution_count[5m])

# Query pipeline duration
histogram_quantile(0.99, rate(orchestrator_pipeline_duration_ms_bucket[5m]))
```

### Tempo Trace Queries (http://localhost:3200)

Search traces by:
- Service name (e.g., `aurora-backend`)
- Duration (e.g., `> 1s`)
- Span attributes (e.g., `llm.prompt_type=summarization`)

### Example End-to-End Trace

A complete user query generates this trace hierarchy:

```
orchestrator.query_pipeline (aurora-backend)
├── llm.request (query_parsing)
├── HTTP GET /api/v1/neo4j/query (aurora-backend → neo4j)
│   └── graph.query (neo4j-client)
└── llm.request (summarization)
```

## Metrics Summary

### LLM Metrics
- `llm.request.count` - Total LLM calls
- `llm.request.duration_ms` - LLM latency
- `llm.tokens.prompt` - Prompt tokens
- `llm.tokens.completion` - Completion tokens
- `llm.tokens.total` - Total tokens

**Attributes**: `llm.provider`, `llm.prompt_type`, `llm.model`

### Neo4j Metrics
- `graph.query.count` - Query count
- `graph.query.duration_ms` - Query duration
- `graph.query.rows_returned` - Result rows

**Attributes**: `db.system`, `graph.query_type`, `graph.cypher_hash`

### Orchestration Metrics
- `orchestrator.pipeline.count` - Pipeline executions
- `orchestrator.pipeline.duration_ms` - Pipeline latency

**Attributes**: `user.id`

### Agent Metrics
- `agent.execution.count` - Agent runs
- `agent.execution.duration_ms` - Agent execution time

**Attributes**: `agent.name`

### Feed Metrics
- `feed.generation.count` - Feed generations
- `feed.generation.duration_ms` - Feed rendering time

**Attributes**: `user.id`, `feed.sort`

## Performance Considerations

### Non-Blocking Export

All telemetry uses background threads for export:
- **Traces**: `BatchSpanProcessor` with 2048 queue, 512 batch size, 5s delay
- **Metrics**: `PeriodicExportingMetricReader` with 15s interval

Telemetry failures do not block application requests.

### Cardinality Control

High-cardinality attributes are avoided:
- ✅ Use `agent.name` (bounded by agent count)
- ❌ Don't use `agent.id` (unbounded UUID)
- ✅ Use `user.id` for user-scoped metrics only
- ❌ Don't use full prompt text in attributes

### Resource Usage

Typical overhead per service:
- CPU: < 2% additional load
- Memory: ~50MB for OTEL SDK
- Network: ~100KB/s to collector at 1.0 sampling

## Troubleshooting

### No traces appearing in Tempo

1. Check collector is running: `docker compose ps otel-collector`
2. Check collector logs: `docker compose logs otel-collector`
3. Verify `OTEL_ENDPOINT` is correct in service env vars
4. Check `OTEL_ENABLED=true` in service env vars

### High memory usage

1. Reduce `OTEL_SAMPLE_RATE` to 0.1 or lower
2. Check for attribute cardinality issues (user IDs, timestamps)
3. Increase collector batch size to reduce export frequency

### Missing LLM metrics

1. Verify LLM calls are wrapped with `create_llm_span_manually()`
2. Check that token usage is recorded in span attributes
3. Ensure `response.usage` is not None

### Broken trace context

1. Verify RabbitMQ clients are using inject/extract trace context functions
2. Check that spans are properly ended in finally blocks
3. Ensure context propagation headers are present in AMQP messages

## Future Enhancements

Potential additions:
- Custom Grafana dashboards for each service
- Alerting rules in Prometheus
- Log-to-trace correlation in Loki queries
- Exemplar support for metrics-to-traces navigation
- OpenTelemetry Collector scaling for high throughput

## References

- [OpenTelemetry Python Documentation](https://opentelemetry.io/docs/instrumentation/python/)
- [OpenTelemetry Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/)
- [Prometheus Query Language](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Grafana Tempo Documentation](https://grafana.com/docs/tempo/latest/)
