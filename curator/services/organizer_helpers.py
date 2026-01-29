"""
Optimized Topic Organizer Helper Methods

Contains helper methods for the algorithmic inference optimization.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import redis
from neo4j_client.models import Topic


def get_unorganized_topics_query() -> tuple[str, dict]:
    """
    Generate Cypher query to get topics needing organization.
    
    Criteria:
    - No outgoing ENCOMPASSES relationships (not yet categorized as parent)
    - No incoming ENCOMPASSES relationships (not yet has a parent)
    - Created within last week (or never organized)
    
    Returns:
        Tuple of (query_string, parameters)
    """
    query = """
    MATCH (t:Topic)
    WHERE NOT (t)-[:ENCOMPASSES]->()
      AND NOT ()-[:ENCOMPASSES]->(t)
    RETURN t
    ORDER BY t.created_at DESC
    LIMIT 1000
    """
    
    return query, {}


def should_run_llm_review(redis_client: redis.Redis) -> bool:
    """
    Determine if LLM review should run now.
    
    Strategy:
    - Once per day (configurable interval)
    - Only if there are relationships queued for review
    
    Args:
        redis_client: Redis client for checking state
        
    Returns:
        True if LLM review should run
    """
    try:
        # Check last review time
        last_review_str = redis_client.get('curator:last_llm_review')
        if last_review_str:
            last_review = datetime.fromisoformat(last_review_str)
            hours_since = (datetime.now() - last_review).total_seconds() / 3600
            
            from settings import settings
            if hours_since < settings.llm_review_interval_hours:
                return False
        
        # Check if there are items to review
        queue_size = redis_client.llen('curator:pending_reviews')
        if queue_size > 0:
            return True
        
        return False
        
    except Exception:
        # If Redis fails, don't run LLM review
        return False


def mark_llm_review_complete(redis_client: redis.Redis):
    """Mark that LLM review has completed."""
    try:
        redis_client.set('curator:last_llm_review', datetime.now().isoformat())
    except Exception:
        pass


def validate_relationship_basic(
    rel: Dict[str, Any],
    all_topics: List[Dict[str, Any]]
) -> bool:
    """
    Basic validation that relationship references exist.
    
    Args:
        rel: Relationship dict with source_topic_id and target_topic_id
        all_topics: List of all topic dicts
        
    Returns:
        True if valid
    """
    topic_ids = {t["topic_id"] for t in all_topics}
    
    source_id = rel.get("source_topic_id")
    target_id = rel.get("target_topic_id")
    
    if source_id not in topic_ids:
        return False
    
    if target_id not in topic_ids:
        return False
    
    if source_id == target_id:
        return False
    
    return True
