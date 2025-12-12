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
