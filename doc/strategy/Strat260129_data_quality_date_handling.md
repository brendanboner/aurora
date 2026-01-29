# Data Quality Strategy: Date Handling & Consistency

**Status:** Active  
**Date:** 2026-01-29  
**Owner:** Platform Team  
**Related:** Fast Pipeline (FAST_PIPELINE.md), Oracle Service

## Executive Summary

This document outlines the strategy for improving date handling across the Aurora platform, addressing current data quality issues, and establishing consistent date semantics for all content types (documents, events, meetings). The strategy includes immediate query adaptations, short-term scraper improvements, and long-term schema enhancements.

---

## Architecture Context

### Current System Architecture

The Aurora platform uses the following request flow:

```
User/CLI → Nginx → Auth Service (port 8000) → Oracle Service (port 8003) → Neo4j + LLM
                                             ↘ Backend Service (port 8001) → PostgreSQL (legacy endpoints only)
```

**Key Services:**
- **Oracle Service:** Primary query/answer engine (fast pipeline with Cypher templates)
- **Backend Service:** Legacy system - only used for user management, events, admin endpoints
- **Auth Service:** API gateway handling authentication and routing

**What Uses What:**
- ✅ **CLI (`aurora` command):** Connects to Oracle service (port 8003)
- ✅ **Frontend Chat:** Calls `/api/oracle/query` → routed to Oracle service
- ✅ **Content Creator:** Uses Oracle service for content discovery
- ⚠️ **Backend Service:** Still runs but only for admin/events/user management

**Important:** The backend's `llm_service.py` is **LEGACY CODE** and not used in the query pipeline. All LLM filter extraction happens in the Oracle service. Fixes must be applied to Oracle service only.

---

## 1. Current State Assessment

### 1.1 Date Storage Format

**Current Implementation:**
- Dates stored as **ISO string format** in Neo4j (e.g., `"2026-01-29"`, `"2026-01-29T10:30:00Z"`)
- String storage allows flexibility but lacks type validation
- Native Neo4j `datetime` type not consistently used

**Observed Data Quality Issues:**
1. **NULL/Missing Dates:** Many documents have `publish_date = NULL` (common for evergreen content)
2. **Malformed Years:** Invalid years like `"2399"`, `"0001"`, `"9999"` from bad parsing
3. **Empty Strings:** `publish_date = ""` instead of NULL
4. **Unknown Markers:** Literal string `"unknown"` used as date value
5. **Mixed Formats:** Some dates have time components, others don't
6. **Timezone Inconsistency:** Mix of UTC, naive datetimes, and local times

### 1.2 Date Field Semantics

**Resource (Document) Node:**
- `publish_date` - When content was originally published/created (source metadata)
- `content_changed_at` - When content was last modified (detected via content_hash)
- `scraped_at` - When we ingested the document (system timestamp)
- `created_at` - When document node was first created in Neo4j

**Event Node:**
- `startTime` / `start_date` - When the event takes place (future or past)
- `endTime` / `end_date` - When multi-day event ends (optional)
- `last_updated` - When event metadata was last scraped

**Current Problems:**
- Field semantics not always respected by scrapers
- Events sometimes use `publish_date` instead of `start_date`
- Conference announcements vs. conference dates confused
- Recurring events create ambiguity

### 1.3 Impact on Query System

**Failed Queries:**
- Temporal queries like "What happened last week?" return zero results
- Non-temporal queries like "What is Wi-Fi 7?" penalized by recency scoring
- Date range filters exclude all documents when dates malformed

**Root Causes Identified:**
1. **Hardcoded Dates in LLM Prompts:** `2025-11-24` instead of `datetime.now()` → wrong date ranges
2. **No Date Validation:** Cypher queries don't validate year ranges → malformed dates break filters
3. **Aggressive Recency Penalties:** NULL dates treated as 365 days old → undated content hidden
4. **No Fallback Logic:** Zero results with date filters → doesn't retry without dates

---

## 2. Immediate Fixes (Query System Adaptations)

### 2.1 Dynamic Date Generation in LLM Prompts

**CRITICAL FIX - DEFERRED:**
- ⚠️ Oracle service LLM filter extraction needs investigation
- The backend's `llm_service.py` had hardcoded dates BUT it's legacy code not used in query pipeline
- **Action Required:** Verify if Oracle service has similar hardcoded dates in LLM prompts
- Oracle service uses different LLM client and prompt structure

**Discovery:** During implementation, we found the backend `llm_service.py` is not used:
- CLI connects directly to Oracle (port 8003)
- Frontend routes through Auth → Oracle
- Backend only handles admin/events/users (not queries)
- Must audit Oracle service's LLM prompts separately

**Policy:** NEVER use hardcoded dates in any prompt, config, or logic that references "today" or "now"

### 2.2 Date Validation in Cypher Templates

**IMPLEMENTATION - COMPLETED:**

Added validation pattern to all temporal WHERE clauses:

```cypher
CASE 
    WHEN r.publish_date IS NOT NULL 
         AND r.publish_date <> '' 
         AND r.publish_date <> 'unknown' 
         AND toInteger(substring(toString(r.publish_date), 0, 4)) BETWEEN 2000 AND 2030 
    THEN datetime(r.publish_date)
    WHEN r.created_at IS NOT NULL THEN datetime(r.created_at)
    WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at)
    ELSE datetime()
END as effective_date
```

**Applied to Templates:**
- ✅ `RECENT_CONTENT`
- ✅ `DOCUMENTS_BY_TOPIC`
- ✅ `RECENT_PUBLICATIONS`
- ✅ `GENERIC_SEARCH`

**Benefits:**
- Excludes malformed dates like "2399" or empty strings
- Gracefully falls back to ingestion timestamps
- Doesn't break queries when date quality is poor

### 2.3 Reduced Recency Penalty for NULL Dates

**IMPLEMENTATION - COMPLETED:**

Changed `GENERIC_SEARCH` template scoring:

```cypher
CASE 
    WHEN r.publish_date IS NOT NULL 
         AND r.publish_date <> '' 
         AND r.publish_date <> 'unknown' 
         AND toInteger(substring(toString(r.publish_date), 0, 4)) BETWEEN 2000 AND 2030 
    THEN duration.between(datetime(r.publish_date), datetime()).days 
    ELSE 0  // Changed from 365
END as days_old
```

**Benefits:**
- Definitional queries ("What is Wi-Fi 7?") no longer penalize undated content
- NULL dates treated as "timeless" rather than "old"
- Still applies recency scoring when dates are valid

### 2.4 Query Fallback Logic

**IMPLEMENTATION - COMPLETED:**

Added automatic retry in `oracle/src/engines/fast_engine.py`:

```python
# If no results and query had date filters, retry without dates
if len(processed_results) == 0 and (params.get('start_date') or params.get('end_date')):
    logger.info("Zero results with date filters, retrying without temporal constraints")
    
    fallback_params = params.copy()
    fallback_params['start_date'] = None
    fallback_params['end_date'] = None
    
    fallback_results = repo.client.execute_query(template.cypher, fallback_params)
    processed_results = template.execute_post_process(fallback_results)
```

**Benefits:**
- Graceful degradation when date coverage sparse
- Users still get results even if temporal intent fails
- Logged for monitoring and future improvements

---

## 3. Rollup System Resilience

### 3.1 Startup Generation with Fallback

**IMPLEMENTATION - COMPLETED:**

Enhanced `oracle/src/services/rollup_scheduler.py`:

```python
# Run immediately on startup if enabled
try:
    await self._run_generation()
except Exception as e:
    logger.error(f"Initial rollup generation failed: {e}, will use cached rollups if available")
    logger.warning("Service will continue with stale PostgreSQL cache or direct Neo4j queries")
```

**Degradation Order:**
1. **Fresh Rollups:** Generate from Neo4j on startup (preferred)
2. **Cached Rollups:** Use existing PostgreSQL rollups if generation fails
3. **Direct Queries:** Fall back to direct Neo4j Cypher queries if no cache

**Benefits:**
- Rollup failures never block service startup
- Stale cache better than no service
- Empty datasets (no updates) don't cause failures

### 3.2 Scheduled Regeneration

**IMPLEMENTATION - COMPLETED:**

Background scheduler regenerates rollups every 6 hours:

```python
# Periodic regeneration with graceful failure handling
try:
    await self._run_generation()
    self._last_run_date = current_day
except Exception as e:
    logger.error(f"Scheduled rollup generation failed: {e}, previous rollups remain available")
```

**Benefits:**
- "This week" queries stay current as week progresses
- Failure doesn't delete existing rollups
- Automatic recovery on next scheduled run

### 3.3 OpenTelemetry Metrics

**PLANNED - NOT YET IMPLEMENTED:**

Recommended metrics for rollup health monitoring:

```python
# Metrics to add in rollup_generator.py
meter.create_counter("rollup.generation.success", description="Successful rollup generations")
meter.create_counter("rollup.generation.failure", description="Failed rollup generations")
meter.create_histogram("rollup.cache.age_hours", description="Age of cached rollups in hours")
meter.create_counter("rollup.empty_dataset.count", description="Rollups with zero events/docs")
meter.create_histogram("rollup.generation.duration_seconds", description="Time to generate rollups")
```

**Alerting Thresholds:**
- **Critical:** `rollup.generation.failure > 3 consecutive failures`
- **Warning:** `rollup.cache.age_hours > 24`
- **Info:** `rollup.empty_dataset.count > 10` (may indicate scraping issues)

---

## 4. Scraper Improvements (Short-Term)

**STATUS:** Documented for future implementation - NOT modifying scrapers now

### 4.1 Date Validation at Ingestion

**Recommendation:**

All scrapers should validate dates before storing to Neo4j:

```python
def validate_date(date_str: str) -> Optional[str]:
    """Validate and normalize date string to ISO format."""
    if not date_str or date_str.lower() in ['unknown', 'null', 'none', '']:
        return None
    
    try:
        parsed = dateutil.parser.parse(date_str)
        
        # Reject invalid years
        if not (2000 <= parsed.year <= 2030):
            logger.warning(f"Invalid year {parsed.year}, rejecting date")
            return None
        
        # Return ISO format (UTC preferred)
        return parsed.isoformat()
    
    except Exception as e:
        logger.warning(f"Date parsing failed: {e}, rejecting date")
        return None
```

**Validation Rules:**
1. Year must be between 2000-2030 (adjust upper bound annually)
2. Reject strings like "unknown", empty strings, "null"
3. Convert all dates to ISO 8601 format
4. Prefer UTC timezone when possible
5. Return NULL instead of storing bad dates

### 4.2 Field Semantic Enforcement

**Recommendation:**

Scrapers must distinguish date types:

| Content Type | Primary Date Field | Semantics | Example |
|--------------|-------------------|-----------|---------|
| Document | `publish_date` | When content was published/created | Press release date |
| Document | `content_changed_at` | When content was last modified | Last updated timestamp |
| Event | `start_date` | When event takes place | Meeting date |
| Event | `end_date` | When multi-day event ends | Conference end date |
| Any | `scraped_at` | When we ingested the item | System timestamp (always set) |

**Examples:**

```python
# Conference announcement (document about event)
document = {
    "title": "Wi-Fi Alliance Announces Summit 2026",
    "publish_date": "2026-01-15",  # When announcement was published
    "scraped_at": "2026-01-16T10:00:00Z"
}

# The actual conference (event)
event = {
    "title": "Wi-Fi Alliance Summit 2026",
    "start_date": "2026-03-20",  # When conference starts
    "end_date": "2026-03-22",    # When conference ends
    "scraped_at": "2026-01-16T10:00:00Z"
}
```

### 4.3 Scraper Audit Checklist

**For Each Datasource Scraper:**

- [ ] Validates dates before storing (rejects years outside 2000-2030)
- [ ] Converts all dates to ISO 8601 string format
- [ ] Sets `publish_date` for when content was published (NULL if unknown)
- [ ] Sets `start_date` for events (when event takes place)
- [ ] Always sets `scraped_at` to current UTC timestamp
- [ ] Handles timezones consistently (prefers UTC)
- [ ] Logs warnings for rejected/malformed dates
- [ ] Tests edge cases (no date, malformed date, future date, past date)

---

## 5. Long-Term Schema Enhancements (Deferred)

**STATUS:** Planned for future implementation - NOT now

### 5.1 Native Datetime Type Migration

**Proposal:**

Migrate from string dates to native Neo4j `datetime` properties:

```cypher
// Current (string)
CREATE (r:Resource {
    publish_date: "2026-01-29T10:30:00Z"  // String
})

// Future (native)
CREATE (r:Resource {
    publish_date: datetime("2026-01-29T10:30:00Z")  // Native datetime
})
```

**Benefits:**
- Type safety at database level
- No need for string validation in queries
- Native date arithmetic support
- Faster date comparisons (indexed properly)

**Migration Steps:**
1. Add new `publish_datetime` property (parallel to `publish_date`)
2. Migrate existing data with validation
3. Update all scrapers to write both formats (transition period)
4. Update all queries to use `publish_datetime`
5. Deprecate and remove `publish_date` string field

**Estimated Effort:** 2-3 weeks (includes testing)

### 5.2 Date Type Metadata

**Proposal:**

Add `content_date_type` enum to clarify date semantics:

```cypher
CREATE (r:Resource {
    publish_date: datetime("2026-01-29"),
    content_date_type: "publication",  // ENUM: publication | event | updated | unknown
    content_date_confidence: 0.95      // Scraper confidence in date accuracy
})
```

**Use Cases:**
- Query can choose whether to filter by `publish_date` or `start_date` intelligently
- "What happened last week?" uses `content_date_type = 'event'` → filter by `start_date`
- "What was published last week?" uses `content_date_type = 'publication'` → filter by `publish_date`

**Enum Values:**
- `publication` - Document was published on this date
- `event` - Event takes/took place on this date
- `updated` - Content was last modified on this date
- `announced` - Event was announced on this date (but happens later)
- `unknown` - Date semantics unclear

### 5.3 Computed Date Quality Score

**Proposal:**

Add computed property for faster query optimization:

```cypher
// During ingestion or periodic maintenance
MATCH (r:Resource)
WITH r,
     CASE 
         WHEN r.publish_date IS NULL THEN 0.0
         WHEN toInteger(substring(r.publish_date, 0, 4)) NOT BETWEEN 2000 AND 2030 THEN 0.0
         WHEN r.publish_date =~ '\\d{4}-\\d{2}-\\d{2}.*' THEN 1.0
         ELSE 0.5
     END as quality_score
SET r.date_quality = quality_score
```

**Benefits:**
- Pre-validated dates → faster query execution
- Can prioritize high-quality dates in results
- Monitor data quality trends over time

---

## 6. Data Quality Monitoring

### 6.1 Date Quality Metrics

**Query to Generate Weekly Report:**

```cypher
MATCH (r:Resource)
WITH 
    count(r) as total_resources,
    sum(CASE WHEN r.publish_date IS NULL THEN 1 ELSE 0 END) as null_dates,
    sum(CASE WHEN r.publish_date = '' OR r.publish_date = 'unknown' THEN 1 ELSE 0 END) as invalid_dates,
    sum(CASE 
        WHEN r.publish_date IS NOT NULL 
             AND toInteger(substring(toString(r.publish_date), 0, 4)) NOT BETWEEN 2000 AND 2030 
        THEN 1 ELSE 0 
    END) as malformed_dates,
    sum(CASE 
        WHEN r.publish_date IS NOT NULL 
             AND r.publish_date <> '' 
             AND r.publish_date <> 'unknown'
             AND toInteger(substring(toString(r.publish_date), 0, 4)) BETWEEN 2000 AND 2030 
        THEN 1 ELSE 0 
    END) as valid_dates

RETURN 
    total_resources,
    null_dates,
    invalid_dates,
    malformed_dates,
    valid_dates,
    round(100.0 * valid_dates / total_resources, 2) as valid_date_percentage
```

**Target KPIs:**
- `valid_date_percentage > 70%` for new documents
- `malformed_dates < 1%` of total resources
- Track trend: should improve over time as scrapers fixed

### 6.2 Scraper-Specific Quality

**Query to Identify Problem Datasources:**

```cypher
MATCH (r:Resource)-[:INGESTED_FROM]->(ds:DataSource)
WITH ds.datasource_id as datasource,
     count(r) as total_docs,
     sum(CASE WHEN r.publish_date IS NULL THEN 1 ELSE 0 END) as null_dates,
     sum(CASE 
         WHEN r.publish_date IS NOT NULL 
              AND toInteger(substring(toString(r.publish_date), 0, 4)) NOT BETWEEN 2000 AND 2030 
         THEN 1 ELSE 0 
     END) as malformed_dates

RETURN 
    datasource,
    total_docs,
    null_dates,
    malformed_dates,
    round(100.0 * null_dates / total_docs, 2) as null_percentage,
    round(100.0 * malformed_dates / total_docs, 2) as malformed_percentage

ORDER BY malformed_percentage DESC
LIMIT 10
```

**Action Items:**
- Prioritize fixing datasources with `malformed_percentage > 5%`
- Investigate datasources with `null_percentage > 80%` (may be evergreen content)

---

## 7. Testing & Validation

### 7.1 Query Test Cases

**Test Suite Location:** `test_cli.sh`

**Representative Test Queries:**

| Query Type | Example | Expected Behavior |
|------------|---------|-------------------|
| Definitional | "What is Wi-Fi 7?" | Return results regardless of dates |
| Search | "What documents mention 5G?" | Minimal recency penalty for NULL dates |
| Temporal (explicit) | "What happened last week?" | Use correct date range (Jan 22-29, 2026) |
| Temporal (implicit) | "What are the latest Wi-Fi Alliance updates?" | Fall back to undated content if needed |
| Temporal (workgroup) | "What was discussed last week in 802.11?" | Use rollups if available, else direct query |

**Validation Criteria:**
- ✅ No queries return "no documents found" unless truly no matching content
- ✅ Date ranges resolve to current date (not hardcoded)
- ✅ NULL dates don't exclude relevant documents from non-temporal queries
- ✅ Malformed dates (2399, empty, unknown) gracefully handled

### 7.2 Rollup Health Checks

**Manual Validation:**

```bash
# Check rollup generation status
curl http://localhost:8002/admin/rollups/status

# Expected response
{
  "last_generation": "2026-01-29T10:00:00Z",
  "rollups_count": 45,
  "workgroups_covered": 15,
  "oldest_rollup_age_hours": 6,
  "status": "healthy"
}
```

**Automated Tests:**

```python
# Test rollup fallback chain
async def test_rollup_degradation():
    # 1. Fresh generation succeeds
    result = await rollup_generator.generate_all_rollups()
    assert result['workgroups_processed'] > 0
    
    # 2. If Neo4j fails, use cached rollups
    with mock_neo4j_failure():
        cached = rollup_generator.query_rollups(rollup_type="week")
        assert len(cached) > 0  # Should return stale cache
    
    # 3. Service continues even with failures
    response = await test_client.post("/query", json={"question": "What happened this week?"})
### Phase 1: Immediate (Week 1) - PARTIALLY COMPLETED ⚠️

- [ ] **Investigate Oracle LLM prompts** - Backend service not used for queries (legacy)
- [x] Add date validation to Cypher templates
- [x] Reduce recency penalty for NULL dates
- [x] Implement query fallback logic
- [x] Enhance rollup scheduler resilience
- [ ] Test with `test_cli.sh` (pending Oracle LLM fix)1) - COMPLETED ✅

- [x] Fix hardcoded dates in LLM prompts
- [x] Add date validation to Cypher templates
- [x] Reduce recency penalty for NULL dates
- [x] Implement query fallback logic
- [x] Enhance rollup scheduler resilience
- [x] Test with `test_cli.sh`

### Phase 2: Short-Term (Weeks 2-4) - PLANNED

- [ ] Add OpenTelemetry metrics for rollup health
- [ ] Create date quality monitoring dashboard
- [ ] Audit and fix top 3 datasource scrapers with worst date quality
- [ ] Implement automated date quality reports (weekly email)
- [ ] Update scraper documentation with date validation guidelines

### Phase 3: Medium-Term (Months 2-3) - PLANNED

- [ ] Fix all remaining datasource scrapers
- [ ] Achieve `valid_date_percentage > 70%` across all datasources
- [ ] Implement `content_date_type` enum in schema
- [ ] Update queries to use date type metadata intelligently
- [ ] Create scraper certification checklist (must pass before deployment)

### Phase 4: Long-Term (Months 4-6) - PROPOSED

- [ ] Migrate to native Neo4j `datetime` type
- [ ] Add computed `date_quality` property
- [ ] Implement date confidence scoring
- [ ] Optimize query performance with pre-validated dates
- [ ] Deprecate string date fields

---

## 9. Success Metrics

### 9.1 Query Success Rate

**Baseline (Before Fixes):**
- Temporal queries failing: ~60% return "no documents found"
- Non-temporal queries affected: ~20% penalized by NULL dates

**Target (After Phase 1):**
- Temporal queries succeeding: >90%
- Non-temporal queries unaffected: >95%
- Average query latency: <500ms (unchanged)

### 9.2 Data Quality Improvement

**Current State:**
- `valid_date_percentage`: ~45% (estimated)
- Malformed dates: ~3% (estimated)
- NULL dates: ~52% (estimated)

**Target (After Phase 3):**
- `valid_date_percentage`: >70%
- Malformed dates: <1%
- NULL dates: ~29% (acceptable for evergreen content)

### 9.3 System Resilience

**Rollup Availability:**
- Target: >99% uptime (service continues with stale cache or direct queries)
- Rollup freshness: <6 hours age under normal operation
- Alert response time: <15 minutes for critical failures

---

## 10. Related Documents
## 11. Appendix: Hardcoded Date Audit

**Architecture Discovery:**

During implementation, we discovered that the backend service's `llm_service.py` is **NOT used in the query pipeline**:

```
❌ INCORRECT ASSUMPTION:
   Frontend → Backend → LLM Service (has hardcoded dates)

✅ ACTUAL ARCHITECTURE:
   Frontend/CLI → Oracle Service → Oracle's LLM client (needs investigation)
   Backend Service → Only for admin/events/users (legacy)
```

**Files Audited for Hardcoded Dates:**

| File | Line | Pattern | Status |
|------|------|---------|--------|
| `backend/src/services/llm_service.py` | 213 | `2025-11-24` | ⚠️ Legacy code - not used for queries |
| `backend/src/services/llm_service.py` | 221 | `2025-11-24` | ⚠️ Legacy code - not used for queries |
| `backend/src/services/llm_frontend.py` | 81-82 | `2025-11-10` | ⚠️ Example/test data only |
| `oracle/src/services/*.py` | ? | ? | 🔍 **NEEDS INVESTIGATION** |

**Action Required:**

1. **Audit Oracle Service LLM Prompts:**
   - Search `oracle/src/services/` for LLM filter extraction logic
   - Check if Oracle has its own LLM client with prompts
   - Look for hardcoded dates in Oracle's temporal query handling

2. **Verify Query Flow:**
   - Trace how CLI `aurora` command sends queries
   - Confirm Oracle service handles all LLM extraction
   - Verify backend service is truly not in query path

**Systems Not Modified:**
- `backend/` - Legacy code reverted (not in query pipeline)
- Test files may contain specific dates for reproducibility (acceptable)

**Policy:** No hardcoded dates allowed in production code that represents "today" or "now". Test fixtures may use specific dates for reproducibility.
| `backend/src/services/llm_frontend.py` | 81-82 | `2025-11-10` | ⚠️ Example/test data only |

**Other Systems (Not Modified):**
- `backend/src/services/llm_frontend.py` - Contains example dates in docstring (harmless)
- Test files may contain specific dates for reproducibility (acceptable)

**Policy:** No hardcoded dates allowed in production code that represents "today" or "now". Test fixtures may use specific dates for reproducibility.

---

## Questions & Feedback

For questions or suggestions regarding this strategy:
- Open an issue in the repository
- Contact the platform team
- Propose improvements via pull request

**Document Version:** 1.0  
**Last Updated:** 2026-01-29  
**Next Review:** 2026-02-29
