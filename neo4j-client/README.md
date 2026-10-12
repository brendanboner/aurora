# Neo4j Client Library

A shared Python library for interacting with the Aurora Neo4j Knowledge Graph.

## Overview

`neo4j-client` provides a standardized interface for all Aurora microservices to interact with the Neo4j knowledge graph. It includes node models, connection management, and repository patterns for common operations.

## Quick Start

### Running Tests

**All tests run in Docker - no local Python setup needed!**

```bash
cd neo4j-client

# Run all tests with detailed output (recommended)
make test-verbose

# Run all tests (summary only)
make test

# Run similarity algorithm tests
make test-similarity

# Run specific test case
make test-case NAME="IEEE 802.11 Variants - Should Deduplicate"

# Run threshold analysis
make test-thresholds

# See all commands
make help
```

Each command automatically builds the Docker image if needed. Just run the test you want!

📚 **Detailed documentation:**
- [TESTING.md](TESTING.md) - Quick testing guide
- [tests/DOCKER_SETUP.md](tests/DOCKER_SETUP.md) - Docker details
- [tests/README.md](tests/README.md) - Test framework documentation

## Installation

### Development Installation (Editable)

From the Aurora root directory:

```bash
pip install -e ./neo4j-client
```

This allows you to use the library while continuing to develop it.

### In Microservices

Add to your `requirements.txt`:

```
-e ../neo4j-client
```

Or install directly:

```bash
cd /path/to/Aurora
pip install -e ./neo4j-client
```

## Usage

### Basic Connection

```python
from neo4j_client import Neo4jClient

# Initialize with explicit configuration
client = Neo4jClient(
    uri="bolt://localhost:7687",
    user="neo4j",
    password="password",
    database="neo4j"
)

# Connect
client.connect()

# Execute queries
results = client.execute_query("MATCH (n:Resource) RETURN n LIMIT 10")

# Close connection
client.close()
```

### Using the Repository

```python
from neo4j_client import Neo4jClient, GraphRepository

# Setup
client = Neo4jClient(uri="bolt://localhost:7687", user="neo4j", password="password")
client.connect()
repo = GraphRepository(client)

# Create nodes
resource_data = {
    "title": "Wi-Fi 6E Technical Overview",
    "url": "https://example.com/wifi6e",
    "category": "white paper",
    "summary": "Comprehensive overview of Wi-Fi 6E technology...",
    "source": "wi-fi-alliance",
    "publish_date": "2024-01-15",
    "scraped_at": 1699123456.78,
    "key_technologies": ["Wi-Fi 6E", "6 GHz"],
    "industry_sectors": ["Telecommunications"],
    "use_cases": ["High-bandwidth applications"]
}

repo.create_resource(resource_data)

# Create relationships
repo.create_topic("Wi-Fi 6E")
repo.link_resource_to_topic("https://example.com/wifi6e", "Wi-Fi 6E")
```

### Using the Deduplicator

The `NodeDeduplicator` service identifies and handles duplicate nodes. It can be used for batch processing or individual node checks.

#### Batch Processing (Digester Service)

```python
from neo4j_client import Neo4jClient, NodeDeduplicator, GraphRepository

# Setup
client = Neo4jClient(uri="bolt://localhost:7687", user="neo4j", password="password")
client.connect()

# Create deduplicator and repository
deduplicator = NodeDeduplicator(client)
repo = GraphRepository(client)

# Prepare entities (from your data extraction pipeline)
entities = {
    "nodes": {
        "resource": resource_model,
        "topics": [topic_models],
        "people": [person_models],
        "organizations": [org_models]
    },
    "relationships": [relationship_models]
}

# Deduplicate before insertion
deduped_entities = deduplicator.deduplicate_nodes(
    entities,
    k_neighbors=5,
    similarity_threshold=0.85,
    llm_review_threshold=0.6
)

# Insert deduplicated entities
stats = repo.insert_entities(deduped_entities)
```

#### Individual Node Checking (Curator Service)

```python
from neo4j_client import Neo4jClient, NodeDeduplicator
from neo4j_client.models import Topic

# Setup
client = Neo4jClient(uri="bolt://localhost:7687", user="neo4j", password="password")
client.connect()

deduplicator = NodeDeduplicator(client)

# Create a new topic
new_topic = Topic(
    topic_id="wifi-7",
    name="Wi-Fi 7",
    classification="technology",
    embedding=[0.1, 0.2, ...]  # Your embedding vector
)

# Check if it's a duplicate using the convenience method
duplicate_info = deduplicator.check_topic_duplicate(new_topic)

if duplicate_info:
    print(f"Found duplicate! Existing ID: {duplicate_info['existing_id']}")
    print(f"Similarity score: {duplicate_info['similarity_score']}")
    print(f"Action: {duplicate_info['action']}")
    # Use the existing topic instead
    existing_topic_id = duplicate_info['existing_id']
else:
    print("No duplicate found - safe to insert")
    # Insert the new topic

# Or use the generic method for any node type
duplicate_info = deduplicator.find_duplicate(
    new_topic,
    "Topic",
    k_neighbors=5,
    similarity_threshold=0.85,
    llm_review_threshold=0.6
)
```

### Initialize Graph

```python
from neo4j_client import Neo4jClient

client = Neo4jClient(uri="bolt://localhost:7687", user="neo4j", password="password")
client.connect()

# Create constraints
client.create_constraints()

# Load base data (organizations, data sources)
client.initialize_base_data()
```

## Node Models

The library defines the following node types:

- **Resource**: Documents with metadata
- **Topic**: Subject areas
- **Standard**: Technical standards
- **StandardEdition**: Specific standard versions
- **Organization**: Organizations
- **DataSource**: Data sources

## Relationships

- `(Resource)-[:COVERS_TOPIC]->(Topic)`
- `(Resource)-[:REFERENCES_STANDARD]->(Standard)`
- `(Resource)-[:REFERENCES_EDITION]->(StandardEdition)`
- `(StandardEdition)-[:VERSION_OF]->(Standard)`
- `(Resource)-[:FROM_SOURCE]->(DataSource)`

## Architecture

```
neo4j_client/
├── __init__.py           # Public API
├── client.py             # Neo4j connection management
├── models.py             # Node model definitions
└── repository.py         # Graph operations
```

## Configuration

The library accepts configuration at initialization time. Each microservice should read its own configuration and pass it to the client:

```python
# In your microservice
from neo4j_client import Neo4jClient
from your_config import settings

client = Neo4jClient(
    uri=settings.neo4j_uri,
    user=settings.neo4j_user,
    password=settings.neo4j_password,
    database=settings.neo4j_database
)
```

### Embedding Model Configuration

The library supports two embedding providers for generating vector embeddings:

1. **SentenceTransformers** (default) - Local, fast, free
2. **Azure OpenAI** - API-based, high quality, requires API key and endpoint

Configure via environment variables:

```bash
# Option 1: SentenceTransformers (default, 768 dimensions)
export EMBEDDING_PROVIDER=sentence-transformers
export EMBEDDING_MODEL=sentence-transformers/all-mpnet-base-v2

# Option 2: Azure OpenAI (1536 dimensions for text-embedding-3-small)
export EMBEDDING_PROVIDER=openai
export EMBEDDING_MODEL=text-embedding-3-small
export AZURE_OPENAI_API_KEY=your-api-key-here
export AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
export AZURE_OPENAI_API_VERSION=2024-08-01-preview  # Optional, defaults to this version
```

**Provider Comparison:**

| Provider | Model | Dimensions | Cost | Speed | Quality |
|----------|-------|------------|------|-------|---------|
| SentenceTransformers | all-mpnet-base-v2 | 768 | Free | Fast (local) | Good |
| Azure OpenAI | text-embedding-3-small | 1536 | $0.02/1M tokens | API latency | Excellent |

**Important Notes:**
- Changing embedding providers requires **recreating all vector indexes** in Neo4j with the new dimension size
- All existing node embeddings must be regenerated
- Don't mix embedding providers in the same database
- Azure OpenAI requires the same credentials used for LLM operations (AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT)

**Neo4j Vector Index Configuration:**

When using different embedding models, update your index dimension:

```cypher
-- For SentenceTransformers (768 dimensions)
CREATE VECTOR INDEX topic_embedding_index IF NOT EXISTS
FOR (n:Topic) ON (n.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 768,
  `vector.similarity_function`: 'cosine'
}};

-- For OpenAI text-embedding-3-small (1536 dimensions)
CREATE VECTOR INDEX topic_embedding_index IF NOT EXISTS
FOR (n:Topic) ON (n.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 1536,
  `vector.similarity_function`: 'cosine'
}};
```

## Development

The library is designed to be framework-agnostic and has minimal dependencies:

- `neo4j` - Official Neo4j Python driver
- Python 3.10+

## License

Proprietary
