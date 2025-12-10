# Neo4j Init Container

One-time initialization container for the Neo4j knowledge graph.

## Purpose

This container runs once at startup to:

1. **Wait for Neo4j** - Ensures the database is accepting connections
2. **Create Schema** - Sets up constraints and indexes (idempotent)
3. **Load Base Data** - Initializes organizations and data sources

## Why a Separate Container?

Previously, the `digester` service was responsible for initializing Neo4j. This created issues:

- **Race conditions**: If multiple services started simultaneously, schema creation could conflict
- **Implicit dependencies**: Other services assumed `digester` ran first
- **Tight coupling**: A document processing service shouldn't own database initialization

The init container pattern solves these by:

- Running once before other services start
- Providing a clear dependency chain in docker-compose
- Separating concerns (initialization vs. runtime operations)

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `neo4j` | Neo4j password |
| `NEO4J_DATABASE` | `neo4j` | Database name |
| `LOG_LEVEL` | `INFO` | Logging level |

## Idempotency

The init container is idempotent:

- **Schema**: Uses `IF NOT EXISTS` clauses; checks for existing constraints before running
- **Base Data**: Checks for existing Organization nodes before loading

This means it's safe to run multiple times (e.g., on container restarts).

## Usage

The container is designed to run via docker-compose:

```yaml
neo4j-init:
  build:
    context: .
    dockerfile: neo4j-init/Dockerfile
  depends_on:
    neo4j:
      condition: service_healthy
  restart: "no"  # Run once only
```

Other services depend on it:

```yaml
digester:
  depends_on:
    neo4j-init:
      condition: service_completed_successfully
```

## Local Development

To run manually (requires neo4j-client installed):

```bash
cd neo4j-init
pip install ../neo4j-client
python init.py
```

## Architecture Decision: Why Not Put Neo4j Behind an API?

A common pattern in microservices is to hide databases behind a dedicated API gateway. We considered this for Neo4j but chose the current approach (shared client library + init container) for the following reasons.

### Option A: Graph API Gateway (Not Chosen)

Put Neo4j behind a REST/GraphQL service that all other services call.

**Pros:**
- Single point of access control and authentication
- Centralized caching layer
- Easier to swap graph databases in the future
- Clear API contracts between services
- Can enforce rate limiting and quotas
- Useful for external consumers of the graph

**Cons:**
- Adds network latency to every graph operation
- Another service to deploy, monitor, and maintain
- Single point of failure (unless replicated)
- HTTP overhead for high-frequency operations (embeddings, bulk writes)
- More complex debugging (distributed traces across services)
- Overkill when all consumers are internal services

### Option B: Shared Client Library + Init Container (Chosen)

Services use a shared `neo4j_client` library directly. Schema initialization is handled by a one-time init container.

**Pros:**
- Lower latency (direct Bolt protocol, no HTTP layer)
- Simpler architecture (fewer moving parts)
- Services can use native Neo4j features (transactions, streaming)
- Easier local development and testing
- No single point of failure for graph access
- The `neo4j_client` library already provides a clean abstraction

**Cons:**
- Credentials must be distributed to each service
- No centralized caching (each service manages its own)
- Harder to add external consumers later
- Schema changes require updating the client library

### When to Reconsider

Consider adding a Graph API Gateway if:

- **External consumers** need access to the knowledge graph
- **Multiple teams** are building services that access the graph
- **Fine-grained authorization** is needed beyond Neo4j's built-in RBAC
- **Query volume** becomes high enough to benefit from centralized caching
- **You need to support multiple graph backends** (e.g., Neo4j + Amazon Neptune)

For the current architecture—a small set of internal services with moderate query volume—the direct client approach is simpler and faster.
