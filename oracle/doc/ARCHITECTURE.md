# Oracle Service Architecture

The Oracle Service is the query and retrieval engine for the Aurora knowledge graph. It processes natural language questions and returns relevant documents with optional AI-generated answers.

## Overview

Oracle provides two main modes:
- **Retrieval Mode**: Returns ranked documents matching the query
- **Answer Mode**: Returns documents plus an LLM-generated answer with citations

## Core Components

### 1. API Layer (`src/api.py`, `src/routes/`)

The FastAPI application exposes two main endpoints:

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Health check with dependency status |
| `POST /query` | Main query endpoint |

### 2. Query Router (`src/services/query_router.py`)

Classifies the user's intent to optimize retrieval strategy.

**Intent Types:**
- `factual_lookup` - Looking for specific facts
- `topic_discovery` - Exploring a topic broadly  
- `comparison` - Comparing technologies/standards
- `timeline` - Historical/chronological queries
- `entity_search` - Looking for specific people/orgs
- `procedural` - How-to questions

### 3. Query Parser (`src/services/query_parser.py`)

Extracts structured filters from natural language using LLM + heuristics.

**Extracts:**
- Topics (e.g., "Wi-Fi 7", "802.11be")
- Organizations (e.g., "Wi-Fi Alliance", "Broadcom")
- People (e.g., "Dorothy Stanley")
- Date ranges (e.g., "last 2 weeks", "in 2025")
- Document categories
- Keywords

**Temporal Interpretation:**
| Phrase | Interpreted As |
|--------|----------------|
| "last week" | Past 7 days |
| "last month" | Past 30 days |
| "last quarter" | Past 90 days |
| "last year" | Past 365 days |
| "latest" / "recent" | Past 30 days |
| "this week" | Current week (Mon-today) |
| "this month" | Current month |
| "this year" | Current year |

### 4. Entity Resolver (`src/services/entity_resolver.py`)

Resolves extracted entity names against actual graph nodes using a three-tier matching strategy:

1. **Exact Match** - Direct name lookup (case-insensitive)
2. **Alias Match** - Check topic/org aliases
3. **Vector Similarity** - Semantic matching for typos/variations

This ensures "wifi 7" matches the graph node "wi-fi 7".

### 5. Keyword Retriever (`src/services/keyword_retriever.py`)

Retrieves documents from Neo4j using structured filters:
- Topic relationships (`RELATES_TO`)
- Organization mentions (`MENTIONS`)
- People mentions (`MENTIONS`)
- Date filtering on `publish_date`
- Text search in title/summary

**Relevance Scoring:**
- 30% text match score
- 25% topic match score (graph relationships)
- 20% organization match score
- 15% people match score
- 10% relationship confidence

### 6. Vector Retriever (`src/services/vector_retriever.py`) [Phase 2]

Semantic search using Neo4j vector indexes:
- Generates query embedding via Azure OpenAI
- Searches document embeddings using cosine similarity
- Returns documents above minimum similarity threshold

**Configuration:**
- `VECTOR_SEARCH_ENABLED` - Enable/disable
- `VECTOR_MIN_SCORE` - Minimum similarity (default: 0.7)
- `VECTOR_TOP_K` - Max results (default: 50)

### 7. Hybrid Search (`src/services/hybrid_search.py`) [Phase 2]

Combines keyword and vector retrieval using Reciprocal Rank Fusion (RRF):

```
RRF_score = Σ (1 / (k + rank_i))
```

Where `k=60` (configurable) and `rank_i` is the document's rank in each result list.

**Configuration:**
- `HYBRID_SEARCH_ENABLED` - Enable/disable
- `RRF_K` - Fusion constant (default: 60)
- `KEYWORD_WEIGHT` - Weight for keyword results (default: 0.5)
- `VECTOR_WEIGHT` - Weight for vector results (default: 0.5)

### 8. Context Builder (`src/services/context_builder.py`)

Builds rich context from the knowledge graph:
- Central topics mentioned across documents
- Key organizations involved
- Key people mentioned
- Related entities (via graph traversal)
- Temporal patterns in the documents

### 9. Response Generator (`src/services/response_generator.py`)

In **Answer Mode**, generates natural language responses:
- Synthesizes information from retrieved documents
- Includes inline citations `[1]`, `[2]`
- Produces confidence scores
- Suggests follow-up queries

## Data Models

### Request (`src/models/request.py`)

```python
class QueryRequest:
    user_id: str           # Cognito UUID
    question: str          # User's question (1-2000 chars)
    mode: QueryMode        # "retrieval", "answer", or "auto"
    options: QueryOptions  # Optional filters
```

### Response (`src/models/response.py`)

```python
class QueryResponse:
    mode: str                    # "retrieval" or "answer"
    answer: Optional[str]        # Generated answer (answer mode)
    citations: List[Citation]    # Source citations
    documents: List[Document]    # Retrieved documents
    graph_context: GraphContext  # Related entities
    metadata: RetrievalMetadata  # Processing stats
    suggestions: List[str]       # Follow-up queries
    confidence_score: float      # Answer confidence
```

## Configuration

All configuration via environment variables (see `src/settings.py`):

| Variable | Description | Default |
|----------|-------------|---------|
| `NEO4J_URI` | Neo4j connection URI | bolt://localhost:7687 |
| `NEO4J_USER` | Neo4j username | neo4j |
| `NEO4J_PASSWORD` | Neo4j password | - |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI key | - |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint | - |
| `AZURE_OPENAI_DEPLOYMENT` | Chat model deployment | gpt-4o |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Embedding model | text-embedding-3-small |
| `VECTOR_SEARCH_ENABLED` | Enable vector search | false |
| `HYBRID_SEARCH_ENABLED` | Enable hybrid search | false |
| `ENTITY_RESOLUTION_ENABLED` | Enable entity resolution | true |
| `LOG_LEVEL` | Logging level | INFO |

## Error Handling

The service implements graceful degradation:
- If LLM unavailable → Falls back to heuristic parsing
- If vector search fails → Falls back to keyword-only
- If entity resolution fails → Uses unresolved entities
- If Neo4j unavailable → Returns error with details

## Performance Considerations

- **Connection Pooling**: Neo4j connections are cached globally
- **LLM Caching**: Consider adding Redis cache for repeated queries
- **Batch Processing**: Embeddings generated in batches
- **Timeout Handling**: All LLM calls have configurable timeouts
