# Quick Troubleshooting Guide

## Testing the Pipeline

### 1. Quick Test via API
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": 1,
    "question": "What are the latest Wi-Fi Alliance updates?"
  }' | jq
```

### 2. Check Response Structure
Look for these indicators of correct operation:

✅ **Good Response**:
```json
{
  "answer": "Based on documents from the Wi-Fi Alliance...",
  "document_count": 15,
  "filters": {
    "from_query": {"topics": ["Wi-Fi"], "organisations": ["Wi-Fi Alliance"]},
    "from_preferences": {"topics": [...], "organisations": [...]},
    "applied": {...}
  },
  "documents": [...]
}
```

❌ **Problem Response**:
```json
{
  "answer": "I don't have specific information about...",
  "document_count": 0,
  "filters": {"applied": {"topics": [], "organisations": []}},
  "documents": []
}
```

## Common Issues

### Issue 1: Generic Responses Despite Documents

**Symptoms**:
- `document_count > 0` but answer is generic
- Answer doesn't reference specific documents
- Answer says "I don't have information"

**Diagnosis**:
```bash
# Check if documents have content
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"user_id": 1, "question": "test"}' | jq '.documents[0]'

# Should show: title, summary, topics, organisations
```

**Solutions**:
1. Verify LLM summarizer is receiving documents:
   ```bash
   docker logs -f aurora-backend | grep "summarise_documents"
   ```

2. Check if documents have summaries:
   ```bash
   # In Neo4j browser: http://localhost:7474
   MATCH (r:Resource) RETURN r.summary LIMIT 5
   ```

3. Restart backend to reload LLM client:
   ```bash
   docker-compose restart backend
   ```

### Issue 2: No Documents Retrieved

**Symptoms**:
- `document_count: 0`
- Empty `documents` array
- Filters look correct

**Diagnosis**:
```bash
# Check filters being applied
docker logs aurora-backend | grep "Merged filters"

# Check Neo4j has data
docker exec -it aurora-neo4j cypher-shell -u neo4j -p neo4j
> MATCH (r:Resource) RETURN count(r);
> MATCH (t:Topic) RETURN count(t);
```

**Solutions**:
1. Verify Neo4j connection:
   ```bash
   docker logs aurora-backend | grep "Neo4j"
   # Should see: "Connected to Neo4j via bolt://..."
   ```

2. Check entity names match:
   ```bash
   # List topics in Neo4j
   docker exec -it aurora-neo4j cypher-shell -u neo4j -p neo4j \
     -c "MATCH (t:Topic) RETURN t.name LIMIT 20"
   
   # Compare with filters in API response
   ```

3. Try broader query:
   ```bash
   curl -X POST http://localhost:8000/query \
     -H "Content-Type: application/json" \
     -d '{"user_id": 1, "question": "What happened recently?"}' | jq
   ```

### Issue 3: Wrong Entities Extracted

**Symptoms**:
- `from_query` filters don't match question
- Expected organization not in filters
- Wrong topics extracted

**Diagnosis**:
```bash
# Check LLM filter extraction
docker logs aurora-backend | grep "LLM extracted filters"

# Test with explicit entity names
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"user_id": 1, "question": "Tell me about IEEE"}' | jq '.filters.from_query'
```

**Solutions**:
1. Verify Azure OpenAI connection:
   ```bash
   docker logs aurora-backend | grep "Azure OpenAI"
   # Should NOT see "LLM unavailable"
   ```

2. Check environment variables:
   ```bash
   docker exec aurora-backend env | grep AZURE_OPENAI
   ```

3. Test LLM directly in Python:
   ```python
   from src.services.llm_service import parse_query_to_filters
   result = parse_query_to_filters("What's new with Wi-Fi Alliance?")
   print(result)
   ```

### Issue 4: User Preferences Not Applied

**Symptoms**:
- `from_preferences: null` in response
- Filters only show `from_query` items
- User has set preferences but they're not used

**Diagnosis**:
```bash
# Check if user exists
curl http://localhost:8000/users/1 | jq

# Check user preferences
curl http://localhost:8000/users/1/preferences | jq
```

**Solutions**:
1. Set user preferences:
   ```bash
   curl -X PUT http://localhost:8000/users/1/preferences \
     -H "Content-Type: application/json" \
     -d '{
       "topics": ["Wi-Fi 6", "802.11ax"],
       "organisations": ["Wi-Fi Alliance", "IEEE"],
       "people": []
     }'
   ```

2. Verify PostgreSQL connection:
   ```bash
   docker logs aurora-backend | grep "postgres"
   docker exec -it aurora-postgres psql -U aurora -d aurora \
     -c "SELECT * FROM user_preferences WHERE user_id = 1;"
   ```

3. Create user if missing:
   ```bash
   curl -X POST http://localhost:8000/users \
     -H "Content-Type: application/json" \
     -d '{
       "email": "test@example.com",
       "display_name": "Test User"
     }'
   ```

### Issue 5: Slow Responses

**Symptoms**:
- Queries take >10 seconds
- Timeouts in UI
- Backend logs show delays

**Diagnosis**:
```bash
# Check for slow operations
docker logs aurora-backend | grep -E "(Processing query|Retrieved|seconds)"

# Monitor Neo4j query performance
docker logs aurora-neo4j | grep -i "slow"
```

**Solutions**:
1. Check Neo4j indexes exist:
   ```cypher
   // In Neo4j browser
   CALL db.indexes() YIELD name, state, type
   ```

2. Reduce result limit:
   ```bash
   # Query with smaller limit
   curl -X POST http://localhost:8000/query \
     -H "Content-Type: application/json" \
     -d '{"user_id": 1, "question": "What happened? limit 10"}' | jq
   ```

3. Check Azure OpenAI latency:
   ```bash
   docker logs aurora-backend | grep -E "(LLM|OpenAI|temperature)"
   ```

## Verification Checklist

Run through this checklist to ensure everything works:

- [ ] Backend container is running: `docker ps | grep aurora-backend`
- [ ] Neo4j is accessible: `curl http://localhost:7474`
- [ ] PostgreSQL has users: `curl http://localhost:8000/users | jq`
- [ ] Neo4j has data: Check browser at http://localhost:7474
- [ ] Azure OpenAI configured: Check env vars in docker-compose.yml
- [ ] User preferences exist: `curl http://localhost:8000/users/1/preferences | jq`
- [ ] Query returns documents: `curl -X POST ... | jq '.document_count'`
- [ ] Answer references documents: Look for specific citations in answer
- [ ] Filters are merged: Check `from_query`, `from_preferences`, and `applied`
- [ ] Logs show pipeline steps: `docker logs aurora-backend | grep "INFO:query_engine"`

## Debug Mode

To enable verbose logging:

1. Edit `docker-compose.yml`:
   ```yaml
   environment:
     - LOG_LEVEL=DEBUG
   ```

2. Restart backend:
   ```bash
   docker-compose restart backend
   ```

3. Watch logs:
   ```bash
   docker logs -f aurora-backend
   ```

## Performance Baseline

Expected timings for a typical query:
- User preference load: <50ms
- LLM filter extraction: 500-1500ms
- Neo4j query: 100-500ms
- LLM summarization: 1000-2000ms
- **Total: 2-4 seconds**

If consistently slower, investigate:
1. Network latency to Azure OpenAI
2. Neo4j query performance (missing indexes)
3. Large result sets (reduce limit)

## Emergency Fallback

If LLM is unavailable and you get heuristic responses:

```bash
# Verify Azure OpenAI credentials
docker exec aurora-backend env | grep AZURE_OPENAI

# Test credentials
docker exec -it aurora-backend python -c "
from src.services.llm_service import get_azure_client
client = get_azure_client()
print(f'Client available: {client is not None}')
"
```

If credentials are wrong:
1. Update `.env` or `docker-compose.yml`
2. Restart: `docker-compose restart backend`
3. Retest query

## Support

For issues not covered here:
1. Check `backend/QUERY_PIPELINE_IMPLEMENTATION.md` for detailed docs
2. Review `PIPELINE_FLOW.md` for architecture
3. Run test script: `python backend/test_query_pipeline.py`
4. Check logs: `docker logs aurora-backend`
