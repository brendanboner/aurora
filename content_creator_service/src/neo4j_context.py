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
                WHERE toLower(topic.name) IN [x IN $topics | toLower(x)]
            }) OR
            ($has_orgs AND EXISTS {
                MATCH (r)-[:MENTIONS]->(org:Organization)
                WHERE toLower(org.name) IN [x IN $organisations | toLower(x)]
            })
        )
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
        WHERE toLower(o.name) IN [x IN $orgs | toLower(x)]
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
