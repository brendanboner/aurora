import os
import psycopg2
import psycopg2.extras
from typing import List, Dict, Any, Optional

PG_DSN = os.getenv(
    "PG_DSN",
    "postgresql://aurora:aurora_password@localhost:5432/aurora"
)

_conn = None

def get_conn():
    global _conn
    if _conn is None:
        _conn = psycopg2.connect(PG_DSN)
        _conn.autocommit = True
    return _conn

def fetchone(query, params=None):
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params or [])
        return cur.fetchone()

def fetchall(query, params=None):
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params or [])
        return cur.fetchall()

def execute(query, params=None):
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params or [])
        return cur.rowcount


# ========== User Management ==========

def create_user(email: str, display_name: str) -> Dict[str, Any]:
    """Create a new user."""
    query = """
        INSERT INTO app_users (email, display_name)
        VALUES (%s, %s)
        RETURNING id, email, display_name, created_at, updated_at
    """
    return fetchone(query, (email, display_name))

def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """Get user by ID."""
    query = "SELECT * FROM app_users WHERE id = %s"
    return fetchone(query, (user_id,))

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Get user by email."""
    query = "SELECT * FROM app_users WHERE email = %s"
    return fetchone(query, (email,))

def get_all_users() -> List[Dict[str, Any]]:
    """Get all users."""
    query = "SELECT * FROM app_users ORDER BY created_at DESC"
    return fetchall(query)

def update_user(user_id: int, display_name: str) -> Optional[Dict[str, Any]]:
    """Update user display name."""
    query = """
        UPDATE app_users
        SET display_name = %s, updated_at = NOW()
        WHERE id = %s
        RETURNING id, email, display_name, created_at, updated_at
    """
    return fetchone(query, (display_name, user_id))

def delete_user(user_id: int) -> int:
    """Delete a user."""
    query = "DELETE FROM app_users WHERE id = %s"
    return execute(query, (user_id,))


# ========== User Preferences ==========

def get_user_preferences(user_id: int) -> Dict[str, Any]:
    """Get user preferences."""
    query = "SELECT * FROM user_preferences WHERE user_id = %s"
    result = fetchone(query, (user_id,))
    if not result:
        # Return default preferences if none exist
        return {
            "user_id": user_id,
            "topics": [],
            "organisations": [],
            "people": [],
            "sources": [],
            "notify_email": True,
            "notify_digest": True
        }
    return result

def upsert_user_preferences(
    user_id: int,
    topics: Optional[List[str]] = None,
    organisations: Optional[List[str]] = None,
    people: Optional[List[str]] = None,
    sources: Optional[List[str]] = None,
    notify_email: Optional[bool] = None,
    notify_digest: Optional[bool] = None
) -> Dict[str, Any]:
    """Create or update user preferences."""
    query = """
        INSERT INTO user_preferences (user_id, topics, organisations, people, sources, notify_email, notify_digest)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            topics = COALESCE(EXCLUDED.topics, user_preferences.topics),
            organisations = COALESCE(EXCLUDED.organisations, user_preferences.organisations),
            people = COALESCE(EXCLUDED.people, user_preferences.people),
            sources = COALESCE(EXCLUDED.sources, user_preferences.sources),
            notify_email = COALESCE(EXCLUDED.notify_email, user_preferences.notify_email),
            notify_digest = COALESCE(EXCLUDED.notify_digest, user_preferences.notify_digest),
            updated_at = NOW()
        RETURNING *
    """
    params = (
        user_id,
        topics,
        organisations,
        people,
        sources,
        notify_email,
        notify_digest
    )
    return fetchone(query, params)


# ========== System Configuration ==========

def get_system_configuration(datasource_id: str = "default") -> Dict[str, Any]:
    """Get system configuration for a datasource.
    
    Returns configuration with relevance weights for temporal queries.
    If no configuration exists, returns default values.
    """
    query = "SELECT * FROM system_configuration WHERE datasource_id = %s"
    result = fetchone(query, (datasource_id,))
    if not result:
        # Return default configuration
        return {
            "datasource_id": datasource_id,
            "name": datasource_id,
            "scraper_type": None,
            "resource_url": None,
            "scrape_schedule": None,
            "run_on_startup": False,
            "check_content_hash": True,
            "publish_weight": 1.0,
            "update_weight": 0.8,
            "event_weight": 0.9,
            "temporal_extraction_days": 90,
            "discovery_mode": "incremental",
            "consecutive_duplicates_limit": 5,
            "full_refresh_schedule": None,
            "last_scraped_at": None
        }
    return result


def upsert_system_configuration(
    datasource_id: str,
    name: Optional[str] = None,
    scraper_type: Optional[str] = None,
    resource_url: Optional[str] = None,
    scrape_schedule: Optional[str] = None,
    run_on_startup: Optional[bool] = None,
    check_content_hash: Optional[bool] = None,
    publish_weight: Optional[float] = None,
    update_weight: Optional[float] = None,
    event_weight: Optional[float] = None,
    temporal_extraction_days: Optional[int] = None,
    scraper_delay: Optional[float] = None,
    max_resources: Optional[int] = None,
    max_redirects: Optional[int] = None,
    folders: Optional[List[str]] = None,
    discovery_mode: Optional[str] = None,
    consecutive_duplicates_limit: Optional[int] = None,
    full_refresh_schedule: Optional[str] = None
) -> Dict[str, Any]:
    """Create or update system configuration for a datasource."""
    import json
    from psycopg2.extras import Json
    
    query = """
        INSERT INTO system_configuration 
            (datasource_id, name, scraper_type, resource_url, scrape_schedule, run_on_startup,
             check_content_hash, publish_weight, update_weight, event_weight, temporal_extraction_days,
             scraper_delay, max_resources, max_redirects, folders,
             discovery_mode, consecutive_duplicates_limit, full_refresh_schedule)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (datasource_id) DO UPDATE SET
            name = COALESCE(EXCLUDED.name, system_configuration.name),
            scraper_type = COALESCE(EXCLUDED.scraper_type, system_configuration.scraper_type),
            resource_url = COALESCE(EXCLUDED.resource_url, system_configuration.resource_url),
            scrape_schedule = COALESCE(EXCLUDED.scrape_schedule, system_configuration.scrape_schedule),
            run_on_startup = COALESCE(EXCLUDED.run_on_startup, system_configuration.run_on_startup),
            check_content_hash = COALESCE(EXCLUDED.check_content_hash, system_configuration.check_content_hash),
            publish_weight = COALESCE(EXCLUDED.publish_weight, system_configuration.publish_weight),
            update_weight = COALESCE(EXCLUDED.update_weight, system_configuration.update_weight),
            event_weight = COALESCE(EXCLUDED.event_weight, system_configuration.event_weight),
            temporal_extraction_days = COALESCE(EXCLUDED.temporal_extraction_days, system_configuration.temporal_extraction_days),
            scraper_delay = COALESCE(EXCLUDED.scraper_delay, system_configuration.scraper_delay),
            max_resources = COALESCE(EXCLUDED.max_resources, system_configuration.max_resources),
            max_redirects = COALESCE(EXCLUDED.max_redirects, system_configuration.max_redirects),
            folders = COALESCE(EXCLUDED.folders, system_configuration.folders),
            discovery_mode = COALESCE(EXCLUDED.discovery_mode, system_configuration.discovery_mode),
            consecutive_duplicates_limit = COALESCE(EXCLUDED.consecutive_duplicates_limit, system_configuration.consecutive_duplicates_limit),
            full_refresh_schedule = COALESCE(EXCLUDED.full_refresh_schedule, system_configuration.full_refresh_schedule),
            updated_at = NOW()
        RETURNING *
    """
    # Convert folders list to psycopg2 Json object for proper JSONB handling
    folders_value = Json(folders) if folders is not None else None
    params = (datasource_id, name, scraper_type, resource_url, scrape_schedule, run_on_startup,
              check_content_hash, publish_weight, update_weight, event_weight, temporal_extraction_days,
              scraper_delay, max_resources, max_redirects, folders_value,
              discovery_mode, consecutive_duplicates_limit, full_refresh_schedule)
    return fetchone(query, params)


def get_all_system_configurations() -> List[Dict[str, Any]]:
    """Get all system configurations."""
    query = "SELECT * FROM system_configuration ORDER BY datasource_id"
    return fetchall(query)
