import os
import psycopg2
import psycopg2.extras
from psycopg2.extras import Json
from typing import List, Dict, Any, Optional, TYPE_CHECKING
import logging

logger = logging.getLogger(__name__)

PG_DSN = os.getenv(
    "PG_DSN",
    "postgresql://aurora:aurora_password@localhost:5432/aurora"
)

_conn = None
_conn_lock = None

def get_conn():
    """
    Get database connection.
    Uses a singleton pattern with basic thread safety.
    
    Note: This is a simple connection pool. For production with high concurrency,
    consider using a proper connection pool like psycopg2.pool.ThreadedConnectionPool.
    """
    global _conn, _conn_lock
    
    # Lazy initialization of lock
    if _conn_lock is None:
        import threading
        _conn_lock = threading.Lock()
    
    with _conn_lock:
        # Check if connection is alive
        if _conn is not None:
            try:
                # Test connection with a simple query
                with _conn.cursor() as cur:
                    cur.execute("SELECT 1")
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                logger.warning("Database connection lost, reconnecting...")
                try:
                    _conn.close()
                except:
                    pass
                _conn = None
        
        # Create new connection if needed
        if _conn is None:
            logger.info(f"Creating new database connection to {PG_DSN.split('@')[1] if '@' in PG_DSN else 'database'}")
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

def create_user(user_id: str, email: str, display_name: str) -> Dict[str, Any]:
    """
    Create a new user with Cognito UUID.
    Handles concurrent creation attempts gracefully using ON CONFLICT.
    
    Args:
        user_id: Cognito user UUID (from sub claim)
        email: User email
        display_name: User display name
    
    Returns:
        User dict (either newly created or existing if race condition occurred)
    
    Note:
        Email has UNIQUE constraint. If user_id collision occurs, we update email/display_name.
        If email collision occurs with different user_id, PostgreSQL will raise IntegrityError.
        This shouldn't happen in normal Cognito flow (one user = one email = one sub).
    """
    query = """
        INSERT INTO app_users (id, email, display_name)
        VALUES (%s, %s, %s)
        ON CONFLICT (id) DO UPDATE 
        SET email = EXCLUDED.email,
            display_name = COALESCE(EXCLUDED.display_name, app_users.display_name),
            updated_at = NOW()
        RETURNING id, email, display_name, created_at, updated_at
    """
    try:
        return fetchone(query, (user_id, email, display_name))
    except psycopg2.IntegrityError as e:
        if 'app_users_email_key' in str(e) or 'duplicate key value violates unique constraint' in str(e):
            # Email already exists with different user_id - this is a data inconsistency
            logger.error(
                f"Email {email} already exists with different user_id. "
                f"Attempted user_id: {user_id}. This indicates a Cognito/database mismatch."
            )
            raise ValueError(
                f"Email {email} is already registered to another user. "
                "This should not happen with Cognito. Please contact support."
            ) from e
        raise

def _migrate_user_id(old_id: str, new_id: str, email: str, display_name: str) -> Dict[str, Any]:
    """
    Migrate a user from an old ID to a new Cognito sub claim ID.
    This handles SSO integration where existing users need their IDs updated.
    
    Updates all related tables (user_preferences, event_attendance, etc.) in a transaction.
    
    Args:
        old_id: Existing user ID in database
        new_id: New Cognito sub claim ID
        email: User email (for verification)
        display_name: Display name to use
    
    Returns:
        Updated user dict
    """
    conn = get_conn()
    
    try:
        # Need to temporarily disable autocommit for transaction
        original_autocommit = conn.autocommit
        conn.autocommit = False
        
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # CRITICAL: Update app_users FIRST so the new_id exists before dependent tables reference it
            # When we UPDATE app_users SET id=new_id WHERE id=old_id:
            #   - The row's PK changes from old_id to new_id
            #   - Dependent tables still have old_id in their FK columns (temporarily invalid)
            # Then we UPDATE dependent tables SET user_id=new_id WHERE user_id=old_id:
            #   - Finds rows by their current value (old_id)
            #   - Changes them to new_id
            #   - FK constraint check verifies new_id exists in app_users (it does)
            # At COMMIT, all FK constraints are satisfied.
            cur.execute(
                """
                UPDATE app_users 
                SET id = %s, display_name = COALESCE(%s, display_name), updated_at = NOW()
                WHERE id = %s AND email = %s
                RETURNING id, email, display_name, created_at, updated_at
                """,
                (new_id, display_name, old_id, email)
            )
            
            user = cur.fetchone()
            
            if not user:
                raise ValueError(f"Failed to migrate user {old_id} - user not found or email mismatch")
            
            # Now update all dependent tables - they still have old_id values
            # The WHERE clause finds them by old_id, SET changes to new_id
            # FK constraints check that new_id exists in app_users (it does now)
            
            # Backend database tables
            cur.execute(
                "UPDATE user_preferences SET user_id = %s WHERE user_id = %s",
                (new_id, old_id)
            )
            cur.execute(
                "UPDATE event_attendance SET user_id = %s WHERE user_id = %s",
                (new_id, old_id)
            )
            cur.execute(
                "UPDATE chat_conversations SET user_id = %s WHERE user_id = %s",
                (new_id, old_id)
            )
            cur.execute(
                "UPDATE chat_messages SET user_id = %s WHERE user_id = %s",
                (new_id, old_id)
            )
            cur.execute(
                "UPDATE user_feedback SET user_id = %s WHERE user_id = %s",
                (new_id, old_id)
            )
            cur.execute(
                "UPDATE user_source_memberships SET user_id = %s WHERE user_id = %s",
                (new_id, old_id)
            )
            
            # Content creator service tables (share same PostgreSQL database)
            cur.execute(
                "UPDATE user_preference_profile SET user_id = %s WHERE user_id = %s",
                (new_id, old_id)
            )
            cur.execute(
                "UPDATE user_agent_follow SET user_id = %s WHERE user_id = %s",
                (new_id, old_id)
            )
            cur.execute(
                "UPDATE user_post_reaction SET user_id = %s WHERE user_id = %s",
                (new_id, old_id)
            )
            cur.execute(
                "UPDATE user_agent SET user_id = %s WHERE user_id = %s",
                (new_id, old_id)
            )
            
            # Commit the transaction
            conn.commit()
            logger.info(f"Successfully migrated user from {old_id} to {new_id}")
            return user
            
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to migrate user ID from {old_id} to {new_id}: {e}")
        raise
    finally:
        # Restore original autocommit setting
        conn.autocommit = original_autocommit


def get_or_create_user(
    user_id: str, 
    email: str, 
    display_name: Optional[str] = None,
    given_name: Optional[str] = None,
    family_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get user by ID, or create if doesn't exist in Postgres.
    Also ensures user is synced to Neo4j graph database.
    
    This function handles SSO migration scenarios where a user may exist with
    an old ID but needs to be updated with a new Cognito sub claim.
    
    This function is called automatically by the UserSyncMiddleware on every
    authenticated request, ensuring users exist in both Postgres and Neo4j
    regardless of which endpoint they access first.
    
    Args:
        user_id: Cognito user UUID (from X-User-Id header)
        email: User email (from X-User-Email header)
        display_name: Optional display name (defaults to email prefix if not provided)
        given_name: Optional first name
        family_name: Optional last name
    
    Returns:
        User dict from Postgres
    """
    # Set default display name if not provided
    if not display_name:
        display_name = email.split('@')[0]  # Use email prefix as default
    
    # Try to get existing user from Postgres by ID
    user = get_user_by_id(user_id)
    
    if not user:
        # Check if a user with this email already exists (SSO migration scenario)
        existing_user = get_user_by_email(email)
        
        if existing_user:
            # User exists with old ID - update to new Cognito sub claim
            old_id = existing_user['id']
            logger.info(f"Migrating user {email} from old ID {old_id} to new Cognito ID {user_id}")
            user = _migrate_user_id(old_id, user_id, email, display_name)
        else:
            # Create new user in Postgres if doesn't exist
            # Note: create_user has ON CONFLICT handling for race conditions
            logger.info(f"Creating new user in Postgres: {user_id} ({email})")
            try:
                user = create_user(user_id, email, display_name)
            except ValueError as e:
                # Email already registered to different user_id (shouldn't happen with Cognito)
                logger.error(f"Failed to create user {user_id} ({email}): {e}")
                raise
    else:
        # User already exists - update email/display_name if they've changed in Cognito
        # This handles the case where user changed email in Cognito
        if user['email'] != email or (display_name and user['display_name'] != display_name):
            logger.info(
                f"Updating user {user_id}: email {user['email']}->{email}, "
                f"display_name {user['display_name']}->{display_name}"
            )
            # Use create_user which has ON CONFLICT logic to update
            user = create_user(user_id, email, display_name)
    
    # Always ensure user is synced to Neo4j (function checks if already synced)
    _ensure_user_in_neo4j(user_id, email, user.get('display_name', display_name), given_name, family_name)
    
    return user


def _ensure_user_in_neo4j(user_uuid: str, email: str, full_name: str, given_name: Optional[str] = None, family_name: Optional[str] = None):
    """
    Ensure user exists in Neo4j graph database.
    
    This function:
    1. Checks if a Person node with this user_uuid already exists
    2. If not, uses the deduplicator to find potential matching Person nodes
    3. Either creates a new Person node or updates existing one with user_uuid
    
    Args:
        user_uuid: UUID from Postgres users table
        email: User email
        full_name: User's full name/display name (stored in Person.name field)
        given_name: Optional first name (for logging/debugging)
        family_name: Optional last name (for logging/debugging)
    """
    client = None
    try:
        from neo4j_client.client import Neo4jClient
        from neo4j_client.repository import GraphRepository
        from neo4j_client.models import Person
        from neo4j_client.deduplicator import NodeDeduplicator
        
        # Log name details if provided
        if given_name or family_name:
            logger.debug(f"User name details - Given: {given_name}, Family: {family_name}, Full: {full_name}")
        
        # Get Neo4j connection details from environment
        uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "neo4j")
        database = os.getenv("NEO4J_DATABASE", "neo4j")
        
        client = Neo4jClient(uri=uri, user=user, password=password, database=database)
        client.connect()
        
        # Create repository for node operations
        repo = GraphRepository(client, logger)
        
        # Check if user already exists in Neo4j by user_uuid
        query = """
        MATCH (p:Person {user_uuid: $user_uuid})
        RETURN p.person_id as person_id, p.name as name, p.email as email, p.user_uuid as user_uuid
        """
        result = client.execute_query(query, {"user_uuid": user_uuid})
        
        if result:
            logger.info(f"User {user_uuid} already exists in Neo4j as Person node {result[0]['person_id']}")
            return
        
        # User doesn't exist - use deduplicator to find potential matches
        new_person = Person(name=full_name, email=email, user_uuid=user_uuid)
        
        # Initialize deduplicator and check for duplicates
        logger.debug(f"Searching for duplicate Person nodes for {email}")
        deduplicator = NodeDeduplicator(client, logger)
        duplicate_info = deduplicator.find_duplicate(
            node=new_person,
            node_label="Person",
            k_neighbors=5,
            similarity_threshold=0.85,  # High threshold for person matching
            llm_review_threshold=0.70    # Use LLM for medium confidence matches
        )
        
        person_id = None
        
        if duplicate_info and duplicate_info.get("is_duplicate"):
            # Found a matching Person node - update it with user_uuid
            person_id = duplicate_info["existing_id"]
            existing_node = duplicate_info["existing_node"]
            
            logger.info(
                f"Found existing Person node for user {user_uuid}: {person_id} "
                f"(name: '{existing_node.get('name')}', score: {duplicate_info.get('similarity_score', 0):.2f})"
            )
            
            # Update existing Person node with user_uuid
            query = """
            MATCH (p:Person {person_id: $person_id})
            SET p.user_uuid = $user_uuid,
                p.email = COALESCE($email, p.email),
                p.name = COALESCE($name, p.name)
            RETURN p.person_id as person_id
            """
            client.execute_query(query, {
                "person_id": person_id,
                "user_uuid": user_uuid,
                "email": email,
                "name": full_name
            })
            logger.info(f"Updated Person node {person_id} with user_uuid {user_uuid}")
        else:
            # No duplicate found - create new Person node
            logger.info(f"Creating new Person node for user {user_uuid}")
            person = Person(name=full_name, email=email, user_uuid=user_uuid)
            repo.create_node(person)
            logger.info(f"Created Person node {person.person_id} for user {user_uuid}")
            
    except Exception as e:
        logger.error(f"Failed to sync user {user_uuid} to Neo4j: {e}", exc_info=True)
        # Don't fail the request if Neo4j sync fails
    finally:
        # Always close Neo4j connection to prevent connection leaks
        if client is not None:
            try:
                client.close()
            except Exception as e:
                logger.warning(f"Failed to close Neo4j connection: {e}")
```
                raise ValueError(f"Failed to migrate user {old_id} - user not found or email mismatch")
            
            # Commit the transaction
            conn.commit()
            logger.info(f"Successfully migrated user from {old_id} to {new_id}")
            return user
            
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to migrate user ID from {old_id} to {new_id}: {e}")
        raise
    finally:
        # Restore original autocommit setting
        conn.autocommit = original_autocommit


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:  # Changed from int to str
    """Get user by Cognito UUID."""
    query = "SELECT * FROM app_users WHERE id = %s"
    return fetchone(query, (user_id,))

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Get user by email."""
    query = "SELECT * FROM app_users WHERE email = %s"
    return fetchone(query, (email,))

def get_all_users() -> List[Dict[str, Any]]:
    """Get all users with their Neo4j sync status."""
    # Import at runtime to avoid circular dependency (graph_service imports postgres)
    from . import graph_service
    
    query = "SELECT * FROM app_users ORDER BY created_at DESC"
    users = fetchall(query)
    
    # Add sync status for each user
    for user in users:
        try:
            user['synced_to_graph'] = graph_service.check_user_in_graph(user['id'])
        except Exception as e:
            logger.warning(f"Failed to check sync status for user {user['id']}: {e}")
            user['synced_to_graph'] = False  # Default to False on error
    
    return users

def update_user(user_id: str, display_name: str) -> Optional[Dict[str, Any]]:  # Changed from int to str
    """Update user display name."""
    query = """
        UPDATE app_users
        SET display_name = %s, updated_at = NOW()
        WHERE id = %s
        RETURNING id, email, display_name, created_at, updated_at
    """
    return fetchone(query, (display_name, user_id))

def delete_user(user_id: str) -> int:  # Changed from int to str
    """Delete a user."""
    query = "DELETE FROM app_users WHERE id = %s"
    return execute(query, (user_id,))


# ========== User Preferences ==========

def get_user_preferences(user_id: str) -> Dict[str, Any]:  # Changed from int to str
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
            "domains": [],
            "notify_email": True,
            "notify_digest": True
        }
    return result

def upsert_user_preferences(
    user_id: str,  # Changed from int to str
    topics: Optional[List[str]] = None,
    organisations: Optional[List[str]] = None,
    people: Optional[List[str]] = None,
    sources: Optional[List[str]] = None,
    domains: Optional[List[str]] = None,
    notify_email: Optional[bool] = None,
    notify_digest: Optional[bool] = None
) -> Dict[str, Any]:
    """Create or update user preferences."""
    query = """
        INSERT INTO user_preferences (user_id, topics, organisations, people, sources, domains, notify_email, notify_digest)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            topics = COALESCE(EXCLUDED.topics, user_preferences.topics),
            organisations = COALESCE(EXCLUDED.organisations, user_preferences.organisations),
            people = COALESCE(EXCLUDED.people, user_preferences.people),
            sources = COALESCE(EXCLUDED.sources, user_preferences.sources),
            domains = COALESCE(EXCLUDED.domains, user_preferences.domains),
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
        domains,
        notify_email,
        notify_digest
    )
    return fetchone(query, params)


# ========== User Source Memberships ==========

def get_user_source_memberships(user_id: str) -> Dict[str, Any]:
    """
    Get all source memberships for a user.

    Returns:
        Dict with 'joined' and 'ignored' lists of datasource_ids.
    """
    query = "SELECT datasource_id, status FROM user_source_memberships WHERE user_id = %s"
    rows = fetchall(query, (user_id,))
    joined = [r["datasource_id"] for r in rows if r["status"] == "joined"]
    ignored = [r["datasource_id"] for r in rows if r["status"] == "ignored"]
    return {"joined": joined, "ignored": ignored}


def upsert_user_source_membership(user_id: str, datasource_id: str, status: str) -> Dict[str, Any]:
    """
    Create or update a user's membership status for a datasource.

    Args:
        user_id: Cognito user UUID
        datasource_id: DataSource node ID (e.g. 'wfa_causeway_wifi7mtg')
        status: 'joined' or 'ignored'

    Returns:
        The upserted row.
    """
    query = """
        INSERT INTO user_source_memberships (user_id, datasource_id, status)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, datasource_id) DO UPDATE SET
            status = EXCLUDED.status,
            updated_at = NOW()
        RETURNING *
    """
    return fetchone(query, (user_id, datasource_id, status))


def delete_user_source_membership(user_id: str, datasource_id: str) -> bool:
    """
    Remove a user's membership preference for a datasource (reverts to default).

    Returns:
        True if a row was deleted, False if it didn't exist.
    """
    query = """
        DELETE FROM user_source_memberships
        WHERE user_id = %s AND datasource_id = %s
        RETURNING datasource_id
    """
    result = fetchone(query, (user_id, datasource_id))
    return result is not None


# ========== System Configuration ==========

# ========== System Configuration (MIGRATED TO NEO4J) ==========
# Note: The system_configuration table has been migrated to Neo4j DataSource nodes.
# All configuration is now managed through graph_service functions.
# See: graph_service.get_datasource_configuration() and graph_service.upsert_datasource_configuration()

# ========== Chat Conversations & Messages ==========

def create_conversation(user_id: str, title: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a new chat conversation for a user.
    
    Args:
        user_id: User's Cognito UUID
        title: Optional conversation title (can be auto-generated from first message)
    
    Returns:
        Conversation dict with id, user_id, title, created_at, updated_at
    """
    query = """
        INSERT INTO chat_conversations (user_id, title)
        VALUES (%s, %s)
        RETURNING id, user_id, title, created_at, updated_at
    """
    return fetchone(query, (user_id, title))


def get_conversation(conversation_id: int) -> Optional[Dict[str, Any]]:
    """Get a conversation by ID."""
    query = "SELECT * FROM chat_conversations WHERE id = %s"
    return fetchone(query, (conversation_id,))


def get_user_conversations(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get all conversations for a user, ordered by most recent.
    
    Args:
        user_id: User's Cognito UUID
        limit: Maximum number of conversations to return (default 50)
    
    Returns:
        List of conversation dicts
    """
    query = """
        SELECT * FROM chat_conversations 
        WHERE user_id = %s 
        ORDER BY updated_at DESC 
        LIMIT %s
    """
    return fetchall(query, (user_id, limit))


def update_conversation_title(conversation_id: int, title: str) -> Optional[Dict[str, Any]]:
    """Update conversation title and updated_at timestamp."""
    query = """
        UPDATE chat_conversations 
        SET title = %s, updated_at = NOW()
        WHERE id = %s
        RETURNING id, user_id, title, created_at, updated_at
    """
    return fetchone(query, (title, conversation_id))


def delete_conversation(conversation_id: int) -> int:
    """Delete a conversation (will cascade delete all messages)."""
    query = "DELETE FROM chat_conversations WHERE id = %s"
    return execute(query, (conversation_id,))


def save_message(
    conversation_id: int,
    user_id: str,
    role: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Save a chat message to the database.
    
    Args:
        conversation_id: ID of the conversation
        user_id: User's Cognito UUID
        role: 'user' or 'assistant'
        content: Message text content
        metadata: Optional dict with filters, documents, etc. (stored as JSONB)
    
    Returns:
        Message dict with all fields
    """
    query = """
        INSERT INTO chat_messages (conversation_id, user_id, role, content, metadata)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id, conversation_id, user_id, role, content, metadata, created_at
    """
    # Convert metadata to JSON for psycopg2
    metadata_value = Json(metadata) if metadata is not None else None
    result = fetchone(query, (conversation_id, user_id, role, content, metadata_value))
    
    # Also update the conversation's updated_at timestamp
    execute(
        "UPDATE chat_conversations SET updated_at = NOW() WHERE id = %s",
        (conversation_id,)
    )
    
    return result


def get_conversation_messages(conversation_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Get all messages for a conversation, ordered chronologically.
    
    Args:
        conversation_id: ID of the conversation
        limit: Maximum number of messages to return (default 100)
    
    Returns:
        List of message dicts
    """
    query = """
        SELECT * FROM chat_messages 
        WHERE conversation_id = %s 
        ORDER BY created_at ASC 
        LIMIT %s
    """
    return fetchall(query, (conversation_id, limit))


def get_user_messages(user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Get all messages for a user across all conversations (for analytics).
    
    Args:
        user_id: User's Cognito UUID
        limit: Maximum number of messages to return (default 100)
    
    Returns:
        List of message dicts ordered by most recent
    """
    query = """
        SELECT * FROM chat_messages 
        WHERE user_id = %s 
        ORDER BY created_at DESC 
        LIMIT %s
    """
    return fetchall(query, (user_id, limit))


# ========== Admin Chat Analytics ==========

def get_all_conversations_admin(limit: int = 100, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get all conversations for admin view, optionally filtered by user.
    Includes user email and message count for each conversation.
    
    Args:
        limit: Maximum number of conversations to return
        user_id: Optional filter by specific user
    
    Returns:
        List of conversation dicts with user info and message counts
    """
    if user_id:
        query = """
            SELECT 
                c.id,
                c.user_id,
                c.title,
                c.created_at,
                c.updated_at,
                u.email,
                u.display_name,
                COUNT(m.id) as message_count
            FROM chat_conversations c
            JOIN app_users u ON c.user_id = u.id
            LEFT JOIN chat_messages m ON c.id = m.conversation_id
            WHERE c.user_id = %s
            GROUP BY c.id, c.user_id, c.title, c.created_at, c.updated_at, u.email, u.display_name
            ORDER BY c.updated_at DESC
            LIMIT %s
        """
        return fetchall(query, (user_id, limit))
    else:
        query = """
            SELECT 
                c.id,
                c.user_id,
                c.title,
                c.created_at,
                c.updated_at,
                u.email,
                u.display_name,
                COUNT(m.id) as message_count
            FROM chat_conversations c
            JOIN app_users u ON c.user_id = u.id
            LEFT JOIN chat_messages m ON c.id = m.conversation_id
            GROUP BY c.id, c.user_id, c.title, c.created_at, c.updated_at, u.email, u.display_name
            ORDER BY c.updated_at DESC
            LIMIT %s
        """
        return fetchall(query, (limit,))


def get_conversation_with_user_admin(conversation_id: int) -> Optional[Dict[str, Any]]:
    """
    Get conversation with user details for admin view.
    
    Args:
        conversation_id: ID of the conversation
    
    Returns:
        Conversation dict with user info
    """
    query = """
        SELECT 
            c.id,
            c.user_id,
            c.title,
            c.created_at,
            c.updated_at,
            u.email,
            u.display_name
        FROM chat_conversations c
        JOIN app_users u ON c.user_id = u.id
        WHERE c.id = %s
    """
    return fetchone(query, (conversation_id,))


def get_chat_statistics() -> Dict[str, Any]:
    """
    Get overall chat statistics for admin dashboard.
    
    Returns:
        Dict with various statistics
    """
    query = """
        SELECT 
            COUNT(DISTINCT c.id) as total_conversations,
            COUNT(DISTINCT c.user_id) as unique_users,
            COUNT(m.id) as total_messages,
            COUNT(CASE WHEN m.role = 'user' THEN 1 END) as user_messages,
            COUNT(CASE WHEN m.role = 'assistant' THEN 1 END) as assistant_messages,
            AVG(msg_count.count) as avg_messages_per_conversation
        FROM chat_conversations c
        LEFT JOIN chat_messages m ON c.id = m.conversation_id
        LEFT JOIN (
            SELECT conversation_id, COUNT(*) as count
            FROM chat_messages
            GROUP BY conversation_id
        ) msg_count ON c.id = msg_count.conversation_id
    """
    result = fetchone(query)
    
    # Get recent activity (last 7 days)
    recent_query = """
        SELECT COUNT(*) as recent_conversations
        FROM chat_conversations
        WHERE created_at >= NOW() - INTERVAL '7 days'
    """
    recent = fetchone(recent_query)
    
    return {
        "total_conversations": result["total_conversations"] or 0,
        "unique_users": result["unique_users"] or 0,
        "total_messages": result["total_messages"] or 0,
        "user_messages": result["user_messages"] or 0,
        "assistant_messages": result["assistant_messages"] or 0,
        "avg_messages_per_conversation": float(result["avg_messages_per_conversation"] or 0),
        "recent_conversations": recent["recent_conversations"] or 0
    }


# ========== User Feedback Management ==========

def create_feedback(
    user_id: str,
    feedback_text: str,
    category: str
) -> Dict[str, Any]:
    """
    Create a new feedback submission.
    
    Args:
        user_id: User's Cognito UUID
        feedback_text: The feedback content
        category: Type of feedback ('feedback', 'bug', 'accessibility', 'styling')
    
    Returns:
        Feedback record with all fields
    """
    query = """
        INSERT INTO user_feedback (user_id, feedback_text, category)
        VALUES (%s, %s, %s)
        RETURNING id, user_id, feedback_text, category, status, priority, 
                  submitted_at, updated_at
    """
    return fetchone(query, (user_id, feedback_text, category))


def get_all_feedback(
    status: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Get all feedback submissions with optional filters.
    Includes user information.
    
    Args:
        status: Filter by status
        category: Filter by category
        priority: Filter by priority
        limit: Maximum number of results
        offset: Pagination offset
    
    Returns:
        List of feedback records with user email and display name
    """
    conditions = []
    params = []
    
    if status:
        conditions.append("f.status = %s")
        params.append(status)
    
    if category:
        conditions.append("f.category = %s")
        params.append(category)
    
    if priority:
        conditions.append("f.priority = %s")
        params.append(priority)
    
    where_clause = " AND " + " AND ".join(conditions) if conditions else ""
    
    query = f"""
        SELECT 
            f.id, f.user_id, f.feedback_text, f.category, f.status, f.priority,
            f.submitted_at, f.updated_at,
            u.email as user_email,
            u.display_name as user_display_name
        FROM user_feedback f
        JOIN app_users u ON f.user_id = u.id
        WHERE 1=1{where_clause}
        ORDER BY f.submitted_at DESC
        LIMIT %s OFFSET %s
    """
    
    params.extend([limit, offset])
    return fetchall(query, tuple(params))


def get_feedback_by_id(feedback_id: int) -> Optional[Dict[str, Any]]:
    """
    Get a specific feedback submission by ID.
    
    Args:
        feedback_id: Feedback record ID
    
    Returns:
        Feedback record with user information, or None if not found
    """
    query = """
        SELECT 
            f.id, f.user_id, f.feedback_text, f.category, f.status, f.priority,
            f.submitted_at, f.updated_at,
            u.email as user_email,
            u.display_name as user_display_name
        FROM user_feedback f
        JOIN app_users u ON f.user_id = u.id
        WHERE f.id = %s
    """
    return fetchone(query, (feedback_id,))


def get_user_feedback(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get all feedback submissions by a specific user.
    
    Args:
        user_id: User's Cognito UUID
        limit: Maximum number of results
    
    Returns:
        List of user's feedback records
    """
    query = """
        SELECT 
            id, user_id, feedback_text, category, status, priority,
            submitted_at, updated_at
        FROM user_feedback
        WHERE user_id = %s
        ORDER BY submitted_at DESC
        LIMIT %s
    """
    return fetchall(query, (user_id, limit))


def update_feedback_status(
    feedback_id: int,
    status: str,
    priority: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Update feedback status and optionally priority (admin function).
    
    Args:
        feedback_id: Feedback record ID
        status: New status ('open', 'closed', 'in_progress', 'paused')
        priority: Optional new priority ('low', 'medium', 'high', 'urgent')
    
    Returns:
        Updated feedback record, or None if not found
    """
    if priority:
        query = """
            UPDATE user_feedback
            SET status = %s, priority = %s
            WHERE id = %s
            RETURNING id, user_id, feedback_text, category, status, priority,
                      submitted_at, updated_at
        """
        return fetchone(query, (status, priority, feedback_id))
    else:
        query = """
            UPDATE user_feedback
            SET status = %s
            WHERE id = %s
            RETURNING id, user_id, feedback_text, category, status, priority,
                      submitted_at, updated_at
        """
        return fetchone(query, (status, feedback_id))


def delete_feedback(feedback_id: int) -> int:
    """
    Delete a feedback submission.
    
    Args:
        feedback_id: Feedback record ID
    
    Returns:
        Number of rows deleted (0 or 1)
    """
    query = "DELETE FROM user_feedback WHERE id = %s"
    return execute(query, (feedback_id,))


def get_feedback_statistics() -> Dict[str, Any]:
    """
    Get overall feedback statistics for admin dashboard.
    
    Returns:
        Dict with various statistics
    """
    query = """
        SELECT 
            COUNT(*) as total_feedback,
            COUNT(DISTINCT user_id) as unique_users,
            COUNT(CASE WHEN status = 'open' THEN 1 END) as open_count,
            COUNT(CASE WHEN status = 'in_progress' THEN 1 END) as in_progress_count,
            COUNT(CASE WHEN status = 'paused' THEN 1 END) as paused_count,
            COUNT(CASE WHEN status = 'closed' THEN 1 END) as closed_count,
            COUNT(CASE WHEN category = 'bug' THEN 1 END) as bug_count,
            COUNT(CASE WHEN category = 'accessibility' THEN 1 END) as accessibility_count,
            COUNT(CASE WHEN category = 'styling' THEN 1 END) as styling_count,
            COUNT(CASE WHEN category = 'feedback' THEN 1 END) as general_feedback_count,
            COUNT(CASE WHEN priority = 'urgent' THEN 1 END) as urgent_count,
            COUNT(CASE WHEN priority = 'high' THEN 1 END) as high_count
        FROM user_feedback
    """
    result = fetchone(query)
    
    # Get recent submissions (last 7 days)
    recent_query = """
        SELECT COUNT(*) as recent_submissions
        FROM user_feedback
        WHERE submitted_at >= NOW() - INTERVAL '7 days'
    """
    recent = fetchone(recent_query)
    
    return {
        "total_feedback": result["total_feedback"] or 0,
        "unique_users": result["unique_users"] or 0,
        "open_count": result["open_count"] or 0,
        "in_progress_count": result["in_progress_count"] or 0,
        "paused_count": result["paused_count"] or 0,
        "closed_count": result["closed_count"] or 0,
        "bug_count": result["bug_count"] or 0,
        "accessibility_count": result["accessibility_count"] or 0,
        "styling_count": result["styling_count"] or 0,
        "general_feedback_count": result["general_feedback_count"] or 0,
        "urgent_count": result["urgent_count"] or 0,
        "high_count": result["high_count"] or 0,
        "recent_submissions": recent["recent_submissions"] or 0
    }

