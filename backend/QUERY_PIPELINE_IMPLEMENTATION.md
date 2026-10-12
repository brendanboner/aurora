# Question-Answering Pipeline Implementation

## Overview

The backend question-answering pipeline has been completely redesigned to ensure all queries are answered based on knowledge graph data rather than generic LLM responses. The pipeline now follows a strict, deterministic workflow that integrates user preferences, performs intelligent filter extraction, and retrieves relevant documents from Neo4j before generating responses.

## Pipeline Architecture

### Complete Workflow

```
User Query → Load Preferences → LLM Filter Extraction → Merge Filters → 
Neo4j Query → Document Retrieval → LLM Summarization → Structured Response
```

### Detailed Steps

#### 1. **Accept Query and User Identification**
- Endpoint: `POST /query`
- Input: `user_id` and natural language `question`
- Entry point: `query_engine.run_query()`

#### 2. **Load User Preferences** 
- Fetches user preferences from PostgreSQL
- Retrieves: topics, organisations, people
- Handles missing preferences gracefully (proceeds without them)
- File: `src/services/postgres.py::get_user_preferences()`

#### 3. **LLM Filter Extraction**
- Sends question to Azure OpenAI for structured analysis
- Extracts: topics, organisations, people, date ranges, other constraints
- Enhanced to recognize high-level subjects and direct entity references
- Fallback to heuristic extraction if LLM unavailable
- File: `src/services/llm_service.py::parse_query_to_filters()`

**Key Enhancement**: The LLM prompt now explicitly instructs the model to:
- Identify when organizations are directly mentioned (e.g., "Wi-Fi Alliance", "IEEE")
- Extract high-level technical topics (e.g., "Wi-Fi 6", "802.11ax", "Bluetooth")
- Focus on wireless communications and standards domain
- Provide better context for broad vs. specific queries

#### 4. **Merge Filters with Preferences**
- Combines LLM-extracted filters with user preferences
- Treats both as **relevance signals**, not hard constraints
- Strategy:
  - LLM filters take priority for specific entities
  - User preferences augment to improve relevance
  - Deduplicates entities (case-insensitive)
  - Increases result limit if many filters present
- File: `src/services/query_engine.py::_merge_filters_with_preferences()`

**Important**: This is NOT an AND filter - documents matching query filters are returned even if they don't match all preferences.

#### 5. **Query Neo4j Knowledge Graph**
- Executes enhanced Cypher query with merged filters
- New relevance-based ranking algorithm
- File: `neo4j_client/repository.py::get_recent_resources()`

**Query Enhancements**:
- **Alias Matching**: Matches topics/orgs by name OR aliases
- **Flexible Matching**: Treats filters as relevance signals
- **Weighted Scoring**:
  - Topic match: 40%
  - Organization match: 30%
  - People match: 20%
  - Relationship quality (confidence): 10%
- **Recency Boost**: More recent documents ranked higher
- **Final Ranking**: 70% relevance + 30% recency

Returns most relevant documents with full metadata:
- title, url, publish_date, summary
- topics, organisations, people
- datasources

#### 6. **LLM Summarization**
- Passes question + retrieved documents to LLM
- Incorporates user preferences for context-aware responses
- Strict instructions to avoid hallucination
- File: `src/services/llm_service.py::summarise_documents()`

**Key Instructions to LLM**:
- Answer ONLY from provided documents
- Reference specific documents
- Consider user preferences when prioritizing information
- Be concise but specific
- Do not make up information

#### 7. **Return Structured Response**
- Generated natural language answer
- List of retrieved documents with metadata
- Filters applied (separated by source):
  - from_query (LLM extracted)
  - from_preferences (user settings)
  - applied (merged final filters)
- Document count
- Topic truncation for display (max 10 per document)

## File Changes

### 1. `backend/src/services/query_engine.py`
**Complete rewrite** to implement the full pipeline:
- `run_query()`: Main orchestration function
- `_merge_filters_with_preferences()`: Intelligent filter merging
- `_format_documents_for_response()`: Response formatting with topic limits

### 2. `backend/src/services/llm_service.py`
**Enhanced** filter extraction and summarization:
- `parse_query_to_filters()`: Improved prompt for better entity recognition
- `summarise_documents()`: Added user preference context parameter

### 3. `neo4j_client/neo4j_client/repository.py`
**Enhanced** Neo4j query with relevance ranking:
- `get_recent_resources()`: Complete query rewrite with:
  - Alias matching for topics and organizations
  - Multi-factor relevance scoring
  - Recency weighting
  - Flexible filtering (OR semantics within entity types)

## Key Features

### ✅ Preference-Aware but Not Constrained
- User preferences influence ranking
- Query-specified entities always respected
- No artificial narrowing of results

### ✅ Anti-Hallucination Measures
- Responses MUST be based on retrieved documents
- LLM instructed to reference sources
- Empty result handling (clear "no documents found" message)

### ✅ Deterministic Operation
1. LLM interprets question → structured filters
2. Preferences merged as relevance signals
3. Neo4j queried with combined filters
4. Documents summarized (not generated)
5. Response constructed from graph data

### ✅ Resilient to Missing Data
- Works without user preferences
- Fallback to heuristic parsing if LLM unavailable
- Graceful handling of empty results
- Continues operation on partial failures

### ✅ Better Entity Recognition
- Direct mentions captured ("Wi-Fi Alliance updates")
- Technical standards recognized ("802.11ax", "Wi-Fi 6")
- Industry organizations identified
- Domain-specific knowledge applied

## API Response Format

```json
{
  "answer": "Natural language response based on retrieved documents...",
  "filters": {
    "applied": {
      "topics": ["Wi-Fi 6", "802.11ax"],
      "organisations": ["Wi-Fi Alliance"],
      "people": [],
      "start_date": null,
      "end_date": null,
      "limit": 30
    },
    "from_query": {
      "topics": ["Wi-Fi 6"],
      "organisations": ["Wi-Fi Alliance"],
      "people": [],
      "limit": 20
    },
    "from_preferences": {
      "topics": ["802.11ax", "Bluetooth"],
      "organisations": ["IEEE"],
      "people": []
    }
  },
  "documents": [
    {
      "title": "Wi-Fi Alliance Announces Wi-Fi 6E",
      "url": "https://...",
      "publish_date": "2025-11-15",
      "summary": "...",
      "topics": ["Wi-Fi 6", "Wi-Fi 6E", "..."],
      "organisations": ["Wi-Fi Alliance"],
      "topics_truncated": false,
      "total_topics": 8
    }
  ],
  "document_count": 15
}
```

## Testing

Run the test script to verify the pipeline:

```bash
cd backend
python test_query_pipeline.py
```

This tests:
- User preference loading
- Filter extraction
- Filter merging
- Document retrieval
- Answer generation
- Generic response detection

## Configuration

Required environment variables:
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_DEPLOYMENT`
- `AZURE_OPENAI_API_VERSION` (default: 2024-08-01-preview)
- `NEO4J_URI`
- `NEO4J_USER`
- `NEO4J_PASSWORD`
- `PG_DSN` (PostgreSQL connection string)

## Troubleshooting

### Symptom: Generic responses despite documents available
**Cause**: LLM not following instructions or ignoring documents
**Solution**: Check LLM prompt in `summarise_documents()`, verify documents contain relevant content

### Symptom: No documents retrieved
**Cause**: Filters too restrictive or entity matching failing
**Solution**: Check merged filters in logs, verify entity names/aliases in Neo4j

### Symptom: Wrong entities extracted
**Cause**: LLM misunderstanding query
**Solution**: Review prompt in `parse_query_to_filters()`, add domain-specific examples

### Symptom: User preferences not applied
**Cause**: Preference merging or loading failure
**Solution**: Check `get_user_preferences()` return value, verify merge logic

## Future Improvements

1. **Semantic Search**: Add vector similarity for content-based retrieval
2. **Query Expansion**: Automatically expand queries with related terms
3. **Feedback Loop**: Learn from user interactions to improve relevance
4. **Caching**: Cache LLM filter extractions for similar queries
5. **Multi-hop Reasoning**: Support complex queries requiring graph traversal
