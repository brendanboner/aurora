# Backend Question-Answering Pipeline - Implementation Summary

## Problem Statement

The backend question-answering pipeline was providing generic responses instead of leveraging the knowledge graph. The system needed to ensure every query follows a deterministic workflow that:
1. Loads user preferences from PostgreSQL
2. Extracts query filters using LLM
3. Merges preferences with query filters intelligently
4. Queries Neo4j for relevant documents
5. Generates context-aware responses from retrieved documents
6. Returns structured results with full traceability

## Solution Overview

A complete redesign of the query pipeline with these core principles:
- **Knowledge Graph First**: All responses based on Neo4j documents, not LLM hallucination
- **Preference Integration**: User preferences as relevance signals, not hard filters
- **Intelligent Entity Recognition**: Enhanced LLM prompts for domain-specific extraction
- **Relevance-Based Ranking**: Multi-factor scoring combining topic match, recency, and relationship quality
- **Full Traceability**: Response includes filters applied, sources used, and document metadata

## Files Modified

### 1. `backend/src/services/query_engine.py` - Complete Rewrite
**Changes**:
- Implemented full pipeline orchestration in `run_query()`
- Added user preference loading from PostgreSQL
- Created `_merge_filters_with_preferences()` for intelligent filter merging
- Added `_format_documents_for_response()` for clean API responses
- Comprehensive logging throughout pipeline

**Key Functions**:
```python
def run_query(user_id: int, question: str) -> Dict[str, Any]:
    """
    Full pipeline:
    1. Load preferences
    2. Extract LLM filters
    3. Merge with preferences
    4. Query Neo4j
    5. Summarize with context
    6. Return structured response
    """
```

### 2. `backend/src/services/llm_service.py` - Enhanced
**Changes**:
- Improved `parse_query_to_filters()` with better prompt engineering
- Enhanced LLM instructions to recognize:
  - Direct organization mentions
  - High-level technical topics
  - Domain-specific standards and protocols
- Updated `summarise_documents()` to accept user preferences
- Added anti-hallucination instructions to summarizer

**Before**: Generic prompt asking to "extract entities"
**After**: Domain-specific prompt with explicit instructions for wireless/standards context

### 3. `neo4j_client/neo4j_client/repository.py` - Enhanced Query
**Changes**:
- Complete rewrite of `get_recent_resources()` Cypher query
- Added alias matching for topics and organizations
- Implemented multi-factor relevance scoring:
  - Topic match: 40%
  - Organization match: 30%
  - People match: 20%
  - Relationship quality: 10%
- Added recency weighting (newer documents ranked higher)
- Combined ranking: 70% relevance + 30% recency
- Flexible filtering (OR within entity types, AND across types)

**Before**: Simple date-based sorting with basic entity matching
**After**: Sophisticated relevance ranking with alias support and quality signals

## New Files Created

### 1. `backend/test_query_pipeline.py`
Comprehensive test script that validates:
- User preference loading
- LLM filter extraction
- Filter merging logic
- Document retrieval
- Answer generation
- Generic response detection

Usage: `python backend/test_query_pipeline.py`

### 2. `backend/QUERY_PIPELINE_IMPLEMENTATION.md`
Complete documentation including:
- Architecture overview
- Detailed step-by-step workflow
- File-by-file changes
- API response format
- Configuration requirements
- Troubleshooting guide
- Future improvements

## Implementation Details

### Filter Merging Strategy
```python
# LLM extracts: ["Wi-Fi 6"]
# User prefs: ["802.11ax", "Bluetooth"]
# Merged: ["Wi-Fi 6", "802.11ax", "Bluetooth"]

# All treated as relevance signals
# Documents matching ANY are ranked by how many they match
```

### Relevance Scoring Example
```
Document matches:
- 2 of 3 topics (66% topic match)
- 1 of 1 org (100% org match)
- 0 of 0 people (100% - no filter)
- Average relationship confidence: 0.85

Topic score: 0.66 × 0.4 = 0.264
Org score: 1.0 × 0.3 = 0.300
People score: 1.0 × 0.2 = 0.200
Quality score: 0.85 × 0.1 = 0.085

Relevance: 0.849
Recency: 0.950 (recent doc)
Final: 0.849 × 0.7 + 0.950 × 0.3 = 0.879
```

### Response Structure
```json
{
  "answer": "Graph-based response...",
  "filters": {
    "applied": {...},      // Final merged filters
    "from_query": {...},   // LLM extracted
    "from_preferences": {...} // User settings
  },
  "documents": [...],      // Retrieved docs
  "document_count": 15
}
```

## Key Features Implemented

### ✅ User Preference Integration
- Loads from PostgreSQL automatically
- Merges with query filters intelligently
- Gracefully handles missing preferences
- Preferences influence ranking, don't exclude results

### ✅ Enhanced Entity Recognition
- Domain-specific prompts for wireless/standards
- Recognizes direct organization mentions
- Identifies technical topics and standards
- Handles abbreviations and aliases

### ✅ Relevance-Based Ranking
- Multi-factor scoring system
- Alias matching for flexible entity recognition
- Recency weighting for time-sensitive queries
- Relationship quality signals from graph

### ✅ Anti-Hallucination Measures
- Responses MUST cite retrieved documents
- Clear instructions to LLM summarizer
- No generic fallbacks when documents exist
- Document metadata included in response

### ✅ Full Traceability
- Filter sources tracked (query vs preferences)
- Applied filters shown separately
- Document count reported
- Logging at each pipeline stage

### ✅ Resilience
- Works without user preferences
- Fallback parsing if LLM unavailable
- Handles empty results gracefully
- Continues on partial failures

## Testing the Implementation

1. **Start the services**:
   ```bash
   docker-compose up -d
   cd backend && make run
   ```

2. **Run the test script**:
   ```bash
   python backend/test_query_pipeline.py
   ```

3. **Test via API**:
   ```bash
   curl -X POST http://localhost:8000/query \
     -H "Content-Type: application/json" \
     -d '{
       "user_id": 1,
       "question": "What are the latest Wi-Fi Alliance updates?"
     }'
   ```

4. **Check logs**:
   ```bash
   docker logs -f aurora-backend
   ```

Expected log output:
```
INFO:query_engine:Processing query for user_id=1: What are the latest...
INFO:query_engine:User preferences loaded: 5 topics, 2 orgs, 0 people
INFO:llm_service:LLM extracted filters: {'topics': ['Wi-Fi'], 'organisations': ['Wi-Fi Alliance'], ...}
INFO:query_engine:Merged filters: {'topics': ['Wi-Fi', 'Topic1', ...], ...}
INFO:query_engine:Retrieved 15 documents from knowledge graph
```

## Verification Checklist

- [x] User preferences loaded from PostgreSQL
- [x] LLM extracts structured filters from query
- [x] Filters merged intelligently (union, not intersection)
- [x] Neo4j query uses merged filters
- [x] Relevance ranking considers multiple factors
- [x] Alias matching works for topics/organizations
- [x] Recency influences ranking
- [x] Documents retrieved with full metadata
- [x] Summarizer receives user preferences
- [x] Answer references retrieved documents
- [x] Response includes filter breakdown
- [x] Topic display limited for readability
- [x] Pipeline resilient to missing preferences
- [x] Fallback handling for LLM/Neo4j failures

## Configuration

Required environment variables (already in docker-compose.yml):
```bash
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_ENDPOINT=<your-endpoint>
AZURE_OPENAI_DEPLOYMENT=<deployment-name>
AZURE_OPENAI_API_VERSION=2024-08-01-preview
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<password>
PG_DSN=postgresql://aurora:aurora_password@postgres:5432/aurora
```

## Common Issues & Solutions

### Issue: Generic responses
**Cause**: LLM ignoring documents or no documents retrieved
**Solution**: 
1. Check `document_count` in response
2. Verify filters in logs
3. Check Neo4j has relevant data
4. Review LLM summarizer prompt

### Issue: No documents found
**Cause**: Filters too restrictive or entity mismatch
**Solution**:
1. Check merged filters in response
2. Verify entity names in Neo4j match query terms
3. Check if aliases are set up
4. Try broader query

### Issue: Wrong entities extracted
**Cause**: LLM misunderstanding domain context
**Solution**:
1. Review query and check LLM filters in response
2. Add examples to LLM prompt if needed
3. Check for typos or ambiguous phrasing

### Issue: Preferences not applied
**Cause**: User has no preferences or merge failing
**Solution**:
1. Check `from_preferences` in response (null if none)
2. Set preferences via `/users/{user_id}/preferences` endpoint
3. Check PostgreSQL connection

## Next Steps

1. **Monitor in Production**: Watch for generic responses
2. **Collect Feedback**: Track user satisfaction with answers
3. **Tune Weights**: Adjust relevance scoring based on usage
4. **Add Metrics**: Instrument pipeline stages for observability
5. **Expand Domains**: Add more domain-specific prompts as needed

## Performance Expectations

- **Response Time**: 2-5 seconds (includes 2 LLM calls + Neo4j query)
- **Document Retrieval**: 10-50 documents depending on filters
- **Token Usage**: ~500-1000 tokens per query (filter extraction + summarization)
- **Cache Opportunities**: Filter extraction, entity resolution

## Summary

The question-answering pipeline now reliably:
1. ✅ Loads user preferences from PostgreSQL
2. ✅ Extracts structured filters using domain-aware LLM
3. ✅ Merges filters intelligently as relevance signals
4. ✅ Queries Neo4j with sophisticated ranking
5. ✅ Generates answers from retrieved documents
6. ✅ Returns traceable, structured responses
7. ✅ Operates deterministically and resiliently

The system now provides **knowledge graph-driven, context-aware responses** instead of generic LLM hallucinations.
