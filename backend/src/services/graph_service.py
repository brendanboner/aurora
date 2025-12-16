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
        people = [p.get("name") for p in row.get("people", []) if p.get("name")]
        
        # Extract detailed people information with affiliations
        people_details = []
        for person_data in row.get("people_details", []):
            person_node = person_data.get("person")
            if not person_node:
                continue
            
            person_info = {
                "name": person_node.get("name"),
                "email": person_node.get("email")
            }
            
            # Add organizational affiliations if they exist
            affiliations = person_data.get("affiliations", [])
            if affiliations:
                # Filter out empty affiliations (where both org and role are null)
                valid_affiliations = [
                    aff for aff in affiliations 
                    if aff.get("organization") or aff.get("role")
                ]
                if valid_affiliations:
                    person_info["affiliations"] = valid_affiliations
            
            people_details.append(person_info)
        
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
                "people": people,
                "people_details": people_details,
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


def query_upcoming_events(filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fetch upcoming events with graceful fallback if Neo4j unavailable."""
    try:
        repo = get_repo()
        rows = repo.get_upcoming_events(
            start_date=filters.get("start_date"),
            topics=filters.get("topics") or [],
            organisations=filters.get("organisations") or [],
            limit=int(filters.get("limit") or 20),
        )
    except Exception as e:
        log.warning(f"Neo4j event query failed; returning empty events: {e}")
        return []
    
    events: List[Dict[str, Any]] = []
    for row in rows:
        e = row.get("event", {})
        resources = row.get("resources", [])
        topics = [t.get("name") for t in row.get("topics", []) if t.get("name")]
        orgs = [o.get("name") for o in row.get("organisations", []) if o.get("name")]
        
        # Convert DateTime objects to strings
        start_date = _convert_datetime_to_string(e.get("start_date"))
        end_date = _convert_datetime_to_string(e.get("end_date"))
        
        # Get resource details
        resource_details = []
        for r in resources:
            if not r:
                continue
            resource_details.append({
                "title": r.get("title"),
                "url": r.get("url"),
                "publish_date": _convert_datetime_to_string(r.get("publish_date")) or _convert_datetime_to_string(r.get("scraped_at")),
                "summary": r.get("summary", "")
            })
        
        events.append({
            "name": e.get("name"),
            "event_type": e.get("event_type"),
            "start_date": start_date,
            "end_date": end_date,
            "location": e.get("location"),
            "timezone": e.get("timezone"),
            "description": e.get("description"),
            "url": e.get("url"),
            "topics": topics,
            "organisations": orgs,
            "resources": resource_details
        })
    
    return events


def query_past_events(filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fetch past events with graceful fallback if Neo4j unavailable."""
    try:
        repo = get_repo()
        rows = repo.get_past_events(
            start_date=filters.get("start_date"),
            end_date=filters.get("end_date"),
            topics=filters.get("topics") or [],
            organisations=filters.get("organisations") or [],
            limit=int(filters.get("limit") or 20),
        )
    except Exception as e:
        log.warning(f"Neo4j event query failed; returning empty events: {e}")
        return []
    
    events: List[Dict[str, Any]] = []
    for row in rows:
        e = row.get("event", {})
        resources = row.get("resources", [])
        topics = [t.get("name") for t in row.get("topics", []) if t.get("name")]
        orgs = [o.get("name") for o in row.get("organisations", []) if o.get("name")]
        
        # Convert DateTime objects to strings
        start_date = _convert_datetime_to_string(e.get("start_date"))
        end_date = _convert_datetime_to_string(e.get("end_date"))
        
        # Get resource details
        resource_details = []
        for r in resources:
            if not r:
                continue
            resource_details.append({
                "title": r.get("title"),
                "url": r.get("url"),
                "publish_date": _convert_datetime_to_string(r.get("publish_date")) or _convert_datetime_to_string(r.get("scraped_at")),
                "summary": r.get("summary", "")
            })
        
        events.append({
            "name": e.get("name"),
            "event_type": e.get("event_type"),
            "start_date": start_date,
            "end_date": end_date,
            "location": e.get("location"),
            "timezone": e.get("timezone"),
            "description": e.get("description"),
            "url": e.get("url"),
            "topics": topics,
            "organisations": orgs,
            "resources": resource_details
        })
    
    return events


def query_temporal_documents(
    filters: Dict[str, Any],
    temporal_focus: str,
    publish_weight: float = 1.0,
    update_weight: float = 0.8
) -> Dict[str, Any]:
    """Query documents based on temporal focus (published/updated/mixed).
    
    Args:
        filters: Query filters (start_date, end_date, topics, organisations, people, etc.)
        temporal_focus: "published", "updated", or "mixed"
        publish_weight: Weight for newly published documents (default: 1.0)
        update_weight: Weight for updated documents (default: 0.8)
        
    Returns:
        Dict with documents, published_count, updated_count, total_count
    """
    try:
        repo = get_repo()
        
        if temporal_focus == "published":
            # Query only newly published documents
            rows = repo.query_documents_by_publish_date(
                start_date=filters.get("start_date"),
                end_date=filters.get("end_date"),
                topics=filters.get("topics") or [],
                organisations=filters.get("organisations") or [],
                limit=int(filters.get("limit") or 20)
            )
            
            docs = []
            for row in rows:
                doc = _format_document_row(row)
                doc["temporal_type"] = "published"
                doc["weighted_score"] = row.get("publish_recency_score", 0.5) * publish_weight
                docs.append(doc)
            
            return {
                "documents": docs,
                "published_count": len(docs),
                "updated_count": 0,
                "total_count": len(docs)
            }
            
        elif temporal_focus == "updated":
            # Query only recently updated documents
            rows = repo.query_recently_updated_documents(
                start_date=filters.get("start_date"),
                end_date=filters.get("end_date"),
                topics=filters.get("topics") or [],
                organisations=filters.get("organisations") or [],
                limit=int(filters.get("limit") or 20)
            )
            
            docs = []
            for row in rows:
                doc = _format_document_row(row)
                doc["temporal_type"] = "updated"
                doc["weighted_score"] = row.get("update_recency_score", 0.5) * update_weight
                docs.append(doc)
            
            return {
                "documents": docs,
                "published_count": 0,
                "updated_count": len(docs),
                "total_count": len(docs)
            }
            
        else:  # "mixed"
            # Query both published and updated documents with weighted scoring
            result = repo.query_temporal_mixed(
                start_date=filters.get("start_date"),
                end_date=filters.get("end_date"),
                topics=filters.get("topics") or [],
                organisations=filters.get("organisations") or [],
                publish_weight=publish_weight,
                update_weight=update_weight,
                limit=int(filters.get("limit") or 20)
            )
            
            docs = []
            for row in result.get("documents", []):
                doc = _format_document_row(row)
                doc["temporal_type"] = row.get("temporal_type", "unknown")
                doc["weighted_score"] = row.get("weighted_score", 0.5)
                docs.append(doc)
            
            return {
                "documents": docs,
                "published_count": result.get("published_count", 0),
                "updated_count": result.get("updated_count", 0),
                "total_count": result.get("total_count", 0)
            }
            
    except Exception as e:
        log.warning(f"Temporal document query failed; returning empty result: {e}")
        return {
            "documents": [],
            "published_count": 0,
            "updated_count": 0,
            "total_count": 0
        }


def _format_document_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Format a document row from Neo4j query result."""
    topics = []
    if isinstance(row.get("topics"), list):
        topics = [t.get("name") for t in row["topics"] if isinstance(t, dict) and t.get("name")]
    
    orgs = []
    if isinstance(row.get("organisations"), list):
        orgs = [o.get("name") for o in row["organisations"] if isinstance(o, dict) and o.get("name")]
    
    people = []
    if isinstance(row.get("people"), list):
        people = [p.get("name") for p in row["people"] if isinstance(p, dict) and p.get("name")]
    
    datasources = []
    if isinstance(row.get("datasources"), list):
        datasources = [ds.get("name") for ds in row["datasources"] if isinstance(ds, dict) and ds.get("name")]
    
    return {
        "url_hash": row.get("url_hash"),
        "url": row.get("url"),
        "title": row.get("title"),
        "summary": row.get("summary"),
        "category": row.get("category"),
        "doc_type": row.get("doc_type"),
        "publish_date": _convert_datetime_to_string(row.get("publish_date")),
        "scraped_at": _convert_datetime_to_string(row.get("scraped_at")),
        "content_changed_at": _convert_datetime_to_string(row.get("content_changed_at")),
        "created_at": _convert_datetime_to_string(row.get("created_at")),
        "importance": row.get("importance"),
        "topics": topics,
        "organisations": orgs,
        "people": people,
        "datasources": datasources
    }


def get_graph_statistics() -> Dict[str, Any]:
    """Get statistics about nodes in the knowledge graph."""
    repo = get_repo()
    # Collect counts using CALL subqueries with variable scope (Neo4j 5+ syntax)
    query = """
        CALL () {
            MATCH (r:Resource) RETURN count(r) as resources
        }
        CALL () {
            MATCH (t:Topic) RETURN count(t) as topics
        }
        CALL () {
            MATCH (o:Organization) RETURN count(o) as organisations
        }
        CALL () {
            MATCH (p:Person) RETURN count(p) as people
        }
        CALL () {
            MATCH (e:Event) RETURN count(e) as events
        }
        CALL () {
            MATCH (ds:DataSource) RETURN count(ds) as datasources
        }
        CALL () {
            MATCH ()-[rel]->() RETURN count(rel) as relationships
        }
        RETURN resources, topics, organisations, people, events, datasources, relationships
    """
    results = repo.client.execute_query(query, {})
    return dict(results[0]) if results else {
        "resources": 0,
        "topics": 0,
        "organisations": 0,
        "people": 0,
        "events": 0,
        "datasources": 0,
        "relationships": 0
    }


# =============================================================================
# DataSource Configuration Management (Admin UI)
# =============================================================================

def get_all_datasource_configurations() -> List[Dict[str, Any]]:
    """
    Get all datasource configurations from Neo4j.
    Returns all DataSource nodes with their properties.
    """
    repo = get_repo()
    query = """
    MATCH (ds:DataSource)
    RETURN ds
    ORDER BY ds.datasource_id
    """
    results = repo.client.execute_query(query, {})
    configs = []
    for record in results:
        ds_node = dict(record["ds"])
        # Convert datetime fields to strings for JSON serialization
        for field in ["last_scraped_at", "created_at", "updated_at"]:
            if field in ds_node:
                ds_node[field] = _convert_datetime_to_string(ds_node[field])
        configs.append(ds_node)
    return configs


def get_datasource_configuration(datasource_id: str) -> Dict[str, Any] | None:
    """
    Get a specific datasource configuration from Neo4j.
    """
    repo = get_repo()
    query = """
    MATCH (ds:DataSource {datasource_id: $datasource_id})
    RETURN ds
    """
    results = repo.client.execute_query(query, {"datasource_id": datasource_id})
    if not results:
        return None
    
    ds_node = dict(results[0]["ds"])
    # Convert datetime fields to strings
    for field in ["last_scraped_at", "created_at", "updated_at"]:
        if field in ds_node:
            ds_node[field] = _convert_datetime_to_string(ds_node[field])
    return ds_node


def upsert_datasource_configuration(
    datasource_id: str,
    name: str | None = None,
    scraper_type: str | None = None,
    resource_url: str | None = None,
    scrape_schedule: str | None = None,
    run_on_startup: bool | None = None,
    check_content_hash: bool | None = None,
    publish_weight: float | None = None,
    update_weight: float | None = None,
    event_weight: float | None = None,
    temporal_extraction_days: int | None = None,
    scraper_delay: float | None = None,
    max_resources: int | None = None,
    max_redirects: int | None = None,
    folders: List[str] | None = None,
    discovery_mode: str | None = None,
    consecutive_duplicates_limit: int | None = None,
    full_refresh_schedule: str | None = None
) -> Dict[str, Any]:
    """
    Create or update a datasource configuration in Neo4j.
    Only updates provided fields (non-None values).
    """
    from datetime import datetime
    
    repo = get_repo()
    
    # Build SET clause for properties that were provided
    set_parts = []
    params = {"datasource_id": datasource_id}
    
    # Always update updated_at timestamp
    set_parts.append("ds.updated_at = datetime()")
    
    # Add provided fields to update
    field_map = {
        "name": name,
        "scraper_type": scraper_type,
        "resource_url": resource_url,
        "scrape_schedule": scrape_schedule,
        "run_on_startup": run_on_startup,
        "check_content_hash": check_content_hash,
        "publish_weight": publish_weight,
        "update_weight": update_weight,
        "event_weight": event_weight,
        "temporal_extraction_days": temporal_extraction_days,
        "scraper_delay": scraper_delay,
        "max_resources": max_resources,
        "max_redirects": max_redirects,
        "folders": folders,
        "discovery_mode": discovery_mode,
        "consecutive_duplicates_limit": consecutive_duplicates_limit,
        "full_refresh_schedule": full_refresh_schedule
    }
    
    for field, value in field_map.items():
        if value is not None:
            set_parts.append(f"ds.{field} = ${field}")
            params[field] = value
    
    # Check if node exists to determine if we need to set created_at
    check_query = "MATCH (ds:DataSource {datasource_id: $datasource_id}) RETURN ds"
    existing = repo.client.execute_query(check_query, {"datasource_id": datasource_id})
    
    if not existing:
        # New node - set created_at
        set_parts.append("ds.created_at = datetime()")
        # Set defaults for required fields if not provided
        if name is None:
            set_parts.append("ds.name = $datasource_id")
    
    # Build the MERGE + SET query
    set_clause = ", ".join(set_parts)
    query = f"""
    MERGE (ds:DataSource {{datasource_id: $datasource_id}})
    SET {set_clause}
    RETURN ds
    """
    
    results = repo.client.execute_write(query, params)
    if not results:
        raise Exception(f"Failed to upsert datasource configuration for {datasource_id}")
    
    ds_node = dict(results[0]["ds"])
    # Convert datetime fields to strings
    for field in ["last_scraped_at", "created_at", "updated_at"]:
        if field in ds_node:
            ds_node[field] = _convert_datetime_to_string(ds_node[field])
    return ds_node


def delete_datasource_configuration(datasource_id: str) -> bool:
    """
    Delete a datasource configuration from Neo4j.
    Returns True if deleted, False if not found.
    """
    repo = get_repo()
    query = """
    MATCH (ds:DataSource {datasource_id: $datasource_id})
    DETACH DELETE ds
    RETURN count(ds) as deleted_count
    """
    results = repo.client.execute_write(query, {"datasource_id": datasource_id})
    if results and results[0]["deleted_count"] > 0:
        return True
    return False


def check_user_in_graph(user_uuid: str) -> bool:
    """
    Check if a user exists in the Neo4j graph as a Person node.
    
    Args:
        user_uuid: The UUID of the user from Postgres
        
    Returns:
        True if the user exists in the graph, False otherwise
    """
    try:
        repo = get_repo()
        query = """
        MATCH (p:Person {user_uuid: $user_uuid})
        RETURN p.person_id as person_id
        LIMIT 1
        """
        results = repo.client.execute_query(query, {"user_uuid": user_uuid})
        has_user = len(results) > 0
        return has_user
    except Exception as e:
        log.warning(f"Failed to check user in graph: {e}")
        return False
