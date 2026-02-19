# Aurora - AI Coding Agent Instructions

Aurora is a microservices-based knowledge management system that scrapes, processes, and enables LLM-powered Q&A over Wi-Fi Alliance documentation using a Neo4j knowledge graph.

## Architecture Overview

**Service Pipeline:** `Retriever → RabbitMQ → Digester → Neo4j ← Curator`
**Query Flow:** `Frontend → Auth Gateway → Backend → Oracle → Neo4j + Azure OpenAI`

### Core Services (all FastAPI)

- **auth/** - OAuth 2.0/JWT gateway using AWS Cognito, proxies all authenticated requests
- **backend/** - Main API (users, preferences, queries), coordinates query pipeline
- **oracle/** - Advanced Q&A with multi-strategy retrieval and graph-aware context
- **retriever/** - Web scraper publishing to RabbitMQ (`scraped_content` queue)
- **digester/** - Consumes RabbitMQ, extracts entities via LLM, populates Neo4j
- **curator/** - Post-processing: organizes topics into hierarchies, deduplicates
- **content_creator_service/** - AI agent personas that generate personalized social posts
- **teams-agent/** - Microsoft Teams bot integration (Node.js)
- **frontend/** - React app (dark theme UI with markdown chat)

### Shared Libraries (installed as editable packages)

- **neo4j-client/** - Graph operations, models (Topic, Organization, Person, Resource)
- **rabbitmq-client/** - Producer/consumer utilities
- **common/** - `auth_middleware.py`, `service_client.py`, `telemetry.py` (OpenTelemetry)

### Infrastructure

- **PostgreSQL** - Users, preferences, feedback, events
- **Neo4j** - Knowledge graph with vector indexes
- **RabbitMQ** - Async message queue between services
- **Redis** - Monitoring, caching, rate limiting
- **Nginx** - Reverse proxy (dev) / SSL termination (prod)
- **Grafana Stack** - Tempo (traces), Loki (logs), Prometheus (metrics)

## Development Workflows

### Starting the System

```bash
# Development (hot reload enabled)
docker compose up -d               # Start all services
docker compose logs -f [service]   # View logs

# Access points
http://localhost:3000              # React dev server (HMR)
http://localhost                   # Via nginx proxy
http://localhost/api/docs          # Swagger docs
```

### Running Tests

```bash
# Root orchestrates all services
make test-all                      # Run tests for all services
make test-<service>                # Test specific service

# Per-service (from service directory)
cd backend && make test            # Uses pytest
cd frontend && npm test            # Uses Jest/React Testing Library
```

### Building & Shipping to ECR

```bash
make aws-login                     # Authenticate to AWS ECR
make ship-all                      # Test + build + push all images
make ship-backend                  # Single service

# Each service Makefile includes ../Makefile.common
# VERSION = git SHA (auto-generated)
```

### Database Migrations

```bash
make migrate                       # Apply PostgreSQL migrations
make migrate-status                # Check migration history

# Migrations in prod-deployment/migrations/*.sql
# Auto-applied via docker-entrypoint-initdb.d in postgres service
```

## Authentication & Authorization

**Security Model:** Docker network isolation. Internal services only reachable via auth gateway.

**Auth Gateway Pattern:**
1. User authenticates via AWS Cognito OAuth 2.0
2. Auth service validates JWT and adds headers: `X-User-Id`, `X-User-Email`, `X-User-Role`
3. Auth service proxies request to internal service
4. Internal services trust headers (shared network boundary)

**Usage in Services:**

```python
from common.auth_middleware import get_user_context, require_user_context, require_role

# Optional auth (works with/without user)
@app.get("/status")
async def status(user: Optional[dict] = Depends(get_user_context)):
    if user:
        return {"user": user["email"]}
    return {"system": "ok"}  # Service-to-service call

# Required auth
@app.post("/query")
@require_user_context
async def query(user: dict = Depends(get_user_context)):
    # user guaranteed not None
    pass

# Role-based
@app.post("/admin/scrape")
@require_role(["admin", "superadmin"])
async def scrape(user: dict = Depends(get_user_context)):
    pass
```

**Service-to-Service Calls:**

```python
from common.service_client import call_internal_service

# User-initiated (propagate context)
result = await call_internal_service(
    service_url="http://curator:8000",
    path="/trigger/topics",
    method="POST",
    user_context=user  # Pass through
)

# System/scheduled (no user context)
result = await call_internal_service(
    service_url="http://curator:8000",
    path="/status",
    method="GET"
)
```

## Query Pipeline Architecture

**File:** `backend/src/services/query_engine.py`

1. Load user preferences from PostgreSQL (topics/orgs/people)
2. Extract filters from question via LLM (`llm_service.parse_query_to_filters`)
3. Merge LLM filters with user preferences (both treated as relevance signals)
4. Query Neo4j with multi-factor scoring (40% topic, 30% org, 20% people, 10% relationships)
5. Combine relevance (70%) + recency (30%) for final ranking
6. Summarize via LLM with anti-hallucination instructions
7. Return answer + citations + full document metadata

**Key Pattern:** Query filters take precedence over user preferences for precision.

**See:** `doc/PIPELINE_FLOW.md` for detailed flow diagram

## RabbitMQ Message Flow

**Queue:** `scraped_content`

**Retriever publishes:**
```python
from rabbitmq_client.producer import RabbitMQProducer

producer = RabbitMQProducer(host, port, user, password, queue)
producer.publish(message_dict, message_type="resource")
```

**Digester consumes:**
```python
from rabbitmq_client import AsyncRabbitMQConsumer

consumer = AsyncRabbitMQConsumer(host, port, user, password, queue)
await consumer.start(callback=process_message)
```

**Message Types:** `"resource"` (documents), `"event"` (conferences/webinars)

## Neo4j Knowledge Graph

**Node Types:** Topic, Organization, Person, Resource, Event, DataSource
**Key Relationships:** DISCUSSES (Resource→Topic), PUBLISHED_BY (Resource→Organization), ENCOMPASSES (Topic→Topic)

**Shared Client Usage:**
```python
from neo4j_client import Neo4jClient, GraphRepository
from neo4j_client.models import Topic, Resource, Organization

client = Neo4jClient(uri, user, password, database)
repo = GraphRepository(client)

# Create/update with deduplication
from neo4j_client.deduplicator import NodeDeduplicator
dedup = NodeDeduplicator(client)
topic = await dedup.find_or_create_topic(name="Wi-Fi 7", aliases=["802.11be"])
```

**Vector Search:** Uses `text-embedding-3-large` embeddings with cosine similarity

## Observability (OpenTelemetry)

**Pattern:** Each service calls `init_telemetry()` at startup

```python
from common.telemetry import init_telemetry, instrument_fastapi

tracer, meter = init_telemetry(
    service_name="aurora-backend",
    service_version="1.0.0"
)
instrument_fastapi(app)  # Auto-instruments routes
```

**Instrumentation:** FastAPI, HTTPX, Psycopg2, Redis automatically traced when available.

**Backends:** Tempo (traces), Loki (logs), Prometheus (metrics) → Grafana dashboards

## Testing Conventions

**Backend/Services (pytest):**
- Use `pytest-asyncio` for async tests
- Mock external dependencies (Neo4j, RabbitMQ, Azure OpenAI)
- See `retriever/tests/test_base_scraper.py` for comprehensive fixture patterns

**Frontend (Jest):**
- React Testing Library for component tests
- Mock API calls via `src/api/client.js`

**Integration Tests:**
- Some services have `/testing` endpoints (curator, retriever)
- Use `test_*.sh` scripts in root for end-to-end scenarios

## Production Deployment

**Target:** AWS EC2 with Docker Compose

```bash
cd prod-deployment
cp .env.prod .env           # Configure DOMAIN, SSL_EMAIL, passwords
make deploy                  # Uses docker-compose.prod.yml

# SSL via Let's Encrypt (automatic renewal)
# nginx/init-ssl.sh runs on first start
# nginx/renew-certs.sh cron job for renewal
```

**Key Config:**
- All infrastructure ports closed (only 80/443 exposed)
- nginx handles SSL termination, proxies to auth service
- Auth service proxies to internal services
- Automated backups via `scripts/backup.sh` (cron)

**See:** `doc/DEPLOYMENT.md` for full EC2 setup guide

## Project-Specific Patterns

### Makefile Hierarchy
- Root `Makefile` orchestrates all services
- Each service has `Makefile` that `include ../Makefile.common`
- Common targets: `test`, `build-push`, `ship` (test + build + push)
- Uses git SHA for automatic image versioning

### Error Handling
- Services use structured logging with context (user_id, request_id)
- LLM calls have fallback heuristics (see `llm_service.py`)
- Neo4j queries use `OPTIONAL MATCH` for flexible retrieval

### Environment Variables
- Development: `.env.dev` → `.env`
- Production: `.env.prod` → `.env`
- All services read from centralized `.env` via docker-compose

### Content Creator Agents
- Each agent has persona, cadence, topics, and style preferences
- Knowledge monitoring triggers post generation when new relevant docs appear
- Posts include source citations and relevance scoring
- Quality controls: diversity filtering, domain limits, temporal windows

## Common Pitfalls

1. **Shared library changes:** After modifying `neo4j-client/` or `rabbitmq-client/`, rebuild dependent service images
2. **Auth headers:** Internal services MUST NOT call auth endpoints directly; use `call_internal_service()` from `common/service_client.py`
3. **Neo4j migrations:** Vector indexes must be manually recreated via `neo4j-client/recreate_vector_indexes.py`
4. **RabbitMQ queues:** If changing queue names, update both producer and consumer configs
5. **CORS:** Development has CORS enabled for `localhost:3000`; production relies on nginx proxy (no CORS needed)

## Key Files for Context

- `docker-compose.yml` - Service orchestration (dev)
- `prod-deployment/docker-compose.prod.yml` - Production config
- `doc/PIPELINE_FLOW.md` - Query processing flow
- `doc/DEPLOYMENT.md` - AWS deployment guide
- `auth/INTEGRATION_GUIDE.md` - Auth gateway deep dive
- `content_creator_service/README.md` - AI agent configuration
- `oracle/README.md` - Advanced Q&A features

## Quick Reference

| Task | Command |
|------|---------|
| Start dev environment | `docker compose up -d` |
| View service logs | `docker compose logs -f [service]` |
| Run all tests | `make test-all` |
| Test one service | `cd [service] && make test` |
| Apply DB migrations | `make migrate` |
| Build for ECR | `make ship-all` |
| Deploy to prod | `cd prod-deployment && make deploy` |
| Connect to EC2 | `make connect_aurora_ec2` |
