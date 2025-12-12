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

    def fetch_recent_events(
        self,
        topics: List[str],
        organisations: List[str],
        limit: int = 15,
    ) -> List[Dict[str, Any]]:
        """Return recent events/resources filtered by topics or organisations."""
        topics = [topic for topic in topics if topic]
        organisations = [org for org in organisations if org]
        if not topics and not organisations:
            return []
        logger.debug(
            "Fetching events for topics=%s organisations=%s (limit=%s)",
            topics,
            organisations,
            limit,
        )
        query = """
        MATCH (r:Resource)
        WHERE (
            ($has_topics AND EXISTS {
                MATCH (r)-[:RELATES_TO]->(topic:Topic)
                WHERE topic.name IN $topics
            }) OR
            ($has_orgs AND EXISTS {
                MATCH (r)-[:MENTIONS]->(org:Organization)
                WHERE org.name IN $organisations
            })
        )
        OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
        OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
        RETURN r.title AS title,
               r.summary AS summary,
               r.publish_date AS start_date,
               r.publish_date AS end_date,
               r.url AS url,
               COALESCE(r.importance, 'normal') AS importance,
               COALESCE(r.last_updated, r.publish_date) AS last_updated,
               collect(DISTINCT t.name) AS topics,
               collect(DISTINCT o.name) AS organisations
        ORDER BY COALESCE(r.last_updated, r.publish_date, datetime()) DESC
        LIMIT $limit
        """
        params = {
            "topics": topics,
            "organisations": organisations,
            "has_topics": bool(topics),
            "has_orgs": bool(organisations),
            "limit": limit,
        }
        return self._client.execute_query(query, params)

    def fetch_recent_documents(self, organisations: List[str], limit: int = 20) -> List[Dict[str, Any]]:
        if not organisations:
            return []
        query = """
        MATCH (r:Resource)-[:MENTIONS]->(o:Organization)
        WHERE o.name IN $orgs
        RETURN r.title AS title,
               r.summary AS summary,
               r.url AS url,
               r.publish_date AS publish_date,
               collect(DISTINCT o.name) AS organisations
        ORDER BY r.publish_date DESC
        LIMIT $limit
        """
        return self._client.execute_query(query, {"orgs": organisations, "limit": limit})

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
                WHERE topic.name IN $topics
            }) OR
            ($has_orgs AND EXISTS {
                MATCH (r)-[:MENTIONS]->(org:Organization)
                WHERE org.name IN $organisations
            })
        )
        AND r.publish_date >= datetime() - duration({days: $window_days})
        OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
        OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
        RETURN r.title AS title,
               r.summary AS summary,
               r.publish_date AS start_date,
               r.publish_date AS end_date,
               r.url AS url,
               COALESCE(r.importance, 'normal') AS importance,
               COALESCE(r.last_updated, r.publish_date) AS last_updated,
               collect(DISTINCT t.name) AS topics,
               collect(DISTINCT o.name) AS organisations
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
        WHERE primary_topic.name IN $topics
        MATCH (primary_topic)<-[:RELATES_TO]-(r:Resource)-[:RELATES_TO]->(adjacent_topic:Topic)
        WHERE adjacent_topic.name NOT IN $topics
        OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
        WHERE NOT ($has_orgs) OR o.name IN $organisations
        RETURN DISTINCT
               r.title AS title,
               r.summary AS summary,
               r.publish_date AS start_date,
               r.publish_date AS end_date,
               r.url AS url,
               COALESCE(r.importance, 'normal') AS importance,
               COALESCE(r.last_updated, r.publish_date) AS last_updated,
               [adjacent_topic.name] AS topics,
               collect(DISTINCT o.name) AS organisations
        ORDER BY COALESCE(r.last_updated, r.publish_date, datetime()) DESC
        LIMIT $limit
        """
        params = {
            "topics": topics,
            "organisations": organisations,
            "has_orgs": bool(organisations),
            "limit": limit,
        }
        return self._client.execute_query(query, params)


@lru_cache(maxsize=1)
def get_context_gateway() -> Neo4jContextGateway:
    return Neo4jContextGateway()
