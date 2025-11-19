import os
from typing import Any, Dict, List

from neo4j_client.client import Neo4jClient
from neo4j_client.repository import GraphRepository

_repo: GraphRepository | None = None


def get_repo() -> GraphRepository:
    global _repo
    if _repo is not None:
        return _repo

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "neo4j")
    database = os.getenv("NEO4J_DATABASE", "neo4j")

    client = Neo4jClient(uri=uri, user=user, password=password, database=database)
    _repo = GraphRepository(client)
    return _repo


def query_documents_from_filters(filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Use GraphRepository.get_recent_resources to fetch relevant docs for the filters.
    """
    repo = get_repo()

    rows = repo.get_recent_resources(
        start=filters.get("start_date"),
        end=filters.get("end_date"),
        topics=filters.get("topics") or [],
        organisations=filters.get("organisations") or [],
        people=filters.get("people") or [],
        limit=int(filters.get("limit") or 20),
    )

    docs: List[Dict[str, Any]] = []
    for row in rows:
        r = row["resource"]
        topics = [t.get("name") for t in row.get("topics", []) if t.get("name")]
        orgs = [o.get("name") for o in row.get("organisations", []) if o.get("name")]

        docs.append(
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "publish_date": r.get("publish_date") or r.get("scraped_at"),
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
    query = """
        MATCH (r:Resource) WITH count(r) as resources
        MATCH (t:Topic) WITH resources, count(t) as topics
        MATCH (o:Organization) WITH resources, topics, count(o) as organisations
        MATCH (p:Person) WITH resources, topics, organisations, count(p) as people
        MATCH (ds:DataSource) WITH resources, topics, organisations, people, count(ds) as datasources
        RETURN resources, topics, organisations, people, datasources
    """
    results = repo.client.execute_query(query, {})
    return dict(results[0]) if results else {
        "resources": 0,
        "topics": 0,
        "organisations": 0,
        "people": 0,
        "datasources": 0
    }
