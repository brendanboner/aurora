"""Async scheduler responsible for invoking CreatorAgents and personal UserAgents."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Optional

try:
    from common.telemetry import get_tracer, get_meter
    tracer = get_tracer()
    meter = get_meter()
    OTEL_AVAILABLE = True
except ImportError:
    tracer = None
    meter = None
    OTEL_AVAILABLE = False

from ..events import KnowledgeEvent
from ..models.agent import CreatorAgent
from ..settings import get_settings
from .agent_service import AgentService
from .generation_service import GenerationService
from .knowledge_monitor import KnowledgeMonitor
from .post_service import PostService
from .user_agent_service import UserAgentService

logger = logging.getLogger(__name__)


# Minimum gap between runs for each cadence. Used as a floor before the
# next creation-time-aligned slot becomes eligible.
CADENCE_WINDOWS: dict[str, timedelta] = {
    "daily": timedelta(hours=23),
    "daily-digest": timedelta(hours=23),
    "weekly": timedelta(days=6),
    "weekly-digest": timedelta(days=6),
}


def compute_next_run_at(
    *,
    cadence: str,
    created_at: Optional[datetime],
    last_run: Optional[datetime],
) -> Optional[datetime]:
    """Next scheduled fire time for a daily/weekly cadence.

    Anchored to ``created_at``'s time-of-day (and weekday for weekly), so an
    agent created at 09:30 keeps posting around 09:30, instead of drifting
    earlier each day under a 23h sliding window.
    """
    window = CADENCE_WINDOWS.get(cadence)
    if window is None or created_at is None:
        return None
    created = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    if last_run is None:
        base = created
    else:
        anchor = last_run if last_run.tzinfo else last_run.replace(tzinfo=timezone.utc)
        base = anchor + window
    candidate = base.replace(
        hour=created.hour,
        minute=created.minute,
        second=0,
        microsecond=0,
    )
    if cadence in {"weekly", "weekly-digest"}:
        days_ahead = (created.weekday() - candidate.weekday()) % 7
        candidate = candidate + timedelta(days=days_ahead)
        if candidate < base:
            candidate += timedelta(days=7)
    else:
        if candidate < base:
            candidate += timedelta(days=1)
    return candidate


class AgentScheduler:
    def __init__(self) -> None:
        settings = get_settings()
        self._poll_interval = settings.scheduler_poll_interval_seconds
        self._per_event_cooldown = timedelta(seconds=settings.per_event_cooldown_seconds)
        self._cadence_windows = CADENCE_WINDOWS
        # Tolerance before the scheduled slot during which a run may fire —
        # the scheduler ticks roughly every minute, so a few minutes of slack
        # lets us hit the slot reliably without drifting.
        self._slot_tolerance = timedelta(minutes=5)
        self._agent_service = AgentService()
        self._user_agent_service = UserAgentService()
        self._monitor = KnowledgeMonitor()
        self._generation_service = GenerationService()
        self._post_service = PostService()
        self._event_sample_limit = 5
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
        """Single scheduler iteration — runs CreatorAgents and personal UserAgents."""
        await asyncio.gather(
            asyncio.to_thread(self._process_agents),
            asyncio.to_thread(self._process_user_agents),
        )

    def _process_agents(self) -> None:
        now = datetime.now(timezone.utc)
        agents = self._agent_service.list_enabled_agents()
        for agent in agents:
            try:
                self._execute_agent(agent, now)
            except Exception as exc:  # pragma: no cover - log and continue
                logger.exception("Agent %s run failed: %s", agent.name, exc)

    def run_agent_once(
        self,
        agent_id: int,
        *,
        force: bool = False,
        limit: Optional[int] = None,
    ) -> tuple[Optional[int], Optional[KnowledgeEvent]]:
        """Execute a single CreatorAgent run synchronously.

        Args:
            agent_id: Target CreatorAgent ID.
            force: When True, bypass cadence & importance checks and allow
                previously processed events.
            limit: Optional override for how many events to sample.

        Returns:
            Tuple of (post_id, event) where post_id is None if no content was generated.
        """

        agent = self._agent_service.get_agent(agent_id)
        now = datetime.now(timezone.utc)
        return self._execute_agent(
            agent,
            now,
            force=force,
            limit=limit,
            allow_repeat=force,
        )

    def _execute_agent(
        self,
        agent: CreatorAgent,
        now: datetime,
        *,
        force: bool = False,
        limit: Optional[int] = None,
        allow_repeat: bool = False,
    ) -> tuple[Optional[int], Optional[KnowledgeEvent]]:
        # Create span for agent execution
        if OTEL_AVAILABLE and tracer:
            span = tracer.start_span("agent.execution")
            span.set_attribute("agent.name", agent.name)
            span.set_attribute("agent.id", agent.id)
            execution_start = time.time()
        else:
            span = None
            execution_start = None
        
        try:
            logger.info("Starting agent execution for %s (force=%s, limit=%s)", agent.name, force, limit)
            logger.info("Agent %s config: topics=%s, orgs=%s, threshold=%s, cadence=%s, enabled=%s", 
                       agent.name, agent.expertise_topics, agent.expertise_organisations, 
                       agent.importance_threshold, agent.posting_cadence, agent.enabled)
            
            events = self._monitor.collect_for_agent(agent, limit=limit or self._event_sample_limit)
            logger.info("Collected %d events for agent %s", len(events), agent.name)
            
            event = self._select_event(agent, events, allow_repeat=allow_repeat)
            if event is None:
                logger.info("Agent %s has no new events (total events: %d, last_cursor: %s)", 
                           agent.name, len(events), agent.last_event_cursor)
                return None, None
            logger.info("Selected event for agent %s: %s (importance: %s)", 
                       agent.name, event.title[:50] if event.title else "No title", 
                       getattr(event, 'importance', 'unknown'))
            
            if not force and not self._event_meets_importance(agent, event):
                logger.info("Agent %s event below importance threshold (event: %s, threshold: %s)", 
                           agent.name, getattr(event, 'importance', 'unknown'), agent.importance_threshold)
                return None, event
            if not force and not self._should_run_agent(agent, now):
                logger.info("Agent %s skipped due to cadence window (cadence: %s, last_run: %s)", 
                           agent.name, agent.posting_cadence, agent.last_run_at)
                return None, event
            logger.info("Attempting to generate post for agent %s with topics: %s, orgs: %s", 
                       agent.name, event.topics or agent.expertise_topics, 
                       event.organisations or agent.expertise_organisations)
            
            # Determine perspective based on day of week for variety
            perspective = self._select_perspective(agent, now)
            
            payload = self._generation_service.generate_post_payload(
                agent,
                topics=event.topics or agent.expertise_topics,
                organisations=event.organisations or agent.expertise_organisations,
                perspective=perspective,
            )
            if not payload:
                logger.info("Agent %s generation returned no content - check Neo4j data and LLM connectivity", agent.name)
                self._agent_service.mark_agent_run(agent.id, event_cursor=event.fingerprint(), generated=False)
                return None, event
            body = payload.get("body") or payload.get("summary")
            if not body:
                logger.info("Agent %s produced empty body (payload keys: %s)", agent.name, list(payload.keys()))
                self._agent_service.mark_agent_run(agent.id, event_cursor=event.fingerprint(), generated=False)
                return None, event
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

            # Push to Teams if agent has a teams_slug (fire-and-forget, non-fatal)
            if getattr(agent, "teams_slug", None):
                from .teams_notifier import push_feed_update
                push_feed_update(
                    agent_slug=agent.teams_slug,
                    agent_name=agent.name,
                    post_id=post_id,
                    title=payload.get("title") or event.title or f"Update from {agent.name}",
                    summary=payload.get("summary") or "",
                    body=payload.get("body") or "",
                    tags=tags if isinstance(tags, list) else [],
                    sources=payload.get("sources") or [],
                )
            
            # Record metrics
            if OTEL_AVAILABLE and span and execution_start:
                execution_duration_ms = (time.time() - execution_start) * 1000
                span.set_attribute("agent.execution.duration_ms", execution_duration_ms)
                span.set_attribute("agent.post.generated", True)
                span.set_attribute("agent.post.id", post_id)
            
            return post_id, event
        finally:
            # End span and record metrics
            if OTEL_AVAILABLE and span and execution_start:
                execution_duration_ms = (time.time() - execution_start) * 1000
                span.end()
                
                # Record execution count
                if meter:
                    execution_counter = meter.create_counter(
                        name="agent.execution.count",
                        description="Number of agent executions",
                        unit="1"
                    )
                    execution_counter.add(1, {"agent.name": agent.name})
                    
                    # Record execution duration
                    execution_histogram = meter.create_histogram(
                        name="agent.execution.duration_ms",
                        description="Agent execution duration in milliseconds",
                        unit="ms"
                    )
                    execution_histogram.record(execution_duration_ms, {"agent.name": agent.name})

    def _select_event(
        self,
        agent: CreatorAgent,
        events: list[KnowledgeEvent],
        allow_repeat: bool = False,
    ) -> Optional[KnowledgeEvent]:
        logger.info("Selecting event for agent %s: %d events available, last_cursor=%s, allow_repeat=%s", 
                   agent.name, len(events), agent.last_event_cursor, allow_repeat)
        
        if not events:
            logger.info("No events available for agent %s", agent.name)
            return None
        
        cursor = agent.last_event_cursor
        selected_event = None
        
        for i, event in enumerate(events):
            fingerprint = event.fingerprint()
            logger.debug("Event %d for agent %s: fingerprint=%s, title='%s'", 
                        i, agent.name, fingerprint, event.title[:50] if event.title else "No title")
            if not fingerprint:
                logger.debug("Skipping event %d - no fingerprint", i)
                continue
            if cursor != fingerprint or allow_repeat:
                selected_event = event
                logger.info("Selected event %d for agent %s: fingerprint=%s, title='%s'", 
                           i, agent.name, fingerprint, event.title[:50] if event.title else "No title")
                break
        
        if not selected_event:
            # All events already processed; allow digest cadences with first item
            cadence = self._normalise_cadence(agent.posting_cadence)
            if cadence in {"daily", "daily-digest", "weekly", "weekly-digest"}:
                logger.info("All events processed, using first event for digest cadence (%s) for agent %s", 
                           cadence, agent.name)
                selected_event = events[0]
            else:
                logger.info("All events already processed and not digest cadence (%s) for agent %s", 
                           cadence, agent.name)
        
        return selected_event

    def _should_run_agent(self, agent: CreatorAgent, now: datetime) -> bool:
        cadence = self._normalise_cadence(agent.posting_cadence)
        last_run = agent.last_run_at
        if cadence in {"per-event", "important-only"}:
            if not last_run:
                return True
            return now - last_run >= self._per_event_cooldown
        if cadence not in self._cadence_windows:
            return True
        target = compute_next_run_at(
            cadence=cadence,
            created_at=agent.created_at,
            last_run=agent.last_generated_at or agent.last_run_at,
        )
        if target is None:
            return True
        return now + self._slot_tolerance >= target

    def _event_meets_importance(self, agent: CreatorAgent, event: KnowledgeEvent) -> bool:
        hierarchy = {"low": 0, "normal": 1, "important": 2, "critical": 3}
        def norm(val: Optional[str]) -> str:
            try:
                return str(val or "normal").strip().lower()
            except Exception:
                return "normal"
        threshold = hierarchy.get(norm(agent.importance_threshold), 1)
        event_rank = hierarchy.get(norm(getattr(event, "importance", None)), 1)
        meets_threshold = event_rank >= threshold
        
        logger.info("Importance check for agent %s: event_importance='%s' (%d) >= threshold='%s' (%d) = %s", 
                   agent.name, getattr(event, "importance", None), event_rank, 
                   agent.importance_threshold, threshold, meets_threshold)
        
        return meets_threshold
    
    def _select_perspective(self, agent: CreatorAgent, now: datetime) -> Optional[str]:
        """
        Select perspective for content discovery to add variety.
        
        Rotates perspectives based on day of week:
        - Monday: "events" (week planning)
        - Tuesday/Thursday: "trends" (analysis)
        - Wednesday/Friday: None (default cadence-based)
        - Weekend: "decisions" (recaps)
        """
        weekday = now.weekday()  # 0=Monday, 6=Sunday
        
        # Only vary perspectives for weekly+ cadences
        if agent.posting_cadence in {"per-event", "daily", "daily-digest"}:
            return None  # Use default cadence routing
        
        perspective_map = {
            0: "events",      # Monday - upcoming events
            1: "trends",      # Tuesday - topic trends
            2: None,          # Wednesday - default
            3: "trends",      # Thursday - topic trends
            4: None,          # Friday - default
            5: "decisions",   # Saturday - recent decisions
            6: "decisions",   # Sunday - recent decisions
        }
        
        perspective = perspective_map.get(weekday)
        if perspective:
            logger.info(
                "Agent %s using perspective '%s' for %s",
                agent.name,
                perspective,
                now.strftime("%A"),
            )
        return perspective

    # ------------------------------------------------------------------
    # Personal UserAgent scheduling
    # ------------------------------------------------------------------

    def _process_user_agents(self) -> None:
        now = datetime.now(timezone.utc)
        agents = self._user_agent_service.get_all_enabled_agents()
        logger.info("Scheduler: %d enabled user agent(s) to check", len(agents))
        for agent_dict in agents:
            try:
                self._execute_user_agent(agent_dict, now)
            except Exception as exc:
                logger.exception(
                    "User agent %s (id=%s) run failed: %s",
                    agent_dict.get("name"),
                    agent_dict.get("id"),
                    exc,
                )
                # Persist the error so the UI can surface it with a fix action
                try:
                    self._user_agent_service.mark_error(agent_dict["id"], str(exc))
                except Exception:
                    pass

    def _should_run_user_agent(self, agent_dict: dict, now: datetime) -> bool:
        cadence = self._normalise_cadence(agent_dict.get("cadence", "daily"))
        if cadence not in self._cadence_windows:
            return True
        created_at = self._coerce_dt(agent_dict.get("created_at"))
        last_run = self._coerce_dt(
            agent_dict.get("last_generated_at") or agent_dict.get("last_run_at")
        )
        target = compute_next_run_at(
            cadence=cadence,
            created_at=created_at,
            last_run=last_run,
        )
        if target is None:
            return True
        return now + self._slot_tolerance >= target

    @staticmethod
    def _coerce_dt(value: Optional[object]) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        return None

    def _execute_user_agent(self, agent_dict: dict, now: datetime) -> None:
        agent_name = agent_dict.get("name", f"user-agent-{agent_dict.get('id')}")
        if not self._should_run_user_agent(agent_dict, now):
            logger.debug(
                "User agent %s not due yet (cadence=%s, last_generated_at=%s)",
                agent_name,
                agent_dict.get("cadence"),
                agent_dict.get("last_generated_at"),
            )
            return
        logger.info(
            "Running user agent %s (id=%s, user_id=%s, cadence=%s)",
            agent_name,
            agent_dict.get("id"),
            agent_dict.get("user_id"),
            agent_dict.get("cadence"),
        )
        result = self._generation_service.generate_for_user_agent(agent_dict)
        if result:
            logger.info(
                "User agent %s generated post %s", agent_name, result.get("post_id")
            )
            # Clear any previous error on success
            self._user_agent_service.clear_error(agent_dict["id"])
        else:
            # No content this cycle — stamp last_run_at so we don't retry every tick
            logger.info("User agent %s: no content this cycle", agent_name)
            self._user_agent_service.mark_run(agent_dict["id"])

    # ------------------------------------------------------------------

    def _normalise_cadence(self, cadence: Optional[str]) -> str:
        if not cadence:
            return "per-event"
        return cadence.strip().lower().replace(" ", "-")
