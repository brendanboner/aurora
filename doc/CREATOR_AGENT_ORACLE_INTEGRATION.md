# Creator Agent Integration with Oracle Service

## Implementation Status

### ✅ Completed

**Oracle Service (Complete)**
- ✅ `oracle/src/services/agent_adapter.py` - Agent routing and preferences mapping
- ✅ `oracle/src/routes/agent.py` - HTTP endpoint (`/agent/discover`, `/agent/health`)
- ✅ `oracle/src/services/query_template_registry.py` - AGENT_CONTENT_DISCOVERY template with deduplication
- ✅ `oracle/src/models/route_plan.py` - RouteId enum extension
- ✅ `oracle/src/api.py` - Router registration

**Creator Service (Complete)**
- ✅ `content_creator_service/src/services/oracle_client.py` - HTTP client for Oracle API
- ✅ `content_creator_service/src/services/generation_service.py` - Oracle integration with fallback
- ✅ `content_creator_service/src/services/scheduler.py` - Perspective variation by weekday
- ✅ `content_creator_service/src/settings.py` - Oracle URL and feature flag
- ✅ Content ID tracking via `post_source.source_identifier`
- ✅ Deduplication using `_fetch_used_content_ids()` from published posts

**Features**
- ✅ Cadence-based routing (1/7/30 days → rollups)
- ✅ Perspective variation (weekday-based for weekly agents)
- ✅ Content deduplication (tracks used IDs from PostgreSQL)
- ✅ Relevance scoring (specificity + recency + importance)
- ✅ Graceful fallback to direct Neo4j
- ✅ Feature flag (`use_oracle_for_discovery=True`)

### 🚧 Testing & Deployment

- ⏳ Rebuild Oracle container with new endpoints
- ⏳ Rebuild creator service with Oracle client
- ⏳ Test `/agent/discover` endpoint
- ⏳ Verify deduplication with repeated runs
- ⏳ Performance comparison (Oracle vs Neo4j)
- ⏳ Production rollout

---

## Overview

This integration enables creator agents to leverage Oracle's fast engine infrastructure for content discovery, including:

- **Pre-computed rollups** (daily/weekly/monthly summaries)
- **Query templates** with Cypher optimization
- **Personalization infrastructure** (topics/organizations/people)
- **Date intelligence** ("this month" vs "in the last month")
- **Content deduplication** to avoid repeating material
- **Relevance scoring** with agent-specific weighting

## Architecture

```
Creator Agent → Oracle Agent Endpoint → Fast Engine → Rollups/Templates → Content
     ↓                ↓                      ↓               ↓
  Persona      AgentRouter             LocalRouter      Cypher Query
  Topics       RoutePlan               UserPrefs        Neo4j Results
  Cadence      Exclusions              Date Logic       
```

## API Endpoint

### POST `/agent/discover`

Discover content optimized for creator agent generation.

**Request Body:**
```json
{
  "agent_id": "wifi7-analyst",
  "agent_name": "Wi-Fi 7 Technical Analyst",
  "expertise_topics": ["Wi-Fi 7", "MLO", "6 GHz"],
  "expertise_organisations": ["Wi-Fi Alliance", "IEEE"],
  "cadence_days": 7,
  "discovery_tolerance": 0.5,
  "last_content_ids": ["doc123", "doc456"],
  "perspective": "trends",
  "limit": 20
}
```

**Response:**
```json
{
  "agent_id": "wifi7-analyst",
  "route_used": "workgroup_weekly_recap",
  "confidence": 0.95,
  "date_range": {
    "start": "2026-01-20",
    "end": "2026-01-27",
    "relative_days": 7
  },
  "content_items": [
    {
      "id": "abc123",
      "title": "Wi-Fi 7 MLO Implementation Updates",
      "summary": "Recent progress on multi-link operation...",
      "publish_date": "2026-01-25",
      "url": "https://...",
      "topics": ["Wi-Fi 7", "MLO"],
      "organizations": ["Wi-Fi Alliance"],
      "events": ["Q1 Plenary"],
      "relevance_score": 0.92
    }
  ],
  "rollup_used": true,
  "excluded_count": 2
}
```

## Agent Adapter

### CreatorAgentPreferences

Maps agent configuration to Oracle's routing format:

```python
from src.services.agent_adapter import CreatorAgentPreferences

agent_prefs = CreatorAgentPreferences(
    agent_id="security-expert",
    agent_name="Security Weekly Digest",
    expertise_topics=["WPA3", "Security", "Authentication"],
    expertise_organisations=["Wi-Fi Alliance"],
    cadence_days=7,  # Weekly
    discovery_tolerance=0.3,  # Strict focus
    last_content_ids=["doc789"]  # Exclude previously used
)
```

### AgentRouter

Routes agents to appropriate query templates:

```python
from src.services.agent_adapter import AgentRouter

router = AgentRouter()
route_id, plan, confidence = router.route_for_agent(
    agent_prefs,
    perspective="trends"  # Optional: "news", "events", "analysis"
)
```

**Routing Logic:**

| Cadence | Default Route | Rollup Used |
|---------|--------------|-------------|
| 1 day | `WORKGROUP_DAILY_RECAP` | Daily rollup |
| 7 days | `WORKGROUP_WEEKLY_RECAP` | Weekly rollup |
| 30 days | `WORKGROUP_MONTHLY_SUMMARY` | Monthly rollup |
| 30+ days | `WORKGROUP_RECENT_UPDATES` | Live query |

**Perspective Override:**

| Perspective | Route |
|------------|-------|
| "events" | `UPCOMING_EVENTS` |
| "decisions" | `RECENT_DECISIONS` |
| "trends" | `TOPICS_TREND` |
| "publications" | `RECENT_PUBLICATIONS` |

## Query Template

### AGENT_CONTENT_DISCOVERY

Specialized template with:

- **Deduplication**: Excludes `last_content_ids`
- **Relevance scoring**: Combines specificity, recency, importance
- **Context enrichment**: Topics, organizations, events, people
- **Flexible filtering**: By topics OR organizations

**Parameters:**
- `topics`: Agent's expertise topics
- `organizations`: Agent's tracked organizations
- `start_date`, `end_date`: Date range
- `exclude_ids`: Previously used content IDs
- `limit`: Maximum results

**Relevance Formula:**
```
relevance = (specificity_score * 0.6 + recency_score * 0.4) * importance_multiplier

specificity_score:
  - 0-3 topics: 1.0 (highly focused)
  - 4-6 topics: 0.8
  - 7+ topics: 0.6

recency_score:
  - exp(-days_old / 7.0)  # 7-day half-life

importance_multiplier:
  - critical: 1.5x
  - high: 1.2x
  - normal: 1.0x
```

## Content Deduplication

Prevents agents from reusing content across generations:

1. **Agent tracks** IDs of used content in their state
2. **Pass IDs** in `last_content_ids` array
3. **Template excludes** via `NOT r.url_hash IN $exclude_ids`
4. **Response includes** `excluded_count` for monitoring

Example:
```python
# First generation
response1 = discover_content(agent_id="agent1", last_content_ids=[])
used_ids = [item["id"] for item in response1["content_items"]]

# Second generation - excludes previous content
response2 = discover_content(agent_id="agent1", last_content_ids=used_ids)
```

## Perspective Variation

Guide agents to different angles on same content:

```python
# News-focused
discover_content(perspective="news")  # Recent publications

# Event-focused
discover_content(perspective="events")  # Upcoming meetings

# Analysis-focused
discover_content(perspective="trends")  # Topic trends

# Decision-focused
discover_content(perspective="decisions")  # Recent decisions
```

## Benefits vs Direct Neo4j

| Feature | Direct Neo4j | Oracle Integration |
|---------|-------------|-------------------|
| Query optimization | Manual | Pre-optimized templates |
| Caching | None | Rollups cached in PostgreSQL |
| Personalization | Custom logic | Built-in (all topics/orgs) |
| Date handling | Manual parsing | Intelligent ("this month" vs "last month") |
| Deduplication | Custom tracking | Built-in exclusion |
| Maintenance | Duplicate Cypher | Shared templates |
| Performance | Variable | Consistent (rollups) |

## Migration Path

### Phase 1: Parallel Testing (Week 1-2)
- Deploy Oracle agent endpoint
- Test with 1-2 pilot agents
- Compare results vs direct Neo4j
- Measure performance/quality

### Phase 2: Gradual Rollout (Week 3-4)
- Migrate daily agents (leverage daily rollups)
- Migrate weekly agents (leverage weekly rollups)
- Monitor content quality and diversity

### Phase 3: Full Migration (Week 5-6)
- Migrate all agents
- Deprecate direct Neo4j queries
- Remove duplicate Cypher logic

### Phase 4: Optimization (Week 7+)
- Fine-tune relevance scoring
- Expand rollup coverage
- Add agent-specific metrics

## Example Integration

### Creator Service Client

```python
import httpx
from typing import List, Dict, Any

class OracleAgentClient:
    """Client for Oracle agent endpoint."""
    
    def __init__(self, oracle_url: str = "http://oracle:8003"):
        self.oracle_url = oracle_url
        self.client = httpx.AsyncClient()
    
    async def discover_content(
        self,
        agent_id: str,
        agent_name: str,
        topics: List[str],
        organizations: List[str],
        cadence_days: int = 7,
        last_content_ids: List[str] = None,
        perspective: str = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Discover content for agent."""
        
        response = await self.client.post(
            f"{self.oracle_url}/agent/discover",
            json={
                "agent_id": agent_id,
                "agent_name": agent_name,
                "expertise_topics": topics,
                "expertise_organisations": organizations,
                "cadence_days": cadence_days,
                "last_content_ids": last_content_ids or [],
                "perspective": perspective,
                "limit": limit
            }
        )
        response.raise_for_status()
        return response.json()
```

### Usage in Creator Service

```python
from src.services.oracle_client import OracleAgentClient

oracle = OracleAgentClient()

# Discover content
result = await oracle.discover_content(
    agent_id=agent.id,
    agent_name=agent.name,
    topics=agent.expertise_topics,
    organizations=agent.expertise_organisations,
    cadence_days=agent.cadence_window_days,
    last_content_ids=agent.last_used_content_ids,
    perspective="trends"
)

# Generate post with agent's persona
content_items = result["content_items"]
post = await generate_post_with_persona(
    agent=agent,
    content=content_items,
    route_used=result["route_used"]
)

# Track used content for next time
agent.last_used_content_ids = [item["id"] for item in content_items]
await agent.save()
```

## Monitoring

### Key Metrics

1. **Route Distribution**: Which routes agents use most
2. **Rollup Hit Rate**: % of requests served by rollups
3. **Exclusion Efficiency**: Avg items excluded per request
4. **Content Quality**: Relevance scores distribution
5. **Performance**: Response time vs direct Neo4j

### Logging

```python
logger.info(
    f"Agent discovery: agent={agent_id}, "
    f"route={route_used}, "
    f"items={len(content_items)}, "
    f"rollup={rollup_used}, "
    f"excluded={excluded_count}"
)
```

## Future Enhancements

1. **Agent-Specific Rollups**: Generate rollups tailored to agent topics
2. **Predictive Scheduling**: Pre-generate content before agent cadence
3. **Content Clustering**: Group similar items for thematic posts
4. **Cross-Agent Diversity**: Ensure different agents cover different angles
5. **Feedback Loop**: Use post performance to tune relevance scoring
6. **Semantic Deduplication**: Exclude semantically similar content, not just exact IDs

## Support

For questions or issues with the agent integration:
- Check Oracle service logs: `docker logs aurora-oracle`
- Review rollup generation: Check PostgreSQL `rollups` table
- Test routing: Use `/agent/health` endpoint
- Debug queries: Enable Neo4j query logging
