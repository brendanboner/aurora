# Neo4j Client Library

A shared Python library for interacting with the Aurora Neo4j Knowledge Graph.

## Overview

`neo4j-client` provides a standardized interface for all Aurora microservices to interact with the Neo4j knowledge graph. It includes node models, connection management, and repository patterns for common operations.

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
    "resource_type": "white paper",
    "summary": "Comprehensive overview of Wi-Fi 6E technology...",
    "source": "wi-fi-alliance",
    "publish_date": "2024-01-15",
    "timestamp": 1699123456.78,
    "key_technologies": ["Wi-Fi 6E", "6 GHz"],
    "industry_sectors": ["Telecommunications"],
    "use_cases": ["High-bandwidth applications"]
}

repo.create_resource(resource_data)

# Create relationships
repo.create_topic("Wi-Fi 6E")
repo.link_resource_to_topic("https://example.com/wifi6e", "Wi-Fi 6E")
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

## Development

The library is designed to be framework-agnostic and has minimal dependencies:

- `neo4j` - Official Neo4j Python driver
- Python 3.10+

## License

Proprietary
