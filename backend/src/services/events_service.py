"""Events service for managing event queries and attendance."""

import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from neo4j_client.client import Neo4jClient
from neo4j_client.models import PersonAttendingEvent

logger = logging.getLogger(__name__)


def _get_neo4j_client() -> Neo4jClient:
    """
    Get a properly configured Neo4j client.
    
    Returns:
        Configured Neo4jClient instance
        
    Raises:
        Exception: If Neo4j connection cannot be established
    """
    # Get Neo4j connection details from environment
    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "neo4j")
    database = os.getenv("NEO4J_DATABASE", "neo4j")
    
    try:
        client = Neo4jClient(uri=uri, user=user, password=password, database=database)
        client.connect()
        return client
    except Exception as e:
        logger.error(f"Failed to connect to Neo4j: {e}")
        raise Exception("Database connection failed") from e


def get_events(
    upcoming: Optional[bool] = None,
    datasource_id: Optional[str] = None,
    event_type: Optional[str] = None,
    sort_by: str = "start_date",
    sort_order: str = "asc",
    limit: int = 100,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Get events with optional filtering and sorting.
    
    Args:
        upcoming: If True, only future events; if False, only past events; if None, all events
        datasource_id: Filter by datasource
        event_type: Filter by event type (e.g., 'conference', 'meeting', 'webinar')
        sort_by: Field to sort by ('start_date', 'name', 'event_type')
        sort_order: 'asc' or 'desc'
        limit: Maximum number of results
        offset: Pagination offset
    
    Returns:
        List of event dictionaries with attendance counts
    """
    client = _get_neo4j_client()
    
    # Build query with filters
    where_clauses = []
    params = {
        "now": datetime.utcnow().isoformat(),
        "limit": limit,
        "offset": offset
    }
    
    if upcoming is not None:
        if upcoming:
            # Dates are stored as ISO strings - convert to datetime for comparison
            where_clauses.append("datetime(e.start_date) >= datetime($now)")
        else:
            where_clauses.append("datetime(e.start_date) < datetime($now)")
    
    if datasource_id:
        where_clauses.append("e.datasource_id = $datasource_id")
        params["datasource_id"] = datasource_id
    
    if event_type:
        where_clauses.append("toLower(e.event_type) = toLower($event_type)")
        params["event_type"] = event_type
    
    where_clause = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    
    # Validate sort_by and sort_order
    valid_sort_fields = {"start_date", "name", "event_type", "end_date"}
    if sort_by not in valid_sort_fields:
        sort_by = "start_date"
    
    sort_order = "ASC" if sort_order.lower() == "asc" else "DESC"
    
    query = f"""
    MATCH (e:Event)
    {where_clause}
    OPTIONAL MATCH (p:Person)-[a:ATTENDING]->(e)
    WITH e, 
         count(DISTINCT p) as attendee_count,
         count(DISTINCT CASE WHEN a.is_presenting = true THEN p END) as presenter_count
    RETURN e.url_hash as url_hash,
           e.name as name,
           e.event_type as event_type,
           e.start_date as start_date,
           e.end_date as end_date,
           e.location as location,
           e.timezone as timezone,
           e.description as description,
           e.url as url,
           e.status as status,
           e.datasource_id as datasource_id,
           attendee_count,
           presenter_count
    ORDER BY e.{sort_by} {sort_order}
    SKIP $offset
    LIMIT $limit
    """
    
    results = client.execute_query(query, params)
    return results


def get_event_by_id(url_hash: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get a single event by URL hash with attendance information.
    
    Args:
        url_hash: Event URL hash (ID)
        user_id: Optional user ID to check if user is attending
    
    Returns:
        Event dictionary with attendance details, or None if not found
    """
    client = _get_neo4j_client()
    
    params = {"url_hash": url_hash}
    
    # Base query for event details
    query = """
    MATCH (e:Event {url_hash: $url_hash})
    OPTIONAL MATCH (p:Person)-[a:ATTENDING]->(e)
    WITH e, 
         count(DISTINCT p) as attendee_count,
         count(DISTINCT CASE WHEN a.is_presenting = true THEN p END) as presenter_count
    """
    
    # Add user attendance check if user_id provided
    if user_id:
        params["user_id"] = user_id
        query += """
        OPTIONAL MATCH (user:Person {user_uuid: $user_id})-[user_att:ATTENDING]->(e)
        RETURN e.url_hash as url_hash,
               e.name as name,
               e.event_type as event_type,
               e.start_date as start_date,
               e.end_date as end_date,
               e.location as location,
               e.timezone as timezone,
               e.description as description,
               e.url as url,
               e.status as status,
               e.datasource_id as datasource_id,
               e.scraped_at as scraped_at,
               attendee_count,
               presenter_count,
               user_att IS NOT NULL as is_attending,
               user_att.is_presenting as is_presenting,
               user_att.marked_at as marked_at
        """
    else:
        query += """
        RETURN e.url_hash as url_hash,
               e.name as name,
               e.event_type as event_type,
               e.start_date as start_date,
               e.end_date as end_date,
               e.location as location,
               e.timezone as timezone,
               e.description as description,
               e.url as url,
               e.status as status,
               e.datasource_id as datasource_id,
               e.scraped_at as scraped_at,
               attendee_count,
               presenter_count,
               false as is_attending,
               false as is_presenting,
               null as marked_at
        """
    
    results = client.execute_query(query, params)
    return results[0] if results else None


def get_event_attendees(url_hash: str) -> List[Dict[str, Any]]:
    """
    Get list of people attending an event.
    
    Args:
        url_hash: Event URL hash (ID)
    
    Returns:
        List of attendee dictionaries with name, email, is_presenting, marked_at
    """
    client = _get_neo4j_client()
    
    query = """
    MATCH (p:Person)-[a:ATTENDING]->(e:Event {url_hash: $url_hash})
    RETURN p.person_id as person_id,
           p.name as name,
           p.email as email,
           p.user_uuid as user_uuid,
           a.is_presenting as is_presenting,
           a.marked_at as marked_at
    ORDER BY a.marked_at DESC
    """
    
    results = client.execute_query(query, {"url_hash": url_hash})
    return results


def mark_attendance(
    user_uuid: str,
    url_hash: str,
    is_presenting: bool = False,
    attending: bool = True
) -> Dict[str, Any]:
    """
    Mark or update user's attendance for an event.
    
    Args:
        user_uuid: User's UUID from Postgres
        url_hash: Event URL hash (ID)
        is_presenting: Whether user is presenting
        attending: True to mark attendance, False to remove attendance
    
    Returns:
        Result dictionary with success status
    """
    client = _get_neo4j_client()
    
    if not attending:
        # Remove attendance
        query = """
        MATCH (p:Person {user_uuid: $user_uuid})-[a:ATTENDING]->(e:Event {url_hash: $url_hash})
        DELETE a
        RETURN true as success
        """
        result = client.execute_query(query, {"user_uuid": user_uuid, "url_hash": url_hash})
        return {"success": bool(result), "attending": False}
    
    # Check if Person node exists for this user by user_uuid
    person_query = """
    MATCH (p:Person {user_uuid: $user_uuid})
    RETURN p.person_id as person_id
    """
    person_result = client.execute_query(person_query, {"user_uuid": user_uuid})
    
    if not person_result:
        # Person not found by user_uuid - this shouldn't happen if user sync is working
        # Log the error and return a clear message
        logger.error(f"Person node not found for user {user_uuid}. User may not be synced to Neo4j.")
        return {
            "success": False, 
            "error": "User profile not found. Please try logging out and back in to sync your profile."
        }
    
    person_id = person_result[0]["person_id"]
    
    # Check if event exists
    event_query = """
    MATCH (e:Event {url_hash: $url_hash})
    RETURN e.url_hash as url_hash
    """
    event_result = client.execute_query(event_query, {"url_hash": url_hash})
    
    if not event_result:
        logger.error(f"Event not found: {url_hash}")
        return {"success": False, "error": "Event not found"}
    
    # Create or update ATTENDING relationship
    now = datetime.utcnow()
    relationship = PersonAttendingEvent(
        source_id=person_id,
        target_id=url_hash,
        marked_at=now,
        is_presenting=is_presenting
    )
    
    # Use MERGE to create or update
    query = """
    MATCH (p:Person {person_id: $person_id})
    MATCH (e:Event {url_hash: $url_hash})
    MERGE (p)-[a:ATTENDING]->(e)
    SET a.marked_at = datetime($marked_at),
        a.is_presenting = $is_presenting
    RETURN true as success
    """
    
    result = client.execute_query(query, {
        "person_id": person_id,
        "url_hash": url_hash,
        "marked_at": now.isoformat(),
        "is_presenting": is_presenting
    })
    
    return {
        "success": bool(result),
        "attending": True,
        "is_presenting": is_presenting,
        "marked_at": now.isoformat()
    }


def get_user_attending_events(user_uuid: str, upcoming_only: bool = True) -> List[Dict[str, Any]]:
    """
    Get events that a user is attending.
    
    Args:
        user_uuid: User's UUID from Postgres
        upcoming_only: If True, only return upcoming events
    
    Returns:
        List of events the user is attending
    """
    client = _get_neo4j_client()
    
    where_clause = ""
    params = {"user_uuid": user_uuid}
    
    if upcoming_only:
        where_clause = "WHERE e.start_date >= datetime($now)"
        params["now"] = datetime.utcnow().isoformat()
    
    query = f"""
    MATCH (p:Person {{user_uuid: $user_uuid}})-[a:ATTENDING]->(e:Event)
    {where_clause}
    RETURN e.url_hash as url_hash,
           e.name as name,
           e.event_type as event_type,
           e.start_date as start_date,
           e.end_date as end_date,
           e.location as location,
           e.url as url,
           a.is_presenting as is_presenting,
           a.marked_at as marked_at
    ORDER BY e.start_date ASC
    """
    
    results = client.execute_query(query, params)
    return results


def get_event_filters() -> Dict[str, Any]:
    """
    Get available filter values for events.
    
    Returns:
        Dictionary with:
        - event_types: List of distinct event types
        - datasources: List of datasources with id, name, and event count
    """
    client = _get_neo4j_client()
    
    # Get distinct event types with counts
    event_types_query = """
    MATCH (e:Event)
    WHERE e.event_type IS NOT NULL
    RETURN DISTINCT e.event_type as type, count(e) as count
    ORDER BY type
    """
    event_types_results = client.execute_query(event_types_query, {})
    event_types = [{"type": r["type"], "count": r["count"]} for r in event_types_results]
    
    # Get datasources with event counts
    # Use both INGESTED_FROM relationship and direct datasource_id property matching
    datasources_query = """
    MATCH (ds:DataSource)
    OPTIONAL MATCH (e:Event)
    WHERE e.datasource_id = ds.datasource_id
    WITH ds, count(e) as event_count
    WHERE event_count > 0
    RETURN ds.datasource_id as datasource_id,
           ds.name as name,
           event_count
    ORDER BY name
    """
    datasources_results = client.execute_query(datasources_query, {})
    datasources = [
        {
            "datasource_id": r["datasource_id"],
            "name": r["name"],
            "event_count": r["event_count"]
        }
        for r in datasources_results
    ]
    
    return {
        "event_types": event_types,
        "datasources": datasources
    }
