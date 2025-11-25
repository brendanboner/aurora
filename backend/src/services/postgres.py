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
            "scrape_frequency": "daily",
            "check_content_hash": True,
            "publish_weight": 1.0,
            "update_weight": 0.8,
            "event_weight": 0.9,
            "last_scraped_at": None
        }
    return result


def upsert_system_configuration(
    datasource_id: str,
    name: Optional[str] = None,
    scrape_frequency: Optional[str] = None,
    check_content_hash: Optional[bool] = None,
    publish_weight: Optional[float] = None,
    update_weight: Optional[float] = None,
    event_weight: Optional[float] = None
) -> Dict[str, Any]:
    """Create or update system configuration for a datasource."""
    query = """
        INSERT INTO system_configuration 
            (datasource_id, name, scrape_frequency, check_content_hash, publish_weight, update_weight, event_weight)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (datasource_id) DO UPDATE SET
            name = COALESCE(EXCLUDED.name, system_configuration.name),
            scrape_frequency = COALESCE(EXCLUDED.scrape_frequency, system_configuration.scrape_frequency),
            check_content_hash = COALESCE(EXCLUDED.check_content_hash, system_configuration.check_content_hash),
            publish_weight = COALESCE(EXCLUDED.publish_weight, system_configuration.publish_weight),
            update_weight = COALESCE(EXCLUDED.update_weight, system_configuration.update_weight),
            event_weight = COALESCE(EXCLUDED.event_weight, system_configuration.event_weight),
            updated_at = NOW()
        RETURNING *
    """
    params = (datasource_id, name, scrape_frequency, check_content_hash, publish_weight, update_weight, event_weight)
    return fetchone(query, params)


def get_all_system_configurations() -> List[Dict[str, Any]]:
    """Get all system configurations."""
    query = "SELECT * FROM system_configuration ORDER BY datasource_id"
    return fetchall(query)
