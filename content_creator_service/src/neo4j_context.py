"""Helpers for retrieving contextual knowledge from Neo4j."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Dict, List

from neo4j_client import Neo4jClient

from .settings import get_settings

logger = logging.getLogger(__name__)


class Neo4jContextGateway:
    """Read-only facade used by CreatorAgents to assemble context."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
        )
        self._settings = settings

    def fetch_recent_events(
        self,
        topics: List[str],
        organisations: List[str],
        limit: int = 15,
        window_days: Optional[int] = None,
        min_relevance_score: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return recent events/resources filtered by topics or organisations.
        
        Implements relevance scoring to prioritize articles where query topics are central:
        - Topic specificity: fewer total topics = more focused content (40% weight)
        - Query topic match rate: proportion of query topics matched (30% weight)
        - Recency: newer content scores higher (20% weight)
        - Title match: query topics in title indicate primary focus (10% weight)
        
        Filters out:
        - Resources older than window_days (default from settings)
        - Resources with relevance score below min_relevance_score (default from settings)
        - Resources with excessive topic relationships (>max_topics_per_article from settings)
        """
        topics = [topic for topic in topics if topic]
        organisations = [org for org in organisations if org]
        if not topics and not organisations:
            return []
        
        # Use settings defaults if not provided
        if window_days is None:
            window_days = self._settings.temporal_window_days_default
        if min_relevance_score is None:
            min_relevance_score = self._settings.min_relevance_score_default
        
        max_topics = self._settings.max_topics_per_article
        
        logger.debug(
            "Fetching events for topics=%s organisations=%s (limit=%s, window=%dd, min_score=%.2f, max_topics=%d)",
            topics,
            organisations,
            limit,
            window_days,
            min_relevance_score,
            max_topics,
        )
        query = """
        MATCH (r:Resource)
        WHERE (
            ($has_topics AND EXISTS {
                MATCH (r)-[:RELATES_TO]->(topic:Topic)
                WHERE toLower(topic.name) IN [x IN $topics | toLower(x)]
            }) OR
            ($has_orgs AND EXISTS {
                MATCH (r)-[:MENTIONS]->(org:Organization)
                WHERE toLower(org.name) IN [x IN $organisations | toLower(x)]
            })
        )
        // Temporal filter: only recent content within window
        AND r.publish_date >= datetime() - duration({days: $window_days})
        
        // Collect all topics and orgs for scoring
        OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
        OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
        
        WITH r, 
             collect(DISTINCT t.name) AS all_topics, 
             collect(DISTINCT o.name) AS all_organisations
        
        // Filter out generic content aggregators (configurable max_topics)
        WHERE size(all_topics) <= $max_topics
        
        // Calculate relevance score components
        WITH r, all_topics, all_organisations,
             // Topic specificity score: fewer topics = more focused (inverse normalized)
             CASE 
                WHEN size(all_topics) = 0 THEN 0.0
                WHEN size(all_topics) <= 3 THEN 1.0
                WHEN size(all_topics) <= 6 THEN 0.7
                WHEN size(all_topics) <= 10 THEN 0.4
                ELSE 0.2
             END AS specificity_score,
             
             // Query match rate: how many query topics are matched
             CASE 
                WHEN $has_topics THEN
                    toFloat(size([topic IN all_topics WHERE toLower(topic) IN [x IN $topics | toLower(x)]])) / 
                    toFloat(size($topics))
                ELSE 1.0
             END AS match_rate_score,
             
             // Recency score: exponential decay (30 days half-life)
             CASE
                WHEN r.publish_date IS NULL THEN 0.5
                ELSE exp(-duration.between(r.publish_date, datetime()).days / 30.0)
             END AS recency_score,
             
             // Title match bonus: query topics in title indicate primary focus
             CASE
                WHEN $has_topics THEN
                    toFloat(size([topic IN $topics WHERE toLower(r.title) CONTAINS toLower(topic)])) /
                    toFloat(size($topics))
                ELSE 0.0
             END AS title_match_score
        
        // Weighted relevance score
        WITH r, all_topics, all_organisations,
             (specificity_score * 0.4 + 
              match_rate_score * 0.3 + 
              recency_score * 0.2 + 
              title_match_score * 0.1) AS relevance_score
        
        // Filter by minimum relevance threshold
        WHERE relevance_score >= $min_relevance_score
        
        RETURN r.title AS title,
               r.summary AS summary,
               r.publish_date AS start_date,
               r.publish_date AS end_date,
               r.url AS url,
               COALESCE(r.importance, 'normal') AS importance,
               COALESCE(r.last_updated, r.publish_date) AS last_updated,
               all_topics AS topics,
               all_organisations AS organisations,
               relevance_score
        
        // Sort by relevance score (primary) and recency (secondary)
        ORDER BY relevance_score DESC, 
                 COALESCE(r.last_updated, r.publish_date, datetime()) DESC
        LIMIT $limit
        """
        params = {
            "topics": topics,
            "organisations": organisations,
            "has_topics": bool(topics),
            "has_orgs": bool(organisations),
            "limit": limit,
            "window_days": window_days,
            "min_relevance_score": min_relevance_score,
            "max_topics": max_topics,
        }
        results = self._client.execute_query(query, params)
        
        # Log relevance scores for monitoring
        if results:
            scores = [r.get("relevance_score", 0) for r in results]
            logger.debug(
                "Fetched %d events with relevance scores: min=%.2f, max=%.2f, avg=%.2f",
                len(results),
                min(scores),
                max(scores),
                sum(scores) / len(scores),
            )
        
        return results

    def fetch_recent_documents(
        self, 
        organisations: List[str], 
        limit: int = 20,
        window_days: Optional[int] = None,
        min_relevance_score: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent documents mentioning specific organisations.
        
        Applies similar relevance scoring as fetch_recent_events:
        - Organization specificity: fewer orgs = more focused (50% weight)
        - Recency: newer content scores higher (30% weight)
        - Title match: org names in title indicate primary focus (20% weight)
        """
        if not organisations:
            return []
        
        # Use settings defaults if not provided
        if window_days is None:
            window_days = self._settings.temporal_window_days_default
        if min_relevance_score is None:
            min_relevance_score = self._settings.min_relevance_score_default
        
        # For documents, use half the max_topics threshold (they're typically more focused)
        max_orgs = self._settings.max_topics_per_article // 2
        
        logger.debug(
            "Fetching documents for organisations=%s (limit=%s, window=%dd, min_score=%.2f, max_orgs=%d)",
            organisations,
            limit,
            window_days,
            min_relevance_score,
            max_orgs,
        )
        
        query = """
        MATCH (r:Resource)-[:MENTIONS]->(o:Organization)
        WHERE toLower(o.name) IN [x IN $orgs | toLower(x)]
        // Temporal filter
        AND r.publish_date >= datetime() - duration({days: $window_days})
        
        WITH r, collect(DISTINCT o.name) AS all_organisations
        
        // Filter out generic aggregators (configurable max_orgs)
        WHERE size(all_organisations) <= $max_orgs
        
        // Calculate relevance score
        WITH r, all_organisations,
             // Organization specificity: fewer orgs = more focused
             CASE
                WHEN size(all_organisations) = 0 THEN 0.0
                WHEN size(all_organisations) <= 2 THEN 1.0
                WHEN size(all_organisations) <= 4 THEN 0.7
                WHEN size(all_organisations) <= 6 THEN 0.4
                ELSE 0.2
             END AS specificity_score,
             
             // Recency score
             CASE
                WHEN r.publish_date IS NULL THEN 0.5
                ELSE exp(-duration.between(r.publish_date, datetime()).days / 30.0)
             END AS recency_score,
             
             // Title match bonus
             toFloat(size([org IN $orgs WHERE toLower(r.title) CONTAINS toLower(org)])) /
             toFloat(size($orgs)) AS title_match_score
        
        WITH r, all_organisations,
             (specificity_score * 0.5 + 
              recency_score * 0.3 + 
              title_match_score * 0.2) AS relevance_score
        
        WHERE relevance_score >= $min_relevance_score
        
        RETURN r.title AS title,
               r.summary AS summary,
               r.url AS url,
               r.publish_date AS publish_date,
               all_organisations AS organisations,
               relevance_score
        
        ORDER BY relevance_score DESC, r.publish_date DESC
        LIMIT $limit
        """
        
        params = {
            "orgs": organisations, 
            "limit": limit,
            "window_days": window_days,
            "min_relevance_score": min_relevance_score,
            "max_orgs": max_orgs,
        }
        
        results = self._client.execute_query(query, params)
        
        # Log relevance scores
        if results:
            scores = [r.get("relevance_score", 0) for r in results]
            logger.debug(
                "Fetched %d documents with relevance scores: min=%.2f, max=%.2f, avg=%.2f",
                len(results),
                min(scores),
                max(scores),
                sum(scores) / len(scores),
            )
        
        return results

    def fetch_recent_and_upcoming(
        self,
        topics: List[str],
        organisations: List[str],
        window_days: int = 30,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Fetch resources within a time window (past and future).
        Useful for agents with regular cadences to find both recent context and upcoming events.
        """
        topics = [topic for topic in topics if topic]
        organisations = [org for org in organisations if org]
        if not topics and not organisations:
            return []

        logger.debug(
            "Fetching events within %d-day window for topics=%s organisations=%s",
            window_days,
            topics,
            organisations,
        )
        query = """
        MATCH (r:Resource)
        WHERE (
            ($has_topics AND EXISTS {
                MATCH (r)-[:RELATES_TO]->(topic:Topic)
                WHERE toLower(topic.name) IN [x IN $topics | toLower(x)]
            }) OR
            ($has_orgs AND EXISTS {
                MATCH (r)-[:MENTIONS]->(org:Organization)
                WHERE toLower(org.name) IN [x IN $organisations | toLower(x)]
            })
        )
        AND r.publish_date >= datetime() - duration({days: $window_days})
        OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
        OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
        WITH r, collect(DISTINCT t.name) AS topics, collect(DISTINCT o.name) AS organisations
        RETURN r.title AS title,
               r.summary AS summary,
               r.publish_date AS start_date,
               r.publish_date AS end_date,
               r.url AS url,
               COALESCE(r.importance, 'normal') AS importance,
               COALESCE(r.last_updated, r.publish_date) AS last_updated,
               topics,
               organisations
        ORDER BY COALESCE(r.last_updated, r.publish_date) DESC
        LIMIT $limit
        """
        params = {
            "topics": topics,
            "organisations": organisations,
            "window_days": window_days,
            "has_topics": bool(topics),
            "has_orgs": bool(organisations),
            "limit": limit,
        }
        return self._client.execute_query(query, params)

    def fetch_adjacent_topics(
        self,
        topics: List[str],
        organisations: List[str],
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Discover adjacent/related topics when primary topics have no matches.
        Useful for exploratory content generation.
        """
        if not topics:
            return []

        logger.debug(
            "Fetching adjacent topics related to: %s (orgs: %s)",
            topics,
            organisations,
        )
        query = """
        MATCH (primary_topic:Topic)
        WHERE toLower(primary_topic.name) IN [x IN $topics | toLower(x)]
        MATCH (primary_topic)<-[:RELATES_TO]-(r:Resource)-[:RELATES_TO]->(adjacent_topic:Topic)
        WHERE NOT toLower(adjacent_topic.name) IN [x IN $topics | toLower(x)]
        OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
        WHERE o IS NULL OR toLower(o.name) IN [x IN $organisations | toLower(x)]
        WITH r, adjacent_topic, collect(DISTINCT o.name) AS organisations
        RETURN r.title AS title,
               r.summary AS summary,
               r.publish_date AS start_date,
               r.publish_date AS end_date,
               r.url AS url,
               COALESCE(r.importance, 'normal') AS importance,
               COALESCE(r.last_updated, r.publish_date) AS last_updated,
               [adjacent_topic.name] AS topics,
               organisations
        ORDER BY COALESCE(r.last_updated, r.publish_date, datetime()) DESC
        LIMIT $limit
        """
        params = {
            "topics": topics,
            "organisations": organisations,
            "limit": limit,
        }
        return self._client.execute_query(query, params)


@lru_cache(maxsize=1)
def get_context_gateway() -> Neo4jContextGateway:
    return Neo4jContextGateway()
