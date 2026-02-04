"""Documents service for managing user uploaded documents."""

import logging
import os
from typing import List, Dict, Any, Optional

import boto3
from botocore.exceptions import ClientError
from neo4j_client.client import Neo4jClient

logger = logging.getLogger(__name__)

# Document categories for user uploads
DOCUMENT_CATEGORIES = [
    {
        "id": "meeting_minutes",
        "name": "Meeting Minutes",
        "description": "Meeting notes and minutes"
    },
    {
        "id": "presentation",
        "name": "Presentation",
        "description": "Slides and presentations"
    },
    {
        "id": "specification",
        "name": "Specification",
        "description": "Technical specifications"
    },
    {
        "id": "whitepaper",
        "name": "Whitepaper",
        "description": "Whitepapers and research documents"
    },
    {
        "id": "report",
        "name": "Report",
        "description": "Reports and analyses"
    },
    {
        "id": "agenda",
        "name": "Agenda",
        "description": "Meeting agendas"
    },
    {
        "id": "general",
        "name": "General",
        "description": "General documents"
    }
]


def _get_neo4j_client() -> Neo4jClient:
    """
    Get a properly configured Neo4j client.
    
    Returns:
        Configured Neo4jClient instance
        
    Raises:
        Exception: If Neo4j connection cannot be established
    """
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


def _get_s3_client():
    """Get S3 client for generating presigned URLs."""
    return boto3.client(
        's3',
        region_name=os.getenv("AWS_REGION", "us-east-1")
    )


def get_document_categories() -> List[Dict[str, str]]:
    """
    Get available document categories for user uploads.
    
    Returns:
        List of category dictionaries with id, name, and description
    """
    return DOCUMENT_CATEGORIES


def get_user_uploads(
    user_uuid: str,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Get documents uploaded by a specific user.
    
    Args:
        user_uuid: User's UUID
        limit: Maximum number of results
        offset: Pagination offset
    
    Returns:
        List of document dictionaries
    """
    client = _get_neo4j_client()
    
    query = """
    MATCH (r:Resource)-[u:UPLOADED_BY]->(p:Person {user_uuid: $user_uuid})
    RETURN r.url_hash as url_hash,
           r.title as title,
           r.url as url,
           r.category as category,
           r.doc_type as doc_type,
           r.s3_key as s3_key,
           r.s3_bucket as s3_bucket,
           r.scraped_at as uploaded_at,
           u.uploaded_at as upload_timestamp
    ORDER BY r.scraped_at DESC
    SKIP $offset
    LIMIT $limit
    """
    
    results = client.execute_query(query, {
        "user_uuid": user_uuid,
        "limit": limit,
        "offset": offset
    })
    
    return results


def get_document_by_id(url_hash: str) -> Optional[Dict[str, Any]]:
    """
    Get a document by its URL hash.
    
    Args:
        url_hash: The document's url_hash (unique identifier)
    
    Returns:
        Document dictionary or None if not found
    """
    client = _get_neo4j_client()
    
    query = """
    MATCH (r:Resource {url_hash: $url_hash})
    OPTIONAL MATCH (r)-[u:UPLOADED_BY]->(p:Person)
    RETURN r.url_hash as url_hash,
           r.title as title,
           r.url as url,
           r.category as category,
           r.doc_type as doc_type,
           r.s3_key as s3_key,
           r.s3_bucket as s3_bucket,
           r.scraped_at as uploaded_at,
           r.summary as summary,
           p.name as uploaded_by_name,
           p.user_uuid as uploaded_by_uuid,
           u.uploaded_at as upload_timestamp
    """
    
    results = client.execute_query(query, {"url_hash": url_hash})
    return results[0] if results else None


def get_document_download_url(url_hash: str) -> Optional[Dict[str, Any]]:
    """
    Get a presigned S3 URL for downloading a document.
    
    Args:
        url_hash: The document's url_hash (unique identifier)
    
    Returns:
        Dictionary with download_url and expires_in, or None if not found
    """
    client = _get_neo4j_client()
    
    # Get S3 info from Neo4j
    query = """
    MATCH (r:Resource {url_hash: $url_hash})
    WHERE r.s3_key IS NOT NULL AND r.s3_bucket IS NOT NULL
    RETURN r.s3_key as s3_key, r.s3_bucket as s3_bucket
    """
    
    results = client.execute_query(query, {"url_hash": url_hash})
    
    if not results:
        return None
    
    s3_key = results[0]["s3_key"]
    s3_bucket = results[0]["s3_bucket"]
    
    if not s3_key or not s3_bucket:
        return None
    
    # Generate presigned URL
    s3_client = _get_s3_client()
    expiration = 3600  # 1 hour
    
    try:
        download_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': s3_bucket,
                'Key': s3_key
            },
            ExpiresIn=expiration
        )
        
        return {
            "download_url": download_url,
            "expires_in": expiration
        }
    except ClientError as e:
        logger.error(f"Failed to generate presigned URL for {url_hash}: {e}")
        return None


def get_event_documents(url_hash: str) -> List[Dict[str, Any]]:
    """
    Get documents related to an event.
    
    Args:
        url_hash: Event URL hash (ID)
    
    Returns:
        List of related documents with metadata
    """
    client = _get_neo4j_client()
    
    query = """
    MATCH (e:Event {url_hash: $url_hash})<-[rel:RELATES_TO]-(r:Resource)
    OPTIONAL MATCH (r)-[u:UPLOADED_BY]->(p:Person)
    RETURN r.url_hash as url_hash,
           r.title as title,
           r.url as url,
           r.category as category,
           r.doc_type as doc_type,
           r.s3_key as s3_key,
           r.s3_bucket as s3_bucket,
           rel.confidence as confidence,
           rel.context_type as context_type,
           rel.evidence as evidence,
           p.name as uploaded_by_name
    ORDER BY rel.confidence DESC, r.scraped_at DESC
    """
    
    results = client.execute_query(query, {"url_hash": url_hash})
    return results


def get_event_document_count(url_hash: str) -> int:
    """
    Get count of documents related to an event.
    
    Args:
        url_hash: Event URL hash (ID)
    
    Returns:
        Number of related documents
    """
    client = _get_neo4j_client()
    
    query = """
    MATCH (e:Event {url_hash: $url_hash})<-[:RELATES_TO]-(r:Resource)
    RETURN count(r) as doc_count
    """
    
    results = client.execute_query(query, {"url_hash": url_hash})
    return results[0]["doc_count"] if results else 0


def check_duplicate_content(content_hash: str) -> Optional[Dict[str, Any]]:
    """
    Check if a document with the same content hash already exists.
    
    Args:
        content_hash: SHA256 hash of the document content
    
    Returns:
        Existing document info if duplicate found, None otherwise
    """
    client = _get_neo4j_client()
    
    query = """
    MATCH (r:Resource {content_hash: $content_hash})
    RETURN r.url_hash as url_hash,
           r.title as title,
           r.url as url
    LIMIT 1
    """
    
    results = client.execute_query(query, {"content_hash": content_hash})
    return results[0] if results else None


def check_duplicate_s3_key(s3_key: str) -> Optional[Dict[str, Any]]:
    """
    Check if a document with the same S3 key already exists.
    
    Args:
        s3_key: S3 object key path
    
    Returns:
        Existing document info if duplicate found, None otherwise
    """
    client = _get_neo4j_client()
    
    query = """
    MATCH (r:Resource {s3_key: $s3_key})
    RETURN r.url_hash as url_hash,
           r.title as title,
           r.url as url
    LIMIT 1
    """
    
    results = client.execute_query(query, {"s3_key": s3_key})
    return results[0] if results else None


def update_document(
    url_hash: str,
    user_uuid: str,
    title: Optional[str] = None,
    category: Optional[str] = None,
    related_events: Optional[List[str]] = None
) -> Optional[Dict[str, Any]]:
    """
    Update a document's metadata and related events.
    
    Only the owner can update their documents.
    
    Args:
        url_hash: Document's url_hash
        user_uuid: User's UUID (must be the owner)
        title: New title (optional)
        category: New category (optional)
        related_events: List of event url_hashes to link to (optional)
    
    Returns:
        Updated document info or None if not found/not authorized
    """
    client = _get_neo4j_client()
    
    # Verify ownership
    ownership_query = """
    MATCH (r:Resource {url_hash: $url_hash})-[:UPLOADED_BY]->(p:Person {user_uuid: $user_uuid})
    RETURN r.url_hash as url_hash
    """
    
    results = client.execute_query(ownership_query, {
        "url_hash": url_hash,
        "user_uuid": user_uuid
    })
    
    if not results:
        return None
    
    # Build update query for metadata
    set_clauses = []
    params = {"url_hash": url_hash}
    
    if title is not None:
        set_clauses.append("r.title = $title")
        params["title"] = title
    
    if category is not None:
        set_clauses.append("r.category = $category")
        params["category"] = category
    
    if set_clauses:
        update_query = f"""
        MATCH (r:Resource {{url_hash: $url_hash}})
        SET {', '.join(set_clauses)}
        """
        client.execute_query(update_query, params)
    
    # Handle related events update
    if related_events is not None:
        # First, remove all existing RELATES_TO relationships to events
        remove_query = """
        MATCH (r:Resource {url_hash: $url_hash})-[rel:RELATES_TO]->(e:Event)
        DELETE rel
        """
        client.execute_query(remove_query, {"url_hash": url_hash})
        
        # Then, create new relationships for the specified events
        if related_events:
            create_query = """
            MATCH (r:Resource {url_hash: $url_hash})
            UNWIND $event_hashes as event_hash
            MATCH (e:Event {url_hash: event_hash})
            MERGE (r)-[:RELATES_TO]->(e)
            """
            client.execute_query(create_query, {
                "url_hash": url_hash,
                "event_hashes": related_events
            })
    
    # Return updated document
    return get_document_by_id(url_hash)


def delete_document(url_hash: str, user_uuid: str) -> bool:
    """
    Delete a document.
    
    Only the owner can delete their documents.
    This removes the Resource node and all its relationships.
    Note: S3 object is NOT deleted to allow for recovery if needed.
    
    Args:
        url_hash: Document's url_hash
        user_uuid: User's UUID (must be the owner)
    
    Returns:
        True if deleted, False if not found/not authorized
    """
    client = _get_neo4j_client()
    
    # Verify ownership and delete in one query
    delete_query = """
    MATCH (r:Resource {url_hash: $url_hash})-[:UPLOADED_BY]->(p:Person {user_uuid: $user_uuid})
    WITH r
    DETACH DELETE r
    RETURN count(r) as deleted_count
    """
    
    results = client.execute_query(delete_query, {
        "url_hash": url_hash,
        "user_uuid": user_uuid
    })
    
    return results[0]["deleted_count"] > 0 if results else False


def get_document_events(url_hash: str) -> List[Dict[str, Any]]:
    """
    Get events that a document is related to.
    
    Args:
        url_hash: Document's url_hash
    
    Returns:
        List of related events
    """
    client = _get_neo4j_client()
    
    query = """
    MATCH (r:Resource {url_hash: $url_hash})-[:RELATES_TO]->(e:Event)
    RETURN e.url_hash as url_hash,
           e.name as name,
           e.start_date as start_date,
           e.event_type as event_type
    ORDER BY e.start_date DESC
    """
    
    results = client.execute_query(query, {"url_hash": url_hash})
    return results
