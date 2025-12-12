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
    ) -> List[KnowledgeEvent]:
        topic_list = [topic for topic in topics if topic]
        org_list = [org for org in organisations if org]
        records = self._context_gateway.fetch_recent_events(topic_list, org_list, limit=limit)
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
        return self.poll_recent_events(
            topics=agent.expertise_topics,
            organisations=agent.expertise_organisations,
            limit=limit,
        )
