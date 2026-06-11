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

# Umbrella DataSources whose contents we want every new user to see in the
# unboosted retrieval path. Joining the parent fans out to all children via
# the workgroup filter (`ds.datasource_id IN $workgroups OR
# ds.parent_datasource_id IN $workgroups`).
#
# Kept small and parent-only — children carry the actual scrape config and
# new ones land under these parents automatically. Power users can still
# tweak via Settings → Workgroups.
DEFAULT_JOINED_DATASOURCES: List[str] = [
    "wfa",
    "wba_extranet",
    "techfieldday",
]


def seed_default_source_memberships(user_id: str) -> int:
    """Add `joined` rows for our default umbrella DataSources.

    Idempotent — uses ON CONFLICT DO NOTHING so re-running is safe and any
    existing user choices (joined or ignored) are preserved.
    """
    if not DEFAULT_JOINED_DATASOURCES:
        return 0
    placeholders = ", ".join(["(%s, %s, 'joined')"] * len(DEFAULT_JOINED_DATASOURCES))
    params: List[Any] = []
    for ds_id in DEFAULT_JOINED_DATASOURCES:
        params.extend([user_id, ds_id])
    query = f"""
        INSERT INTO user_source_memberships (user_id, datasource_id, status)
        VALUES {placeholders}
        ON CONFLICT (user_id, datasource_id) DO NOTHING
    """
    try:
        return execute(query, params)
    except Exception as exc:
        # FK violation here means the user row isn't there yet — caller
        # should arrange ordering. Anything else (table missing during early
        # migration) is logged and swallowed; defaults are best-effort.
        logger.warning(f"Failed to seed default source memberships for {user_id}: {exc}")
        return 0

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
        user = fetchone(query, (user_id, email, display_name))
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

    # Best-effort: give new users a starter set of "joined" umbrella sources
    # so unboosted retrieval surfaces WFA/WBA/TFD content out of the box.
    try:
        seed_default_source_memberships(user_id)
    except Exception as seed_err:
        logger.warning(f"Default source memberships seed failed for {user_id}: {seed_err}")

    return user

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
            # FK constraints in PostgreSQL are IMMEDIATE by default: changing app_users.id
            # while child rows still reference the old ID raises ForeignKeyViolation instantly.
            #
            # Fix: INSERT new row first (both IDs exist) → update children → delete old row.
            # This keeps FK constraints satisfied at every step.

            # 1. Verify old user exists
            cur.execute(
                "SELECT id, email, display_name, created_at FROM app_users WHERE id = %s AND email = %s",
                (old_id, email)
            )
            old_user = cur.fetchone()
            if not old_user:
                raise ValueError(f"Failed to migrate user {old_id} — not found or email mismatch")

            # 2. Insert new row with the SSO/new ID (both old and new now exist in app_users)
            cur.execute(
                """
                INSERT INTO app_users (id, email, display_name, created_at, updated_at)
                VALUES (%s, %s, COALESCE(%s, %s), %s, NOW())
                ON CONFLICT (id) DO UPDATE
                  SET email = EXCLUDED.email,
                      display_name = COALESCE(EXCLUDED.display_name, app_users.display_name),
                      updated_at = NOW()
                RETURNING id, email, display_name, created_at, updated_at
                """,
                (new_id, email, display_name, old_user['display_name'], old_user['created_at'])
            )
            user = cur.fetchone()
            
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
            cur.execute(
                "UPDATE post SET user_id = %s WHERE user_id = %s",
                (new_id, old_id)
            )
            cur.execute(
                "UPDATE post_comment SET user_id = %s WHERE user_id = %s",
                (new_id, old_id)
            )

            # Additional backend tables missing from original migration
            cur.execute(
                "UPDATE user_source_preferences SET user_id = %s WHERE user_id = %s",
                (new_id, old_id)
            )
            cur.execute(
                "UPDATE oracle_query_history SET user_id = %s WHERE user_id = %s",
                (new_id, old_id)
            )
            # Teams conversation references use aurora_user_id, not user_id
            cur.execute(
                "UPDATE teams_conversation_references SET aurora_user_id = %s WHERE aurora_user_id = %s",
                (new_id, old_id)
            )

            # 3. Delete the old app_users row — all children now reference new_id so no FK violation
            cur.execute("DELETE FROM app_users WHERE id = %s", (old_id,))

            # Commit the transaction
            conn.commit()
            logger.info(f"Successfully migrated user from {old_id} to {new_id}: "
                        f"preferences, memberships, agents, posts, query history, Teams refs all re-keyed")
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
            # User exists with a different internal ID (email-collision / SSO migration).
            # Instead of re-keying every FK (which breaks with IMMEDIATE constraints),
            # store the new SSO/Azure OID in the sso_id column so lookups resolve to
            # the existing stable ID. The user keeps their data — no FK changes needed.
            old_id = existing_user['id']
            if old_id != user_id:
                logger.info(
                    f"SSO link: storing sso_id={user_id} on existing account {old_id} "
                    f"({email}) — no ID migration required"
                )
                try:
                    execute(
                        "UPDATE app_users SET sso_id = %s, "
                        "display_name = COALESCE(%s, display_name), updated_at = NOW() "
                        "WHERE id = %s",
                        (user_id, display_name, old_id)
                    )
                except Exception as sso_err:
                    logger.warning(f"Could not set sso_id ({sso_err}), continuing with existing account")
            user = get_user_by_id(old_id)  # Re-fetch with full row
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
        # User already exists (found by id or sso_id).
        internal_id = user['id']  # may differ from user_id if found via sso_id lookup

        if user['email'] != email or (display_name and user['display_name'] != display_name):
            if internal_id != user_id:
                # Found via sso_id — update the existing row using its INTERNAL id.
                # Do NOT call create_user(user_id, ...) because user_id is the Azure OID
                # which would try to INSERT a new row and hit the email unique constraint.
                logger.info(
                    f"Updating SSO-linked user (internal_id={internal_id}, sso_id={user_id}): "
                    f"display_name={display_name}"
                )
                execute(
                    "UPDATE app_users SET display_name = COALESCE(%s, display_name), "
                    "updated_at = NOW() WHERE id = %s",
                    (display_name, internal_id)
                )
                user = get_user_by_id(internal_id)
            else:
                logger.info(
                    f"Updating user {user_id}: email {user['email']}->{email}, "
                    f"display_name {user['display_name']}->{display_name}"
                )
                user = create_user(user_id, email, display_name)

    # Always ensure user is synced to Neo4j (function checks if already synced)
    _ensure_user_in_neo4j(
        user['id'] if user else user_id,
        email,
        user.get('display_name', display_name) if user else display_name,
        given_name,
        family_name
    )
    
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


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Look up user by internal id OR by sso_id OR by aad_object_id.

    Aurora users carry up to three identifiers post-SSO migration:
      - `id`            original Cognito UUID (FK target — stable)
      - `sso_id`        Cognito-issued sub claim on the SSO-federated login
      - `aad_object_id` Microsoft Graph Object ID (what Teams sends as activity.from.aadObjectId)

    All three resolve to the same row so any token format the front-of-stack
    happens to carry (web SSO / Teams bot) finds the same account.
    """
    query = (
        "SELECT * FROM app_users "
        "WHERE id = %s OR sso_id = %s OR aad_object_id = %s"
    )
    return fetchone(query, (user_id, user_id, user_id))


def get_user_by_aad_object_id(aad_object_id: str) -> Optional[Dict[str, Any]]:
    """Look up the Aurora account associated with a Microsoft Graph Object ID.

    Used by the Teams bot when activity.from.aadObjectId is the only identity
    signal available. Falls back to None if no user has claimed this OID; the
    bot is then responsible for the synthetic-account flow.
    """
    query = "SELECT * FROM app_users WHERE aad_object_id = %s"
    return fetchone(query, (aad_object_id,))


def set_user_aad_object_id(user_id: str, aad_object_id: str) -> None:
    """Auto-claim: record the AAD OID on a user's row so future Teams logins
    skip Graph API and the synthetic-account fallback. No-op if already set.
    """
    execute(
        "UPDATE app_users SET aad_object_id = %s, updated_at = NOW() "
        "WHERE id = %s AND aad_object_id IS NULL",
        (aad_object_id, user_id),
    )


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

def get_user_preferences(user_id: str) -> Dict[str, Any]:
    """Get user preferences (topics, organisations, people, domains, notifications, background)."""
    query = """
        SELECT user_id, topics, organisations, people, domains,
               notify_email, notify_digest, background
        FROM user_preferences WHERE user_id = %s
    """
    result = fetchone(query, (user_id,))
    if not result:
        return {
            "user_id": user_id,
            "topics": [],
            "organisations": [],
            "people": [],
            "domains": [],
            "notify_email": True,
            "notify_digest": True,
            "background": None,
        }
    return result


def upsert_user_preferences(
    user_id: str,
    topics: Optional[List[str]] = None,
    organisations: Optional[List[str]] = None,
    people: Optional[List[str]] = None,
    domains: Optional[List[str]] = None,
    notify_email: Optional[bool] = None,
    notify_digest: Optional[bool] = None,
    background: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update user preferences (topics/orgs/people/domains/notifications/background).

    Note: `background` uses a sentinel ('' = explicit clear) since plain
    NULL would be filtered by COALESCE and never overwrite an existing
    value. Pass None to leave it unchanged.
    """
    # Convert empty string to a value the COALESCE will accept (treats '' as a clear).
    bg_param = background  # None preserves existing; '' clears; any string overwrites
    query = """
        INSERT INTO user_preferences
            (user_id, topics, organisations, people, domains, notify_email, notify_digest, background)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            topics        = COALESCE(EXCLUDED.topics,        user_preferences.topics),
            organisations = COALESCE(EXCLUDED.organisations, user_preferences.organisations),
            people        = COALESCE(EXCLUDED.people,        user_preferences.people),
            domains       = COALESCE(EXCLUDED.domains,       user_preferences.domains),
            notify_email  = COALESCE(EXCLUDED.notify_email,  user_preferences.notify_email),
            notify_digest = COALESCE(EXCLUDED.notify_digest, user_preferences.notify_digest),
            background    = COALESCE(EXCLUDED.background,    user_preferences.background),
            updated_at    = NOW()
        RETURNING user_id, topics, organisations, people, domains,
                  notify_email, notify_digest, background
    """
    params = (user_id, topics, organisations, people, domains, notify_email, notify_digest, bg_param)
    return fetchone(query, params)


# ========== User Source Preferences (weighted source boosts) ==========

def get_user_source_preferences(user_id: str) -> List[Dict[str, Any]]:
    """Return [{datasource_id, weight}, ...] for the user.

    Returns [] gracefully if migration 008 hasn't been applied yet.
    """
    query = """
        SELECT datasource_id, weight
        FROM user_source_preferences
        WHERE user_id = %s
        ORDER BY weight DESC, datasource_id
    """
    try:
        return fetchall(query, (user_id,))
    except Exception as e:
        if "user_source_preferences" in str(e):
            return []
        raise


def upsert_user_source_preference(
    user_id: str, datasource_id: str, weight: float = 1.0
) -> Dict[str, Any]:
    """Set or update a weighted source preference.

    Returns gracefully if migration 008 hasn't been applied yet.
    """
    query = """
        INSERT INTO user_source_preferences (user_id, datasource_id, weight)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, datasource_id) DO UPDATE SET
            weight     = EXCLUDED.weight,
            updated_at = NOW()
        RETURNING user_id, datasource_id, weight
    """
    try:
        return fetchone(query, (user_id, datasource_id, weight))
    except Exception as e:
        if "user_source_preferences" in str(e):
            return {"user_id": user_id, "datasource_id": datasource_id, "weight": weight}
        raise


def delete_user_source_preference(user_id: str, datasource_id: str) -> bool:
    """Remove a source preference (reverts to default weighting).

    Returns gracefully if migration 008 hasn't been applied yet.
    """
    query = """
        DELETE FROM user_source_preferences
        WHERE user_id = %s AND datasource_id = %s
        RETURNING datasource_id
    """
    try:
        result = fetchone(query, (user_id, datasource_id))
        return result is not None
    except Exception as e:
        if "user_source_preferences" in str(e):
            return False
        raise


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

