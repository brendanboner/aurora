"""Personalization service for Oracle queries.

This service handles:
1. Fetching user preferences from PostgreSQL
2. Auto-detection logic for when to personalize
3. Building user context for answer tailoring
"""

import logging
from dataclasses import dataclass
from typing import Optional
import psycopg2
import psycopg2.extras

from src.settings import settings
from src.models.request import PersonalizeMode
from src.models.response import QueryIntent

logger = logging.getLogger(__name__)

# PostgreSQL connection
_pg_conn = None


def _get_pg_conn():
    """Get PostgreSQL connection (singleton)."""
    global _pg_conn
    if _pg_conn is None or _pg_conn.closed:
        dsn = f"postgresql://{settings.postgres_user}:{settings.postgres_password}@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
        _pg_conn = psycopg2.connect(dsn)
        _pg_conn.autocommit = True
    return _pg_conn


def _fetchone(query: str, params: tuple = None) -> Optional[dict]:
    """Execute query and fetch one result."""
    conn = _get_pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or ())
            return cur.fetchone()
    except psycopg2.Error as e:
        logger.error(f"PostgreSQL error: {e}")
        # Try to reconnect on next call
        global _pg_conn
        _pg_conn = None
        return None


def _fetchall(query: str, params: tuple = None) -> list[dict]:
    """Execute query and fetch all results."""
    conn = _get_pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or ())
            return cur.fetchall()
    except psycopg2.Error as e:
        logger.error(f"PostgreSQL error: {e}")
        # Try to reconnect on next call
        global _pg_conn
        _pg_conn = None
        return []


def _get_popular_people(people_list: list[str], limit: int = 10) -> list[str]:
    """Sort people by popularity (follower count) and return top N.
    
    Popularity is determined from follower counts stored in the
    ``user_preferences`` table. If the underlying database query fails
    or returns no popularity data for the given people, this function
    falls back to returning the first ``limit`` entries from the original
    ``people_list`` in their existing order.
    
    Args:
        people_list: List of people to sort.
        limit: Maximum number of people to return.
        
    Returns:
        List of people names ordered by popularity when available; if
        no popularity data is available or the query fails, returns the
        first ``limit`` people from the original list.
    """
    if not people_list:
        return []
    
    # Query to count how many users follow each person
    # Uses unnest to expand the people array and count occurrences
    query = """
        SELECT person_name, COUNT(*) as follower_count
        FROM (
            SELECT unnest(people) as person_name
            FROM user_preferences
            WHERE people IS NOT NULL AND array_length(people, 1) > 0
        ) AS all_people
        WHERE person_name = ANY(%s)
        GROUP BY person_name
        ORDER BY follower_count DESC, person_name ASC
        LIMIT %s
    """
    
    results = _fetchall(query, (people_list, limit))
    
    if not results:
        # If query fails or no data, just return first N from list
        return people_list[:limit]
    
    # Extract sorted person names
    popular = [row['person_name'] for row in results]
    
    # If we got fewer results than limit, add remaining people from original list
    if len(popular) < limit:
        remaining = [p for p in people_list if p not in popular]
        popular.extend(remaining[:limit - len(popular)])
    
    return popular


@dataclass
class UserPreferences:
    """User preferences from PostgreSQL."""
    user_id: str
    topics: list[str]
    organisations: list[str]
    people: list[str]
    domains: list[str] = None

    def __post_init__(self):
        if self.domains is None:
            self.domains = []

    def is_empty(self) -> bool:
        """Check if user has any preferences set."""
        return not (self.topics or self.organisations or self.people or self.domains)


@dataclass
class UserContext:
    """User context for answer personalization."""
    topics: list[str]
    organisations: list[str]
    people: list[str]
    joined_workgroups: list[str] = None  # Display names of joined WBA workgroups

    def to_prompt_section(self) -> str:
        """Format user context for inclusion in LLM prompt."""
        parts = []

        if self.topics:
            parts.append(f"- Their areas of interest: {', '.join(self.topics)}")
        if self.organisations:
            parts.append(f"- Organizations they follow: {', '.join(self.organisations)}")
        if self.people:
            popular_people = _get_popular_people(self.people, limit=10)
            parts.append(f"- People they track: {', '.join(popular_people)}")
        if self.joined_workgroups:
            parts.append(f"- WBA workgroups they belong to: {', '.join(self.joined_workgroups)}")

        if not parts:
            return ""

        return "\n".join(parts)


@dataclass 
class PersonalizationDecision:
    """Result of personalization decision."""
    should_personalize: bool
    user_context: Optional[UserContext]
    reason: str


async def get_user_preferences(user_id: str) -> UserPreferences:
    """Fetch user preferences from PostgreSQL.
    
    Args:
        user_id: Cognito user UUID
        
    Returns:
        UserPreferences with topics, orgs, people, domains (may be empty)
    """
    query = "SELECT topics, organisations, people, domains FROM user_preferences WHERE user_id = %s"
    result = _fetchone(query, (user_id,))
    
    if not result:
        logger.debug(f"No preferences found for user {user_id}")
        return UserPreferences(
            user_id=user_id,
            topics=[],
            organisations=[],
            people=[],
            domains=[]
        )
    
    return UserPreferences(
        user_id=user_id,
        topics=result.get("topics") or [],
        organisations=result.get("organisations") or [],
        people=result.get("people") or [],
        domains=result.get("domains") or []
    )


def _has_explicit_entities(parsed_topics: list[str], parsed_orgs: list[str], parsed_people: list[str]) -> bool:
    """Check if query has explicit entity mentions."""
    return bool(parsed_topics or parsed_orgs or parsed_people)


def _topics_overlap_with_preferences(
    parsed_topics: list[str], 
    user_topics: list[str]
) -> bool:
    """Check if query topics overlap with user's preferred topics."""
    if not parsed_topics or not user_topics:
        return False
    
    # Normalize for comparison (lowercase)
    parsed_lower = {t.lower() for t in parsed_topics}
    user_lower = {t.lower() for t in user_topics}
    
    return bool(parsed_lower & user_lower)


def _is_document_lookup_query(intent: QueryIntent, query: str) -> bool:
    """Detect if query is looking for a specific document."""
    # Document lookup signals
    doc_keywords = [
        "show me", "find me", "get me", "where is", "link to",
        "meeting minutes", "presentation", "document", "report",
        "whitepaper", "spec", "specification", "pdf"
    ]
    
    query_lower = query.lower()
    return any(kw in query_lower for kw in doc_keywords)


def _is_learning_new_area(
    parsed_topics: list[str],
    user_topics: list[str],
    intent: QueryIntent
) -> bool:
    """Detect if user is exploring outside their expertise."""
    if not parsed_topics:
        return False
    
    if not user_topics:
        # No preferences = can't determine expertise
        return False
    
    # If query topics don't overlap with user preferences, they're exploring
    if not _topics_overlap_with_preferences(parsed_topics, user_topics):
        return True
    
    return False


async def decide_personalization(
    mode: PersonalizeMode,
    user_id: str,
    question: str,
    intent: QueryIntent,
    parsed_topics: list[str],
    parsed_orgs: list[str],
    parsed_people: list[str]
) -> PersonalizationDecision:
    """Decide whether to personalize and build user context.
    
    Args:
        mode: Personalization mode (off/on/auto)
        user_id: User's Cognito UUID
        question: Original question text
        intent: Classified query intent
        parsed_topics: Topics extracted from query
        parsed_orgs: Organizations extracted from query
        parsed_people: People extracted from query
        
    Returns:
        PersonalizationDecision with decision and optional user context
    """
    logger.info(f"Personalization decision: mode={mode.value}, user={user_id}, intent={intent.value}, topics={parsed_topics}, orgs={parsed_orgs}")
    
    # Mode: OFF - never personalize
    if mode == PersonalizeMode.OFF:
        logger.info(f"Personalization decision: OFF (mode disabled)")
        return PersonalizationDecision(
            should_personalize=False,
            user_context=None,
            reason="personalization_disabled"
        )
    
    # Fetch user preferences (needed for both ON and AUTO)
    preferences = await get_user_preferences(user_id)
    
    # No preferences = can't personalize
    if preferences.is_empty():
        logger.info(f"Personalization decision: OFF (no user preferences)")
        return PersonalizationDecision(
            should_personalize=False,
            user_context=None,
            reason="no_preferences"
        )
    
    logger.info(f"User preferences: topics={preferences.topics[:5] if preferences.topics else []}, orgs={preferences.organisations[:3] if preferences.organisations else []}")
    
    user_context = UserContext(
        topics=preferences.topics,
        organisations=preferences.organisations,
        people=preferences.people
    )
    
    # Mode: ON - always personalize (if user has preferences)
    if mode == PersonalizeMode.ON:
        logger.info(f"Personalization decision: ON (mode enabled)")
        return PersonalizationDecision(
            should_personalize=True,
            user_context=user_context,
            reason="personalization_enabled"
        )
    
    # Mode: AUTO - decide based on query analysis
    logger.info(f"Personalization AUTO mode - analyzing query...")
    
    # Rule 1: Document lookups don't need personalization
    if _is_document_lookup_query(intent, question):
        logger.info(f"Personalization decision: OFF (document lookup query)")
        return PersonalizationDecision(
            should_personalize=False,
            user_context=None,
            reason="document_lookup"
        )
    
    # Rule 2: Open-ended queries (trend/discovery) ALWAYS benefit from personalization
    # Even for new topics, framing the answer in context of user's interests helps
    if intent in [QueryIntent.TOPIC_DISCOVERY, QueryIntent.TREND_ANALYSIS]:
        logger.info(f"Personalization decision: ON (open-ended {intent.value} query)")
        return PersonalizationDecision(
            should_personalize=True,
            user_context=user_context,
            reason="open_ended_query"
        )
    
    # Rule 3: Explicit entities in query - depends on context
    has_entities = _has_explicit_entities(parsed_topics, parsed_orgs, parsed_people)
    logger.info(f"Query has explicit entities: {has_entities}")
    
    if has_entities:
        # If topics overlap with preferences, definitely personalize
        topics_overlap = _topics_overlap_with_preferences(parsed_topics, preferences.topics)
        logger.info(f"Topics overlap with preferences: {topics_overlap}")
        
        if topics_overlap:
            logger.info(f"Personalization decision: ON (topic overlap with preferences)")
            return PersonalizationDecision(
                should_personalize=True,
                user_context=user_context,
                reason="topic_overlap"
            )
        
        # For ENTITY_FOCUSED queries outside their expertise, don't bias the results
        # (e.g., "What is company X's revenue?" - they want facts, not framing)
        if intent == QueryIntent.ENTITY_FOCUSED:
            if _is_learning_new_area(parsed_topics, preferences.topics, intent):
                logger.info(f"Personalization decision: OFF (entity-focused query in new area)")
                return PersonalizationDecision(
                    should_personalize=False,
                    user_context=None,
                    reason="entity_focused_new_area"
                )
        
        # For other intents with explicit entities, light personalization helps
        logger.info(f"Personalization decision: ON (explicit entities with context)")
        return PersonalizationDecision(
            should_personalize=True,
            user_context=user_context,
            reason="explicit_entities_with_context"
        )
    
    # Default: personalize for better relevance
    logger.info(f"Personalization decision: ON (default - better relevance)")
    return PersonalizationDecision(
        should_personalize=True,
        user_context=user_context,
        reason="default_personalize"
    )


# ========== User Source Memberships ==========

def get_user_source_memberships(user_id: str) -> dict:
    """
    Fetch user source membership preferences from PostgreSQL.

    Returns:
        Dict with 'joined' (boosted) and 'ignored' (hard-excluded) datasource_id lists.
        Both lists are empty if no preferences are set (default behaviour).
    """
    query = "SELECT datasource_id, status FROM user_source_memberships WHERE user_id = %s"
    rows = _fetchall(query, (user_id,))
    joined = [r["datasource_id"] for r in rows if r["status"] == "joined"]
    ignored = [r["datasource_id"] for r in rows if r["status"] == "ignored"]
    logger.debug(f"Source memberships for {user_id}: joined={joined}, ignored={ignored}")
    return {"joined": joined, "ignored": ignored}
