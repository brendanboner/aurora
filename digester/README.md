# Document Digester Microservice

A Python microservice that processes documents from RabbitMQ, extracts metadata using LLM, and builds a Neo4j knowledge graph.

## Overview

The Document Digester service:
1. Consumes messages from a RabbitMQ queue containing document information
2. Extracts metadata using Azure OpenAI LLM
3. Validates and normalizes the extracted metadata  
4. Inserts structured data into a Neo4j knowledge graph using the shared `neo4j-client` library

## Architecture

The service processes documents through the following pipeline:

```
RabbitMQ → LLM Extraction → Validation → Normalization → Neo4j KG
```

### Components

- **LLM** (`llm/`): Metadata extraction using Azure OpenAI with content chunking support
- **Normalization** (`normalization/`): Data validation and normalization
- **Utils** (`utils/`): Logging utilities

### Shared Dependencies

This service uses shared libraries for infrastructure components:
- **`rabbitmq-client`** - RabbitMQ consumer/producer (located at `../rabbitmq-client`)
- **`neo4j-client`** - Neo4j knowledge graph operations (located at `../neo4j-client`)

These libraries provide:
- RabbitMQ connection management and message handling
- Neo4j connection management
- Node models (Resource, Topic, Standard, etc.)
- Repository patterns for CRUD operations

## Message Format

The service expects messages in the following JSON format:

```json
{
  "title": "Document Title",
  "url": "https://example.com/resource",
  "resource_type": "white paper",
  "content": "Extracted text content...",
  "publish_date": "2024-01-15",
  "source": "wi-fi-alliance",
  "timestamp": 1699123456.78
}
```

## Knowledge Graph Structure

The service creates and manages the following node types:

- **Resource**: Documents with metadata (summary, technologies, sectors, use cases)
- **Topic**: Subject areas covered by resources
- **Standard**: Technical standards referenced
- **StandardEdition**: Specific versions of standards
- **Organization**: Pre-loaded organizations (Wi-Fi Alliance, IEEE, etc.)
- **DataSource**: Pre-loaded data sources

### Relationships

- `(Resource)-[:COVERS_TOPIC]->(Topic)`
- `(Resource)-[:REFERENCES_STANDARD]->(Standard)`
- `(Resource)-[:REFERENCES_EDITION]->(StandardEdition)`
- `(StandardEdition)-[:VERSION_OF]->(Standard)`
- `(Resource)-[:FROM_SOURCE]->(DataSource)`

## Prerequisites

- Docker
- Make  
- Environment variables configured (see Environment Setup below)

## Environment Setup

Copy the environment template and configure your settings:

```bash
cp .env.example .env
```

Edit `.env` with your specific configuration values. The template includes all required environment variables for:
- Docker network settings
- RabbitMQ connection details
- Neo4j database configuration
- Azure OpenAI API credentials
- Content processing settings
- Logging levels

See [../.env.example](../.env.example) for the complete configuration template.

## Deployment

### Shared Development Mode

Deploy using shared infrastructure (efficient for multi-service development):

```bash
# Deploy using shared infrastructure
make deploy-local
```

This will:
1. Validate environment variables
2. Ensure RabbitMQ and Neo4j are running (starts if needed)
3. Build the digester Docker image
4. Deploy the service container with proper networking

### Isolated Development Mode

For complete isolation during development:

```bash
# Deploy with isolated infrastructure
make deploy-isolated
```

This creates a completely isolated environment with its own RabbitMQ and Neo4j instances on different ports.

## Available Commands

```bash
make help             # Show all available commands
make deploy-local     # Deploy on shared network (development)
make deploy-isolated  # Deploy with isolated infrastructure (development)
make clean-isolated   # Clean ALL isolated environments (all services)
make clean-shared     # Clean shared resources (use with caution)
make nuke            # Remove everything (containers + images + cleanup)
```

## Configuration

### Content Processing

For long documents, content is automatically chunked:
- `MAX_CHUNK_SIZE`: Characters per chunk (default: 8000)
- `CHUNK_OVERLAP`: Overlap between chunks (default: 500)

### LLM Provider

Uses Azure OpenAI for metadata extraction with configurable parameters:
- `AZURE_OPENAI_DEPLOYMENT`: Your Azure OpenAI deployment name
- `LLM_MAX_TOKENS`: Maximum tokens per request (default: 4096)  
- `LLM_TEMPERATURE`: Response creativity (default: 0.1)

## Metadata Extraction

The LLM extracts the following metadata fields:

- **summary**: 2-3 sentence document summary
- **topics**: Relevant subjects covered
- **standards**: Technical standards mentioned
- **standard_editions**: Specific standard versions
- **key_technologies**: Technologies discussed
- **industry_sectors**: Relevant industry sectors
- **use_cases**: Practical applications

## Base Data

The service initializes with hardcoded data:

### Organizations
- Wi-Fi Alliance

### Data Sources
- wi-fi-alliance


## Monitoring & Management

### Neo4j Browser

- **Shared Mode**: http://localhost:7474  
- **Isolated Mode**: http://localhost:7475
- **Default Credentials**: See your `.env` file (NEO4J_USER/NEO4J_PASSWORD)

### RabbitMQ Management

- **Shared Mode**: http://localhost:15672
- **Isolated Mode**: http://localhost:15673  
- **Default Credentials**: See your `.env` file (RABBITMQ_USER/RABBITMQ_PASSWORD)

## Service Lifecycle

When deployed, the service automatically:
1. Connects to Neo4j and initializes base data (organizations, data sources)
2. Creates necessary database constraints  
3. Connects to RabbitMQ and starts consuming messages
4. Processes each message through the extraction pipeline
5. Inserts structured data into the knowledge graph

### Graceful Shutdown

The containerized service handles shutdown signals gracefully:
1. Stops consuming new messages
2. Closes RabbitMQ connection
3. Closes Neo4j connection


