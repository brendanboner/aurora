"""Monitors Neo4j and RabbitMQ for new knowledge events."""
from __future__ import annotations

import logging
from typing import Iterable, List

from ..events import KnowledgeEvent
from ..models.agent import CreatorAgent
from ..neo4j_context import get_context_gateway

logger = logging.getLogger(__name__)


class KnowledgeMonitor:
    def __init__(self) -> None:
        self._context_gateway = get_context_gateway()

    def poll_recent_events(
        self,
        topics: Iterable[str],
        organisations: Iterable[str],
        limit: int = 10,
        window_days: int = 90,
    ) -> List[KnowledgeEvent]:
        """Poll recent events with optional temporal filtering."""
        topic_list = [topic for topic in topics if topic]
        org_list = [org for org in organisations if org]
        logger.info("Polling Neo4j: topics=%s orgs=%s limit=%d window=%dd", topic_list, org_list, limit, window_days)
        records = self._context_gateway.fetch_recent_events(
            topic_list, 
            org_list, 
            limit=limit,
            window_days=window_days,
        )
        logger.info("Neo4j returned %d records", len(records))
        events: List[KnowledgeEvent] = []
        for record in records:
            events.append(
                KnowledgeEvent(
                    event_type="neo4j_event",
                    external_id=(record.get("url") or record.get("title") or ""),
                    title=record.get("title", ""),
                    summary=record.get("summary", ""),
                    topics=record.get("topics", []),
                    organisations=record.get("organisations", []),
                    published_at=record.get("start_date"),
                    importance=record.get("importance") or "normal",
                )
            )
        return events

    def collect_for_agent(self, agent: CreatorAgent, limit: int = 10) -> List[KnowledgeEvent]:
        """Collect contextual events for an agent with intelligent filtering."""
        logger.info(
            "Collecting events for agent %s: topics=%s orgs=%s limit=%d",
            agent.name,
            agent.expertise_topics,
            agent.expertise_organisations,
            limit,
        )

        # Determine time window based on posting cadence
        window_days = self._get_time_window_for_cadence(agent.posting_cadence)
        logger.info("Using %d-day window for agent %s (cadence: %s)", 
                   window_days, agent.name, agent.posting_cadence)

        # Try primary topics first
        events = self._fetch_with_temporal_filtering(
            topics=agent.expertise_topics,
            organisations=agent.expertise_organisations,
            window_days=window_days,
            limit=limit,
        )
        logger.info("Found %d primary events for agent %s", len(events), agent.name)

        # If no events found and agent has low discovery tolerance, try adjacent topics
        if not events and agent.expertise_topics:
            logger.info("No primary events found; trying adjacent topics for agent %s", agent.name)
            adjacent_events = self._fetch_adjacent_topic_events(
                topics=agent.expertise_topics,
                organisations=agent.expertise_organisations,
                limit=limit,
            )
            logger.info("Found %d adjacent topic events for agent %s", len(adjacent_events), agent.name)
            events.extend(adjacent_events)

        # Log event details for debugging
        for i, event in enumerate(events[:5]):  # Log first 5 events
            logger.debug("Event %d: title='%s', topics=%s, orgs=%s, importance=%s", 
                        i, event.title[:50] if event.title else "No title", 
                        event.topics, event.organisations, 
                        getattr(event, 'importance', 'unknown'))

        return events

    def _get_time_window_for_cadence(self, posting_cadence: str) -> int:
        """Map agent cadence to Neo4j time window in days."""
        cadence_windows = {
            "per-event": 7,          # React to events within past week
            "daily": 1,              # Fresh daily content
            "weekly": 7,             # Weekly review
            "biweekly": 14,          # Two-week lookback
            "monthly": 30,           # Monthly digest
            "quarterly": 90,         # Quarterly review
        }
        return cadence_windows.get(posting_cadence, 7)

    def _fetch_with_temporal_filtering(
        self,
        topics: List[str],
        organisations: List[str],
        window_days: int = 7,
        limit: int = 10,
    ) -> List[KnowledgeEvent]:
        """Fetch events within a temporal window."""
        topic_list = [topic for topic in topics if topic]
        org_list = [org for org in organisations if org]

        if not topic_list and not org_list:
            return []

        logger.debug(
            "Fetching events within %d-day window: topics=%s orgs=%s",
            window_days,
            topic_list,
            org_list,
        )

        logger.info("Making Neo4j query for agent with topics=%s, orgs=%s, window_days=%d, limit=%d", 
                   topic_list, org_list, window_days, limit)
        
        records = self._context_gateway.fetch_recent_and_upcoming(
            topics=topic_list,
            organisations=org_list,
            window_days=window_days,
            limit=limit,
        )
        logger.info("Neo4j query returned %d records", len(records))

        events: List[KnowledgeEvent] = []
        for record in records:
            events.append(
                KnowledgeEvent(
                    event_type="neo4j_event",
                    external_id=(record.get("url") or record.get("title") or ""),
                    title=record.get("title", ""),
                    summary=record.get("summary", ""),
                    topics=record.get("topics", []),
                    organisations=record.get("organisations", []),
                    published_at=record.get("start_date"),
                    importance=record.get("importance") or "normal",
                )
            )
        return events

    def _fetch_adjacent_topic_events(
        self,
        topics: List[str],
        organisations: List[str],
        limit: int = 10,
    ) -> List[KnowledgeEvent]:
        """Discover adjacent topics when primary topics are exhausted."""
        topic_list = [topic for topic in topics if topic]
        org_list = [org for org in organisations if org]

        if not topic_list:
            return []

        logger.debug("Fetching adjacent topics: primary=%s orgs=%s", topic_list, org_list)

        records = self._context_gateway.fetch_adjacent_topics(
            topics=topic_list,
            organisations=org_list,
            limit=limit,
        )
        logger.info("Adjacent topic fetch returned %d records", len(records))

        events: List[KnowledgeEvent] = []
        for record in records:
            events.append(
                KnowledgeEvent(
                    event_type="neo4j_event",
                    external_id=(record.get("url") or record.get("title") or ""),
                    title=record.get("title", ""),
                    summary=record.get("summary", ""),
                    topics=record.get("topics", []),
                    organisations=record.get("organisations", []),
                    published_at=record.get("start_date"),
                    importance=record.get("importance") or "normal",
                )
            )
        return events
