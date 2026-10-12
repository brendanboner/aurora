# Aurora CLI

Command-line interface for querying the Aurora Oracle service.

## Overview

The Aurora CLI provides command-line access to the Oracle service for natural language queries against the knowledge graph. It's designed for development, testing, and scripting purposes, bypassing Cognito authentication using header-based auth with user context from environment variables.

## Prerequisites

1. **Oracle service must be exposed locally** - The `docker-compose.override.yml` should expose Oracle on port 8003:
   ```yaml
   oracle:
     ports:
       - "8003:8000"
   ```

2. **Environment variables configured** - Set `TEST_USER_ID` and `TEST_USER_EMAIL` in the workspace root `.env` file (see `.env.example` in this directory)

## Installation

Using `uv` (recommended):
```bash
uv sync
```

Or using pip:
```bash
pip install -r requirements.txt
```

## Configuration

The CLI reads user context from environment variables defined in the workspace root `.env` file:

```bash
# Required: User credentials for dev/testing
TEST_USER_ID=e4b864d8-5061-7019-73e7-c42cbfb4a2b7
TEST_USER_EMAIL=bbonner@extremenetworks.com

# Optional: Override Oracle URL (default: http://localhost:8003)
AURORA_ORACLE_URL=http://localhost:8003

# Optional: User role (default: user)
AURORA_ROLE=user
```

See `.env.example` for a complete template.

## Usage

**Important:** Always quote your questions to prevent shell interpretation of special characters (?, *, etc.)

### Basic Query
```bash
./aurora "What are the latest Wi-Fi Alliance updates?"
```

### Retrieval Mode (documents only, no LLM answer)
```bash
./aurora --mode retrieval "What are the latest IEEE standards?"
```

### Filter by Datasources
```bash
./aurora --datasources wfa_resource_page,broadcast "Tell me about Wi-Fi 7"
```

### Verbose Mode (show query ID, confidence, graph context)
```bash
./aurora -v "What happened last week in wireless communications?"
```

### Custom Oracle URL
```bash
./aurora --oracle-url http://production-oracle:8003 "What is Wi-Fi 6E?"
```

### Limit Documents Retrieved
```bash
./aurora --max-documents 5 "Give me a quick summary of recent updates"
```

## Features

- 🔐 **Auth Bypass for Dev**: Uses header-based authentication (X-User-Id, X-User-Email) to bypass Cognito
- 🎯 **Personalization**: Automatically applies user preferences from your configured user profile
- 📊 **Multiple Modes**: Choose between retrieval (docs only) or answer (LLM-generated response)
- 🔍 **Datasource Filtering**: Filter results by specific datasources (wfa, broadcast, etc.)
- 📈 **Rich Metadata**: View confidence scores, query IDs, graph context, and more in verbose mode
- 💡 **Query Suggestions**: Get related query suggestions to explore further
- 🔄 **Spinner Animation**: Shows progress while waiting for Oracle response
- 📚 **Source Citations**: Shows up to 10 most relevant documents with metadata

## Output Format

### Answer Mode (default)
```
🔍 Question: What are the latest Wi-Fi Alliance updates?
👤 User: bbonner@extremenetworks.com (e4b864d8-5061-7019-73e7-c42cbfb4a2b7)
🎯 Mode: answer

[Spinner: Generating answer with Oracle...]

================================================================================
💬 ANSWER
================================================================================

[LLM-generated answer based on knowledge graph documents]

================================================================================
📄 SOURCES (15 documents retrieved)
================================================================================

[1] Wi-Fi Alliance Announces New Certification Program
    📅 2025-11-15
    🔗 https://...
    📊 Datasource: wfa
    🏷️  Wi-Fi 6, Certification, Standards

[2] Latest Wi-Fi Technology Updates
    📅 2025-11-10
    🔗 https://...
    📊 Datasource: broadcast

... and 13 more documents

================================================================================
💡 RELATED QUERIES
================================================================================
  1. What are the key features of the new certification program?
  2. How does this compare to previous Wi-Fi standards?
  3. When will devices be available with this certification?

================================================================================
✅ Query complete
================================================================================
```

### Verbose Mode (--verbose)
Includes additional metadata:
```
================================================================================
🔍 QUERY METADATA
================================================================================
Query ID: q_abc123...
Pipeline: fast
Confidence Score: 0.89
Personalization Applied: True

Graph Context:
  Entities: 8
  Relationships: 15
  Top entities: Wi-Fi Alliance, Wi-Fi 6E, Certification Program, ...

[... rest of output ...]
```

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--oracle-url` | Oracle service URL | `http://localhost:8003` or `AURORA_ORACLE_URL` |
| `--mode` | Query mode: `retrieval`, `answer`, or `auto` | `answer` |
| `--datasources` | Comma-separated datasource IDs to filter | All datasources |
| `--max-documents` | Maximum documents to retrieve | `10` |
| `-v, --verbose` | Show detailed metadata (query ID, confidence, graph context) | Off |

## Examples

### Ask about recent updates
```bash
./aurora "What happened this week?"
```

### Query specific organization with datasource filter
```bash
./aurora --datasources wfa_resource_page "What are the latest Wi-Fi Alliance standards?"
```

### Retrieval-only mode for finding documents
```bash
./aurora --mode retrieval --datasources broadcast "Recent wireless industry news"
```

### Verbose output for debugging
```bash
./aurora -v "Tell me about Wi-Fi 6 and Wi-Fi 6E"
```

### Combine multiple options
```bash
./aurora --mode answer --datasources wfa_resource_page,ieee --max-documents 20 -v \
  "What are the differences between 802.11ax and 802.11be?"
```

## Document Upload (Parse Command)

Upload local documents to the knowledge graph:

```bash
./aurora parse /path/to/document.pdf --organization "Wi-Fi Alliance" --category whitepaper
```

See parse-specific help:
```bash
./aurora parse --help
```

## Authentication

The CLI uses **header-based authentication** for dev/testing purposes:
- `X-User-Id`: User UUID from `TEST_USER_ID` env var
- `X-User-Email`: Email from `TEST_USER_EMAIL` env var  
- `X-User-Role`: Role from `AURORA_ROLE` env var (default: `user`)

This bypasses the production Cognito authentication flow. The Oracle service trusts these headers from internal/CLI requests.

### Personalization

Queries use the configured `TEST_USER_ID` to load user preferences from the database. This enables:
- Tailored answer narratives based on your interests
- Topic and organization preferences from your profile
- Personalized query suggestions

Set `--mode auto` (default) to enable automatic personalization.

## Troubleshooting

### Oracle not responding
```bash
# Check if Oracle is running and exposed
curl http://localhost:8003/oracle/health

# Verify Oracle port in docker-compose.override.yml
grep -A 2 "oracle:" docker-compose.override.yml

# Restart Oracle service
docker-compose restart oracle
```

### Environment variables not loaded
```bash
# Verify .env file exists in workspace root
cat ../.env | grep TEST_USER

# Manually export if needed
export TEST_USER_ID=e4b864d8-5061-7019-73e7-c42cbfb4a2b7
export TEST_USER_EMAIL=bbonner@extremenetworks.com
```

### Permission denied
```bash
chmod +x aurora
```

### Module not found
```bash
uv sync
# or
pip install -r requirements.txt
```

### Datasource IDs
To list available datasources:
```bash
curl http://localhost:8003/oracle/datasources
```

## Integration

The CLI can be used in scripts:

```bash
#!/bin/bash
# daily-update.sh

echo "Getting daily wireless industry updates..."
./aurora What happened today in wireless communications? > daily-report.txt
```

Or in automation:

```bash
# Cron job: daily at 9 AM
0 9 * * * cd /path/to/cli && ./aurora "What are today's updates?" | mail -s "Daily Aurora Report" user@example.com
```

## Architecture

```
CLI (aurora_query.py)
    ↓
    [Headers: X-User-Id, X-User-Email, X-User-Role]
    ↓
Oracle Service (localhost:8003)
    ↓
    [Loads user preferences, applies personalization]
    ↓
Knowledge Graph + LLM
    ↓
Structured Response (QueryResponse model)
```

The CLI communicates directly with the Oracle service, which handles:
- Query parsing and understanding
- Knowledge graph retrieval with caching
- User preference loading and personalization
- LLM answer generation
- Citation and source tracking
