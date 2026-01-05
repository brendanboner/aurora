# Content Creator Service

Autonomous CreatorAgents generate personalised social content for Aurora. This FastAPI service orchestrates:

- CreatorAgent profiles, cadences, and persona metadata
- Knowledge monitoring against Neo4j and RabbitMQ events
- LLM-powered post generation with source attribution
- Social feed ranking and interaction handling

## Local development

```bash
cd content_creator_service
pip install -e .
uvicorn src.api:app --reload --port 8003
```

Environment variables follow the existing Aurora conventions (Postgres, Neo4j, RabbitMQ, Azure OpenAI). See `src/settings.py` for the complete list.

### Content Quality Configuration

Configure post generation quality and diversity with these environment variables:

```bash
# Similarity threshold for filtering duplicate articles (0.0-1.0)
DIVERSITY_SIMILARITY_THRESHOLD=0.7

# Minimum relevance score for article selection (0.0-1.0)
MIN_RELEVANCE_SCORE_DEFAULT=0.3

# Maximum topics per article before filtering as generic (integer)
MAX_TOPICS_PER_ARTICLE=20

# Maximum articles from same domain per post (integer)
MAX_ARTICLES_PER_DOMAIN=2

# Default temporal window for article selection in days (1-365)
TEMPORAL_WINDOW_DAYS_DEFAULT=90
```

These can also be adjusted at runtime via the Admin UI at `/admin/content-quality` (requires admin role).
