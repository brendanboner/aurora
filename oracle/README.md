# Oracle Service

The Oracle Service provides enhanced question-answering capabilities over Aurora's knowledge graph. It introduces multi-strategy retrieval, graph-aware context assembly, and dual-mode responses (document retrieval vs. LLM-generated answers).

## Features

- **Multi-Strategy Retrieval**: Combines keyword search, vector similarity, and graph traversal
- **Query Intent Classification**: Automatically classifies queries to select optimal retrieval strategies
- **Dual Response Modes**: 
  - `retrieval`: Returns ranked document list for self-directed research
  - `answer`: Generates LLM answer with citations grounded in retrieved documents
- **Graph-Aware Context**: Assembles rich context including entity relationships

## API Endpoints

### POST /oracle/query

Main query endpoint for question-answering.

**Request:**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "question": "What are the latest updates on Wi-Fi 7?",
  "mode": "answer",
  "options": {
    "max_documents": 10,
    "include_graph_context": true
  }
}
```

**Response (Answer Mode):**
```json
{
  "mode": "answer",
  "answer": "Based on recent documents...",
  "citations": [...],
  "documents": [...],
  "graph_context": {...},
  "metadata": {...}
}
```

### GET /oracle/health

Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "checks": {
    "neo4j": "ok",
    "llm": "ok"
  }
}
```

## Query Intent Types

| Intent | Description | Example |
|--------|-------------|---------|
| `entity_focused` | Asking about specific organization, person, or resource | "What did Wi-Fi Alliance announce?" |
| `topic_discovery` | Exploring what's new in a topic area | "What's the latest in Wi-Fi 7?" |
| `relationship_query` | Asking about connections between entities | "Who is working on 802.11be?" |
| `trend_analysis` | Looking for patterns over time | "What topics are trending this month?" |
| `comparative` | Comparing multiple entities or topics | "Compare Wi-Fi 6E and Wi-Fi 7" |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEO4J_URI` | Yes | - | Neo4j connection URI |
| `NEO4J_USER` | Yes | - | Neo4j username |
| `NEO4J_PASSWORD` | Yes | - | Neo4j password |
| `NEO4J_DATABASE` | No | neo4j | Neo4j database name |
| `AZURE_OPENAI_API_KEY` | Yes | - | Azure OpenAI API key |
| `AZURE_OPENAI_ENDPOINT` | Yes | - | Azure OpenAI endpoint |
| `AZURE_OPENAI_DEPLOYMENT` | Yes | - | GPT deployment name |
| `LOG_LEVEL` | No | INFO | Logging level |

## Development

### Running locally

```bash
# Install dependencies
pip install -e .

# Run the service
uvicorn oracle.src.api:app --reload --port 8003
```

### Running tests

```bash
make test
```

### Building Docker image

```bash
make build
```

## Architecture

```
oracle/
├── src/
│   ├── api.py                      # FastAPI app entry point
│   ├── settings.py                 # Environment configuration
│   ├── routes/
│   │   ├── query.py                # /oracle/query endpoint
│   │   └── health.py               # /oracle/health endpoint
│   ├── services/
│   │   ├── query_router.py         # Intent classification & routing
│   │   ├── query_parser.py         # Entity/filter extraction
│   │   ├── keyword_retriever.py    # Neo4j keyword search
│   │   ├── vector_retriever.py     # Neo4j vector similarity search (Phase 2)
│   │   ├── hybrid_search.py        # Combined retrieval with RRF (Phase 2)
│   │   ├── context_builder.py      # Graph context assembly
│   │   └── response_generator.py   # Mode-based response formatting
│   ├── prompts/
│   │   ├── intent_classifier.py    # Intent classification prompts
│   │   ├── entity_extractor.py     # Entity extraction prompts
│   │   └── answer_generator.py     # Answer synthesis prompts
│   └── models/
│       ├── request.py              # Pydantic request models
│       └── response.py             # Pydantic response models
├── scripts/
│   └── backfill_embeddings.py      # Backfill script for vector indexes (Phase 2)
└── tests/
    ├── test_query_router.py
    ├── test_query_parser.py
    ├── test_vector_search.py       # Phase 2 tests
    └── test_api.py
```

## Phase 2: Vector Search Integration

Phase 2 adds semantic search capabilities to handle conceptual queries, typos, and synonym matching.

### Features

- **Vector Retriever**: Semantic similarity search using Neo4j vector indexes
- **Hybrid Search**: Combines keyword and vector retrieval using Reciprocal Rank Fusion (RRF)
- **Recency Boost**: Recent documents receive a relevance score boost
- **Typo Tolerance**: Find "Wi-Fi HaLow" even when user types "wifi hallow"

### Configuration

Additional environment variables for Phase 2:

| Variable | Default | Description |
|----------|---------|-------------|
| `VECTOR_SEARCH_ENABLED` | true | Enable vector similarity search |
| `VECTOR_MIN_SCORE` | 0.7 | Minimum cosine similarity score |
| `VECTOR_TOP_K` | 50 | Candidates to retrieve from vector search |
| `HYBRID_SEARCH_ENABLED` | true | Enable hybrid keyword+vector search |
| `RRF_K` | 60 | RRF constant (higher = more equal weighting) |
| `KEYWORD_WEIGHT` | 1.0 | Weight for keyword results in fusion |
| `VECTOR_WEIGHT` | 1.0 | Weight for vector results in fusion |
| `RECENCY_BOOST_ENABLED` | true | Enable recency boost |
| `RECENCY_BOOST_DAYS` | 30 | Boost documents from last N days |
| `RECENCY_BOOST_FACTOR` | 1.2 | Multiplier for recent documents |

### Backfilling Embeddings

Before using vector search, you need to generate embeddings for existing documents:

```bash
# Backfill Resource embeddings (run from oracle directory)
python -m scripts.backfill_embeddings --node-type resource

# Backfill Topic embeddings
python -m scripts.backfill_embeddings --node-type topic

# Backfill Organization embeddings
python -m scripts.backfill_embeddings --node-type organization

# Dry run to preview
python -m scripts.backfill_embeddings --node-type resource --dry-run

# Process limited number of nodes
python -m scripts.backfill_embeddings --node-type resource --max-nodes 1000
```

### Vector Index Setup

Vector indexes should be created automatically by the neo4j-client library. If needed, you can manually create them:

```cypher
CREATE VECTOR INDEX resource_embedding_index IF NOT EXISTS
FOR (r:Resource) ON r.embedding
OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}};

CREATE VECTOR INDEX topic_embedding_index IF NOT EXISTS
FOR (t:Topic) ON t.embedding
OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}};

CREATE VECTOR INDEX organization_embedding_index IF NOT EXISTS
FOR (o:Organization) ON o.embedding
OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}};
```

### Reciprocal Rank Fusion (RRF)

RRF combines ranked lists from keyword and vector search without requiring score normalization:

```
RRF(d) = Σ (weight_i / (k + rank_i(d)))
```

Where:
- `weight_i` is the weight for retriever i (keyword_weight, vector_weight)
- `k` is the RRF constant (default: 60)
- `rank_i(d)` is the rank of document d in retriever i's results

Documents appearing in both keyword and vector results get boosted scores.
