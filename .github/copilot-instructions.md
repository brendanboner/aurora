# Aurora — AI Coding Agent Instructions

Aurora is a microservices-based knowledge management system that scrapes, processes, and enables LLM-powered Q&A over Wi-Fi Alliance documentation using a Neo4j knowledge graph.  
The system is designed so users can ask questions **as if they personally attended every Wi-Fi Alliance meeting and reviewed every published document**.  Answers must always be substantive — never expose internal retrieval limitations.

---

## Architecture Overview

```
Retriever → RabbitMQ → Digester → Neo4j ← Curator
Frontend → Auth Gateway → Backend → Oracle → Neo4j + Azure OpenAI
```

### Core Services (all FastAPI / Python)

| Service | Role |
|---------|------|
| `auth/` | OAuth 2.0/JWT gateway via AWS Cognito; proxies all authenticated requests |
| `backend/` | Main API (users, preferences, queries); coordinates query pipeline |
| `oracle/` | Two-pipeline Q&A: **fast** (graph-first, sub-3s) and **baseline** (full LLM) |
| `retriever/` | Web scraper; publishes to RabbitMQ `scraped_content` queue |
| `digester/` | Consumes RabbitMQ; LLM entity extraction; populates Neo4j |
| `curator/` | Post-processing: topic hierarchies, deduplication |
| `content_creator_service/` | AI agent personas — personalized social posts from KB |
| `teams-agent/` | Microsoft Teams bot (Node.js) |
| `frontend/` | React app (dark theme, markdown chat, `src/pages/Chatbot.jsx`) |

### Shared Libraries (editable installs)

| Package | Contents |
|---------|----------|
| `neo4j-client/` | Graph ops, models: Topic, Organization, Person, Resource |
| `rabbitmq-client/` | Async producer/consumer helpers |
| `common/` | `auth_middleware.py`, `service_client.py`, `telemetry.py` (OTel) |

### Infrastructure

- **PostgreSQL** — users, preferences, feedback, events
- **Neo4j** — knowledge graph with vector indexes (`text-embedding-3-large`)
- **RabbitMQ** — async queue between retriever → digester
- **Redis** — fast-engine result cache (1 hr TTL), answer cache, rate limiting
- **Nginx** — dev reverse proxy / prod SSL termination
- **Grafana Stack** — Tempo (traces), Loki (logs), Prometheus (metrics)

---

## Oracle Fast Pipeline (critical — read this)

The fast pipeline is the primary query path. It uses a **graph-first, template-driven** approach to return answers in <3s by hitting Neo4j directly before falling back to the full LLM baseline.

### Flow

```
LocalRouter (regex + entity extraction)
  → RoutePlan (RouteId + params + confidence)
  → Cypher template (QueryTemplateRegistry)
  → Neo4j results
  → LLM synthesis (answer_generator.py)
  → Response

If fast raises ANY exception → baseline_engine.query() runs automatically
```

### Key files

| File | Purpose |
|------|---------|
| `oracle/src/engines/fast_engine.py` | Core fast pipeline; routing, Cypher execution, LLM synthesis |
| `oracle/src/services/local_router.py` | Regex pattern matching → RouteId + confidence (0–1) |
| `oracle/src/models/route_plan.py` | `RouteId` enum (39 route types) |
| `oracle/src/services/query_template_registry.py` | All Cypher templates + `build_params()` |
| `oracle/src/prompts/answer_generator.py` | LLM system prompt — "meeting attendee" persona |
| `oracle/src/services/response_generator.py` | Baseline zero-doc fallback handler |
| `oracle/src/services/confidence_scorer.py` | Multi-factor answer confidence (baseline only) |
| `oracle/src/services/fast_cache.py` | Redis caches: `fast:plan:*`, `fast:result:*`, `fast:answer:*` |

### Important invariants (do not break)

1. **Never cache zero-node results.** `fast_engine.py` has a guard: `if len(processed_results) > 0: await self.fast_cache.set_result(...)`. Zero-node caches previously caused blank answers for up to 1 hour.
2. **Raise exception on zero docs**, don't return a static string. The `fast_fallback_to_baseline` in `query.py` only activates when `fast_engine.query()` raises — a silent return bypasses baseline.
3. **LLM client is synchronous.** `get_llm_client()` returns `AzureOpenAI` (sync). Use `call_llm(client, messages, ...)` — never `await client.chat.completions.create(...)` directly.
4. **Topic plural/singular variants.** When building Cypher params, always add both `term` and `term + "s"` / `term[:-1]` so "sticky clients" matches "sticky client" nodes.
5. **PERSON_PROFILE Cypher** — the `aff` variable from `OPTIONAL MATCH (p)-[aff:AFFILIATED_WITH]->(o)` must appear in every subsequent `WITH` clause or you get a `CypherSyntaxError`.

### Confidence scoring

- **Fast pipeline:** returns `metadata.intent_confidence` (routing confidence, 0–1). No full answer-level score.
- **Baseline pipeline:** runs `calculate_confidence()` from `confidence_scorer.py` — factors: document coverage (30%), source quality (25%), recency (20%), consensus (15%), query match (10%).
- CLI surfaces both: `🟢 High / 🟡 Medium / 🔴 Low` with percentage.

### Flushing Redis caches (when debugging stale answers)

```bash
# Flush all fast caches
redis-cli EVAL "local k=redis.call('keys',ARGV[1]) for i=1,#k,5000 do redis.call('del',unpack(k,i,math.min(i+4999,#k))) end return #k" 0 "fast:*"

# Flush only result cache (keep plan + answer caches)
redis-cli EVAL "..." 0 "fast:result:*"
```

---

## Frontend — Chatbot.jsx critical patterns

**File:** `frontend/src/pages/Chatbot.jsx`

### Known bugs fixed — do not reintroduce

| Bug | Root cause | Fix |
|-----|-----------|-----|
| Assistant message silently vanished | `AuthContext.checkAuthStatus` had `[user]` as `useCallback` dep → infinite re-auth loop → each new `user` object reference triggered the message **load** effect, resetting messages from localStorage before the save effect ran | `checkAuthStatus` now has `[]` deps; uses `setUser(prev => identical ? prev : newData)`; Chatbot load/save effects depend on `user?.id` (string) not `user` (object) |
| "No matching documents" generic response | `response_generator.py` was `await`-ing a sync `AzureOpenAI` client → silent `TypeError` → hardcoded fallback string returned | Use `call_llm()` wrapper, never `await client.chat.completions.create()` |
| Blank chat after second query | Zero-node results cached in Redis; next request hit cache → 0 docs → zero_docs_fallback every time | Never cache zero-node results |

### Message rendering

- Messages are saved to `localStorage` per-user via `compactMessageForStorage` (truncates docs/text for storage)
- On load, timestamps are restored with `new Date(msg.timestamp)` — always use `(ts instanceof Date ? ts : new Date(ts)).toLocaleTimeString()` for safe rendering
- `MAX_STORED_MESSAGES = 24` — only last 24 messages are persisted; full message array kept in React state

### Query flow in `executeQuery()`

```
sendOracleQuery() → Promise.race(query, 90s timeout)
  → hasUsableAnswer(response.answer) ?
      → use answer
      → buildDocumentFallbackAnswer(docs)  ← never shows blank
  → setMessages([...prev, assistantMessage])
  → if shouldAutoEnhance: void autoEnhanceMessage(...)
```

---

## Authentication & Authorization

**Security model:** Docker network isolation. Internal services only reachable through auth gateway.

```python
from common.auth_middleware import get_user_context, require_user_context, require_role
from common.service_client import call_internal_service

# Service-to-service (always use this, never direct HTTP to auth)
result = await call_internal_service(
    service_url="http://curator:8000",
    path="/trigger/topics",
    method="POST",
    user_context=user  # or None for system calls
)
```

Auth gateway adds headers: `X-User-Id`, `X-User-Email`, `X-User-Role`. Internal services trust these headers.

---

## Development Workflows

### Start / stop

```bash
docker compose up -d               # Start all (hot reload on)
docker compose logs -f oracle      # Tail a service
docker compose restart oracle      # Restart one service
```

### End-to-end CLI testing

```bash
# Standard battery (21 questions, all pipelines)
./test_cli.sh

# Fast-pipeline battery (68 questions, forced fast mode)
./test_cli_fast.sh --random --questions=5     # 5 random
./test_cli_fast.sh --random                   # 5 random (default)
./test_cli_fast.sh                            # all 68 in order
./test_cli_fast.sh --verbose --questions=3    # + route/graph metadata

# Single query with explicit pipeline
./cli/aurora --pipeline fast  "What are sticky clients?"
./cli/aurora --pipeline baseline "Compare Wi-Fi 7 and Wi-Fi 8"
./cli/aurora -v "What happened in the Wi-Fi 8 meeting last week?"   # verbose
```

`cli/fast_questions.txt` — 68 questions covering all 10 route-type categories.

### Build & ship

```bash
make aws-login                                          # Authenticate ECR (opens browser)
make build-push-oracle build-push-frontend             # Rebuild changed services
make build-push-all                                    # Rebuild everything
# VERSION is auto-set to the current git SHA
```

### Deploy to production EC2

```bash
# Option 1 — interactive SSM session
make connect_aurora_ec2
# then: sudo -i -u ec2-user
# then: cd ~/octo-rapid-aurora/prod-deployment && make update

# Option 2 — non-interactive SSM (scriptable)
aws ssm send-command \
  --instance-ids "i-083e73fca8dbe3191" \
  --profile "PowerUserAccess-716121312929" \
  --region us-east-1 \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["sudo -u ec2-user bash -c \"cd /home/ec2-user/octo-rapid-aurora && git pull origin main && cd prod-deployment && make update\""]'
```

`make update` = ECR login → backup → `docker compose pull` → `docker compose up -d`

### Database migrations

```bash
make migrate          # Apply pending PostgreSQL migrations
make migrate-status   # Check history
# Migration SQL files: prod-deployment/migrations/*.sql
```

---

## Neo4j Knowledge Graph

**Node types:** Topic, Organization, Person, Resource, Event, DataSource  
**Key relationships:** `DISCUSSES` (Resource→Topic), `PUBLISHED_BY` (Resource→Organization), `ENCOMPASSES` (Topic→Topic), `AFFILIATED_WITH` (Person→Organization)

```python
from neo4j_client import Neo4jClient, GraphRepository
from neo4j_client.deduplicator import NodeDeduplicator

client = Neo4jClient(uri, user, password, database)
dedup  = NodeDeduplicator(client)
topic  = await dedup.find_or_create_topic(name="Wi-Fi 7", aliases=["802.11be"])
```

**Vector search:** `text-embedding-3-large`, cosine similarity  
**Recreate vector indexes:** `python neo4j-client/recreate_vector_indexes.py`

---

## Observability

```python
from common.telemetry import init_telemetry, instrument_fastapi

tracer, meter = init_telemetry(service_name="aurora-oracle", service_version="1.0.0")
instrument_fastapi(app)   # auto-instruments all routes
```

Grafana at `http://localhost:3001` (dev) — Tempo traces, Loki logs, Prometheus metrics.

---

## RabbitMQ Message Flow

**Queue:** `scraped_content`  
**Message types:** `"resource"` (documents), `"event"` (conferences/webinars)

```python
# Retriever publishes
from rabbitmq_client.producer import RabbitMQProducer
producer = RabbitMQProducer(host, port, user, password, queue)
producer.publish(message_dict, message_type="resource")

# Digester consumes
from rabbitmq_client import AsyncRabbitMQConsumer
consumer = AsyncRabbitMQConsumer(host, port, user, password, queue)
await consumer.start(callback=process_message)
```

---

## Common Pitfalls

1. **Shared library changes** — after editing `neo4j-client/` or `rabbitmq-client/`, rebuild all dependent service images.
2. **Auth headers** — internal services must use `call_internal_service()`, never raw HTTP to the auth service.
3. **Async LLM client** — `get_llm_client()` is sync `AzureOpenAI`. Always use `call_llm()` wrapper.
4. **Zero-doc caching** — never call `fast_cache.set_result()` when `processed_results` is empty.
5. **CORS** — dev has CORS on for `localhost:3000`; prod relies on nginx proxy (no CORS headers needed).
6. **`user` object identity in React** — `AuthContext.checkAuthStatus` previously recreated `user` on every call (infinite loop). It now uses a JSON identity check — do not add `user` back to its `useCallback` deps.
7. **Pipeline override in oracle** — pass `options.pipeline_override = "fast" | "baseline"` in the request body to force a pipeline; do not rely on AB-test flag alone when testing.

---

## Environment Variables

| Context | File |
|---------|------|
| Development | `.env.dev` → `.env` |
| Production | `.env.prod` → `.env` |
| CLI testing | `TEST_USER_ID`, `TEST_USER_EMAIL`, `AURORA_ROLE`, `AURORA_ORACLE_URL` |

All services read from the centralized `.env` via docker-compose.

---

## Key Files Quick Reference

| File | What it does |
|------|-------------|
| `docker-compose.yml` | Dev service orchestration |
| `prod-deployment/docker-compose.prod.yml` | Production config |
| `oracle/src/engines/fast_engine.py` | Fast pipeline (primary query path) |
| `oracle/src/services/query_template_registry.py` | All 39 Cypher templates |
| `oracle/src/prompts/answer_generator.py` | LLM persona ("meeting attendee") |
| `frontend/src/pages/Chatbot.jsx` | Main chat UI |
| `frontend/src/contexts/AuthContext.js` | Auth state (stable user ref) |
| `cli/aurora_query.py` | CLI query client with `--pipeline` and confidence badges |
| `cli/fast_questions.txt` | 68-question fast-mode test bank |
| `test_cli_fast.sh` | Fast-pipeline test harness (`--random --questions=N`) |
| `test_cli.sh` | Full 21-question integration test battery |
| `doc/PIPELINE_FLOW.md` | Query processing flow diagram |
| `doc/DEPLOYMENT.md` | AWS EC2 deployment guide |

---

## Quick Command Reference

| Task | Command |
|------|---------|
| Start dev | `docker compose up -d` |
| Tail logs | `docker compose logs -f [service]` |
| Run all service tests | `make test-all` |
| Run fast-mode CLI tests | `./test_cli_fast.sh --random --questions=5` |
| Run full CLI battery | `./test_cli.sh` |
| Rebuild changed services | `make build-push-oracle build-push-frontend` |
| Rebuild everything | `make build-push-all` |
| AWS ECR login | `make aws-login` |
| Deploy to prod | `cd prod-deployment && make update` |
| Connect to EC2 | `make connect_aurora_ec2` |
| Flush Redis fast cache | `redis-cli EVAL "..." 0 "fast:*"` |
| Apply DB migrations | `make migrate` |
