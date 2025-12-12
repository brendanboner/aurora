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
        """Return recent events filtered by topics or organisations."""
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
        MATCH (e:Event)
        WHERE (
            ($has_topics AND EXISTS {
                MATCH (e)-[:EVENT_DISCUSSES_TOPIC]->(topic:Topic)
                WHERE topic.name IN $topics
            }) OR
            ($has_orgs AND EXISTS {
                MATCH (e)-[:EVENT_INVOLVES_ORGANIZATION]->(org:Organization)
                WHERE org.name IN $organisations
            })
        )
        OPTIONAL MATCH (e)-[:EVENT_DISCUSSES_TOPIC]->(t:Topic)
        OPTIONAL MATCH (e)-[:EVENT_INVOLVES_ORGANIZATION]->(o:Organization)
        RETURN e.title AS title,
               e.summary AS summary,
               e.start_date AS start_date,
               e.end_date AS end_date,
               e.url AS url,
               e.importance AS importance,
               e.last_updated AS last_updated,
               collect(DISTINCT t.name) AS topics,
               collect(DISTINCT o.name) AS organisations
        ORDER BY coalesce(e.last_updated, e.start_date, datetime()) DESC
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
        MATCH (r:Resource)-[:RESOURCE_MENTIONS_ORGANIZATION]->(o:Organization)
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


@lru_cache(maxsize=1)
def get_context_gateway() -> Neo4jContextGateway:
    return Neo4jContextGateway()
