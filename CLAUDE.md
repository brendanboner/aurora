# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Primary reference

`.github/copilot-instructions.md` is the authoritative architecture and conventions doc. Read it before non-trivial changes — it covers the Oracle fast/baseline pipeline, Chatbot.jsx history, auth model, RabbitMQ flow, Neo4j schema, and known bug regressions in detail. This file is the short version.

## What Aurora is

A microservices RAG system that scrapes Wi-Fi Alliance docs, builds a Neo4j knowledge graph, and serves LLM-powered Q&A. The product persona is "user attended every Wi-Fi Alliance meeting" — answers must be substantive and never reveal internal retrieval limits.

```
Retriever → RabbitMQ → Digester → Neo4j ← Curator
Frontend → Auth gateway → Backend → Oracle → Neo4j + Azure OpenAI
```

Services (all Python/FastAPI unless noted): `auth/`, `backend/`, `oracle/`, `retriever/`, `digester/`, `curator/`, `content_creator_service/`, `kg_view/`, `frontend/` (React), `teams-agent/` (Node/TS), `nginx/`.

Shared libraries (editable installs): `neo4j-client/`, `rabbitmq-client/`, `common/` (auth_middleware, service_client, telemetry).

Infrastructure: PostgreSQL (users/prefs/feedback), Neo4j (KG + `text-embedding-3-large` vector indexes), RabbitMQ (`scraped_content` queue), Redis (fast-engine cache, 1h TTL), Grafana/Tempo/Loki/Prometheus.

## Common commands

```bash
# Dev environment (hot reload)
docker compose up -d
docker compose logs -f <service>
docker compose restart <service>

# Tests — per-service from repo root
make test-oracle              # one service
make test-all                 # all Python services
cd <service> && make test     # alternate form (creates a venv, runs pytest, tears down)

# Single Python test (after `cd <service> && make install` to seed .venv)
cd oracle && PYTHONPATH=..:$PYTHONPATH .venv/bin/pytest tests/path/to/test_file.py::test_name -v

# Frontend
cd frontend && npm test -- --watchAll=false
cd frontend && npm start          # local dev server (or use docker compose)

# CLI / end-to-end testing of the query pipelines
./test_cli.sh                                              # 21-question full battery
./test_cli_fast.sh --random --questions=5                  # fast-pipeline battery
./cli/aurora --pipeline fast "What are sticky clients?"    # single query, forced pipeline
./cli/aurora --pipeline baseline -v "Compare Wi-Fi 7 and 8"

# Build & ship to ECR (VERSION auto-set to git SHA)
make aws-login
make build-push-oracle build-push-frontend       # selected services
make build-push-all                              # everything
make ship-oracle                                 # test + build + push for one service

# DB migrations (PostgreSQL)
make migrate
make migrate-status

# Deploy to production EC2
make connect_aurora_ec2          # SSM session, then: sudo -i -u ec2-user; cd ~/octo-rapid-aurora/prod-deployment && make update
```

Each service Makefile follows the same pattern via `Makefile.common`: `test` (creates a fresh `.venv`, runs pytest with coverage, tears the venv down), `build-push`, `ship`. `oracle/Makefile` also `pip install -e ../neo4j-client` — most other Python services do the same for the shared libraries they import.

## Architecture invariants — do not break

These are real footguns that have caused regressions. The full list is in copilot-instructions.md; the most load-bearing:

1. **Oracle LLM client is synchronous.** `get_llm_client()` returns `AzureOpenAI` (sync). Always call via the `call_llm(client, messages, ...)` wrapper — never `await client.chat.completions.create(...)`. An `await` on the sync client silently raises `TypeError` and was the root cause of generic "no matching documents" answers.

2. **Never cache zero-node fast-engine results.** `fast_engine.py` guards with `if len(processed_results) > 0:` before `fast_cache.set_result(...)`. A zero-node cache returns blank answers for up to 1 hour.

3. **Fast pipeline must raise on zero docs, not return a static string.** `fast_fallback_to_baseline` in `oracle/src/routes/query.py` only fires when `fast_engine.query()` raises; a silent string return bypasses the baseline pipeline.

4. **Service-to-service calls go through `common.service_client.call_internal_service`** — never raw HTTP to the auth gateway. Internal services trust the `X-User-Id` / `X-User-Email` / `X-User-Role` headers the gateway injects.

5. **`AuthContext.checkAuthStatus` in the frontend has `[]` deps and uses a JSON identity check on `setUser`.** Adding `user` back to its `useCallback` deps recreates the user object on every render → infinite re-auth → message load effect resets `localStorage` messages.

6. **Topic params in Cypher templates need plural+singular variants.** When `local_router` extracts a term, add both `term` and `term + "s"` / `term[:-1]` so "sticky clients" matches "sticky client" nodes.

7. **`PERSON_PROFILE` Cypher:** the `aff` from `OPTIONAL MATCH (p)-[aff:AFFILIATED_WITH]->(o)` must appear in every subsequent `WITH` clause or Neo4j raises `CypherSyntaxError`.

## Where to look first

| Area | Files |
|------|-------|
| Fast pipeline core | `oracle/src/engines/fast_engine.py`, `oracle/src/services/local_router.py`, `oracle/src/services/query_template_registry.py`, `oracle/src/models/route_plan.py` |
| Answer synthesis prompt | `oracle/src/prompts/answer_generator.py` |
| Baseline fallback / zero-doc handler | `oracle/src/services/response_generator.py`, `oracle/src/routes/query.py` |
| Confidence scoring (baseline only) | `oracle/src/services/confidence_scorer.py` |
| Redis caches | `oracle/src/services/fast_cache.py` (keys: `fast:plan:*`, `fast:result:*`, `fast:answer:*`) |
| Chat UI | `frontend/src/pages/Chatbot.jsx`, `frontend/src/contexts/AuthContext.js` |
| Auth/proxy | `auth/auth.py`, `auth/services/proxy.py`, `common/auth_middleware.py`, `common/service_client.py` |
| Graph models / dedup | `neo4j-client/` (Topic, Organization, Person, Resource, Event, DataSource) |
| CLI | `cli/aurora_query.py`, `cli/fast_questions.txt` (68-question test bank) |
| Pipeline docs | `doc/PIPELINE_FLOW.md`, `doc/FAST_PIPELINE.md`, `doc/CURATOR_OPTIMIZATION.md`, `doc/CREATOR_AGENT_ORACLE_INTEGRATION.md` |

## Debugging stale answers (fast pipeline)

```bash
# Flush all fast caches
redis-cli EVAL "local k=redis.call('keys',ARGV[1]) for i=1,#k,5000 do redis.call('del',unpack(k,i,math.min(i+4999,#k))) end return #k" 0 "fast:*"

# Or just result cache, keep plan/answer caches
redis-cli EVAL "..." 0 "fast:result:*"
```

To force a pipeline for a single request, set `options.pipeline_override = "fast" | "baseline"` in the query body — don't rely on AB-test flags when reproducing behavior.

## Environment files

`.env.dev` → `.env` for local; `.env.prod` → `.env` for production. All services read the centralized `.env` via docker-compose. CLI tests honor `TEST_USER_ID`, `TEST_USER_EMAIL`, `AURORA_ROLE`, `AURORA_ORACLE_URL`.
