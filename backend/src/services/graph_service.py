import os
import logging
from typing import Any, Dict, List

from neo4j_client.client import Neo4jClient
from neo4j_client.repository import GraphRepository

log = logging.getLogger("graph_service")


def _convert_datetime_to_string(value: Any) -> str | None:
    """Convert Neo4j DateTime objects to ISO format strings.
    
    Handles:
    - Neo4j DateTime objects (have isoformat method)
    - Python datetime objects (have isoformat method)
    - Already-string values
    - None values
    """
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return str(value)

_repo: GraphRepository | None = None


def get_repo() -> GraphRepository:
    """Return a connected GraphRepository with host fallbacks.

    Attempts env-provided URI first, then common service names then localhost.
    This prevents DNS issues when switching between docker-compose and ad-hoc
    container runs. Logs failures but does not raise, allowing higher layers to
    fallback gracefully.
    """
    global _repo
    if _repo is not None:
        return _repo

    env_uri = os.getenv("NEO4J_URI")
    candidates: List[str] = []
    if env_uri:
        candidates.append(env_uri)
    # Add common service DNS names used in compose / make targets
    for host in ["bolt://neo4j:7687", "bolt://aurora-neo4j:7687", "bolt://localhost:7687"]:
        if host not in candidates:
            candidates.append(host)

    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "neo4j")
    database = os.getenv("NEO4J_DATABASE", "neo4j")

    last_error: Exception | None = None
    for uri in candidates:
        try:
            client = Neo4jClient(uri=uri, user=user, password=password, database=database)
            client.connect()
            _repo = GraphRepository(client)
            log.info(f"Connected to Neo4j via {uri}")
            return _repo
        except Exception as e:  # connection or DNS failure
            last_error = e
            log.warning(f"Neo4j connection attempt failed for {uri}: {e}")
            continue

    # All attempts failed: create repository with first candidate; operations will fail but higher layer has fallbacks
    fallback_uri = candidates[0] if candidates else "bolt://localhost:7687"
    log.error(f"All Neo4j connection attempts failed; using fallback URI {fallback_uri}. Last error: {last_error}")
    client = Neo4jClient(uri=fallback_uri, user=user, password=password, database=database)
    _repo = GraphRepository(client)
    return _repo


def query_documents_from_filters(filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fetch relevant documents with graceful fallback if Neo4j unavailable.

    Instead of raising connection errors (which surfaced as 500s in /query), we
    now catch exceptions and return an empty list allowing the LLM layer to
    still provide a response.
    """
    try:
        repo = get_repo()
        rows = repo.get_recent_resources(
            start=filters.get("start_date"),
            end=filters.get("end_date"),
            topics=filters.get("topics") or [],
            organisations=filters.get("organisations") or [],
            people=filters.get("people") or [],
            category=filters.get("category"),
            doc_type=filters.get("doc_type"),
            limit=int(filters.get("limit") or 20),
        )
    except Exception as e:
        log.warning(f"Neo4j query failed; returning empty documents: {e}")
        return []

    docs: List[Dict[str, Any]] = []
    for row in rows:
        r = row.get("resource", {})
        topics = [t.get("name") for t in row.get("topics", []) if t.get("name")]
        orgs = [o.get("name") for o in row.get("organisations", []) if o.get("name")]
        
        # Convert DateTime objects to strings for API compatibility
        publish_date = _convert_datetime_to_string(r.get("publish_date"))
        if not publish_date:
            publish_date = _convert_datetime_to_string(r.get("scraped_at"))
        
        docs.append(
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "publish_date": publish_date,
                "summary": r.get("summary", ""),
                "topics": topics,
                "organisations": orgs,
            }
        )
    return docs


def get_all_topics(limit: int = 1000) -> List[Dict[str, Any]]:
    """Get all topics from the knowledge graph."""
    repo = get_repo()
    query = """
        MATCH (t:Topic)
        RETURN t.topic_id as id, t.name as name, t.aliases as aliases, 
               t.classification as classification
        ORDER BY t.name
        LIMIT $limit
    """
    results = repo.client.execute_query(query, {"limit": limit})
    return [dict(r) for r in results]


def get_all_organisations(limit: int = 1000) -> List[Dict[str, Any]]:
    """Get all organisations from the knowledge graph."""
    repo = get_repo()
    query = """
        MATCH (o:Organization)
        RETURN o.org_id as id, o.name as name, o.aliases as aliases, 
               o.org_type as org_type
        ORDER BY o.name
        LIMIT $limit
    """
    results = repo.client.execute_query(query, {"limit": limit})
    return [dict(r) for r in results]


def get_all_people(limit: int = 1000) -> List[Dict[str, Any]]:
    """Get all people from the knowledge graph."""
    repo = get_repo()
    query = """
        MATCH (p:Person)
        RETURN p.person_id as id, p.name as name, p.email as email
        ORDER BY p.name
        LIMIT $limit
    """
    results = repo.client.execute_query(query, {"limit": limit})
    return [dict(r) for r in results]


def get_graph_statistics() -> Dict[str, Any]:
    """Get statistics about nodes in the knowledge graph."""
    repo = get_repo()
    # Collect counts, including total relationships between any nodes.
    query = """
        MATCH (r:Resource) WITH count(r) as resources
        MATCH (t:Topic) WITH resources, count(t) as topics
        MATCH (o:Organization) WITH resources, topics, count(o) as organisations
        MATCH (p:Person) WITH resources, topics, organisations, count(p) as people
        MATCH (ds:DataSource) WITH resources, topics, organisations, people, count(ds) as datasources
        MATCH ()-[rel]->() WITH resources, topics, organisations, people, datasources, count(rel) as relationships
        RETURN resources, topics, organisations, people, datasources, relationships
    """
    results = repo.client.execute_query(query, {})
    return dict(results[0]) if results else {
        "resources": 0,
        "topics": 0,
        "organisations": 0,
        "people": 0,
        "datasources": 0,
        "relationships": 0
    }
