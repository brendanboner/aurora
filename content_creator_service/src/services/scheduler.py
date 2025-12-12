"""Async scheduler responsible for invoking CreatorAgents."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Optional

from ..events import KnowledgeEvent
from ..models.agent import CreatorAgent
from ..settings import get_settings
from .agent_service import AgentService
from .generation_service import GenerationService
from .knowledge_monitor import KnowledgeMonitor
from .post_service import PostService

logger = logging.getLogger(__name__)


class AgentScheduler:
    def __init__(self) -> None:
        settings = get_settings()
        self._poll_interval = settings.scheduler_poll_interval_seconds
        self._per_event_cooldown = timedelta(seconds=settings.per_event_cooldown_seconds)
        self._cadence_windows = {
            "daily": timedelta(hours=23),
            "daily-digest": timedelta(hours=23),
            "weekly": timedelta(days=6),
            "weekly-digest": timedelta(days=6),
        }
        self._agent_service = AgentService()
        self._monitor = KnowledgeMonitor()
        self._generation_service = GenerationService()
        self._post_service = PostService()
        self._task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        logger.info("Starting CreatorAgent scheduler (interval=%ss)", self._poll_interval)
        self._shutdown_event.clear()
        self._task = asyncio.create_task(self._run())

    async def shutdown(self) -> None:
        if self._task is None:
            return
        logger.info("Stopping CreatorAgent scheduler")
        self._shutdown_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _run(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                await self.tick()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("Scheduler tick failed: %s", exc)
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                continue

    async def tick(self) -> None:
        """Single scheduler iteration."""
        await asyncio.to_thread(self._process_agents)

    def _process_agents(self) -> None:
        now = datetime.now(timezone.utc)
        agents = self._agent_service.list_enabled_agents()
        for agent in agents:
            try:
                self._maybe_run_agent(agent, now)
            except Exception as exc:  # pragma: no cover - log and continue
                logger.exception("Agent %s run failed: %s", agent.name, exc)

    def _maybe_run_agent(self, agent: CreatorAgent, now: datetime) -> None:
        events = self._monitor.collect_for_agent(agent, limit=5)
        event = self._select_event(agent, events)
        if event is None:
            logger.debug("Agent %s has no new events", agent.name)
            return
        if not self._event_meets_importance(agent, event):
            logger.debug("Agent %s event below importance threshold", agent.name)
            return
        if not self._should_run_agent(agent, now):
            logger.debug("Agent %s skipped due to cadence window", agent.name)
            return
        payload = self._generation_service.generate_post_payload(
            agent,
            topics=event.topics or agent.expertise_topics,
            organisations=event.organisations or agent.expertise_organisations,
        )
        if not payload:
            logger.info("Agent %s generation returned no content", agent.name)
            self._agent_service.mark_agent_run(agent.id, event_cursor=event.fingerprint(), generated=False)
            return
        body = payload.get("body") or payload.get("summary")
        if not body:
            logger.info("Agent %s produced empty body", agent.name)
            self._agent_service.mark_agent_run(agent.id, event_cursor=event.fingerprint(), generated=False)
            return
        tags = payload.get("tags") or event.topics or agent.expertise_topics
        post_id = self._post_service.create_post(
            agent_id=agent.id,
            title=payload.get("title") or event.title or f"Update from {agent.name}",
            body=body,
            summary=payload.get("summary"),
            tags=tags,
            visibility=payload.get("visibility", "public"),
            importance=payload.get("importance", agent.importance_threshold),
            content_length=payload.get("content_length", agent.content_length_preference),
            sources=payload.get("sources", []),
        )
        self._agent_service.mark_agent_run(agent.id, event_cursor=event.fingerprint(), generated=True)
        logger.info("CreatorAgent %s generated post %s", agent.name, post_id)

    def _select_event(self, agent: CreatorAgent, events: list[KnowledgeEvent]) -> Optional[KnowledgeEvent]:
        if not events:
            return None
        cursor = agent.last_event_cursor
        for event in events:
            fingerprint = event.fingerprint()
            if not fingerprint:
                continue
            if cursor != fingerprint:
                return event
        # All events already processed; allow digest cadences with first item
        if self._normalise_cadence(agent.posting_cadence) in {"daily", "daily-digest", "weekly", "weekly-digest"}:
            return events[0]
        return None

    def _should_run_agent(self, agent: CreatorAgent, now: datetime) -> bool:
        cadence = self._normalise_cadence(agent.posting_cadence)
        last_run = agent.last_run_at
        if cadence in {"per-event", "important-only"}:
            if not last_run:
                return True
            return now - last_run >= self._per_event_cooldown
        window = self._cadence_windows.get(cadence)
        if not window:
            return True
        anchor = agent.last_generated_at or agent.last_run_at
        if not anchor:
            return True
        return now - anchor >= window

    def _event_meets_importance(self, agent: CreatorAgent, event: KnowledgeEvent) -> bool:
        hierarchy = {"low": 0, "normal": 1, "important": 2, "critical": 3}
        threshold = hierarchy.get((agent.importance_threshold or "normal").lower(), 1)
        event_rank = hierarchy.get((event.importance or "normal").lower(), 1)
        return event_rank >= threshold

    def _normalise_cadence(self, cadence: Optional[str]) -> str:
        if not cadence:
            return "per-event"
        return cadence.strip().lower().replace(" ", "-")
