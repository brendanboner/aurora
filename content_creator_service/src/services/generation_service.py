"""Content generation orchestration for CreatorAgents."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from ..llm_client import get_llm_client
from ..models.agent import CreatorAgent
from ..models.post import PostSource
from ..neo4j_context import get_context_gateway
from ..settings import get_settings
from .prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


class GenerationService:
    def __init__(self) -> None:
        self._context = get_context_gateway()
        self._settings = get_settings()
        self._prompt_builder = PromptBuilder()

    def build_prompt(self, agent: CreatorAgent, context_payload: Dict[str, Any]) -> Dict[str, str]:
        """Legacy method for backward compatibility. Use PromptBuilder instead."""
        system_prompt = self._prompt_builder.build_system_prompt(agent)
        user_prompt = self._prompt_builder.build_user_prompt(
            agent,
            context_payload.get("events", []),
            context_payload.get("documents", []),
        )
        return {"system": system_prompt, "user": user_prompt}

    def generate_post_payload(
        self,
        agent: CreatorAgent,
        topics: Optional[List[str]] = None,
        organisations: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a post with full context including agent history and user feedback.
        """
        topic_scope = topics or agent.expertise_topics
        organisation_scope = organisations or agent.expertise_organisations

        # Fetch current events and documents
        events = self._context.fetch_recent_events(topic_scope, organisation_scope, limit=8)
        documents = self._context.fetch_recent_documents(organisation_scope, limit=12)

        if not events and not documents:
            logger.info("No context available for agent %s", agent.name)
            return None

        # Fetch agent's recent posts for deduplication
        recent_posts = self._fetch_agent_recent_posts(agent.id, limit=5)
        
        # Fetch recent posts from ALL agents for cross-agent deduplication
        all_agents_posts = self._fetch_all_recent_posts(exclude_agent_id=agent.id, limit=10)

        # Fetch user reactions to recent posts for preference signals
        user_reactions = self._aggregate_user_reactions(recent_posts)

        # Build rich prompt with all context
        system_prompt = self._prompt_builder.build_system_prompt(agent)
        user_prompt = self._prompt_builder.build_user_prompt(
            agent,
            events=events,
            documents=documents,
            recent_posts=recent_posts,
            user_reactions=user_reactions,
            all_agents_recent_posts=all_agents_posts,
        )

        # Determine temperature (agent override or system default)
        temperature = agent.llm_temperature_override if agent.llm_temperature_override is not None else None

        # Call LLM with enriched prompt and temperature
        llm_client = get_llm_client()
        llm_response = llm_client.generate(system_prompt, user_prompt, temperature_override=temperature)

        if not llm_response:
            logger.warning("LLM generation failed for agent %s", agent.name)
            return None

        # Coerce sources from LLM response or fallback to context
        sources = self._coerce_sources(llm_response.get("sources"), events, documents)

        return {
            "title": llm_response.get("title", "Untitled update"),
            "summary": llm_response.get("summary"),
            "body": llm_response.get("body"),
            "tags": llm_response.get("tags", topic_scope),
            "visibility": llm_response.get("visibility", "public"),
            "importance": llm_response.get("importance", agent.importance_threshold),
            "content_length": llm_response.get("content_length", agent.content_length_preference),
            "sources": sources,
        }

    def _fetch_agent_recent_posts(self, agent_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        """Fetch agent's recent posts for deduplication context."""
        try:
            from .. import db
            
            rows = db.fetch_all(
                """
                SELECT id, title, body, created_at
                FROM post
                WHERE agent_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (agent_id, limit),
            )

            return [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "body": row["body"][:200] if row["body"] else "",  # Truncate for prompt context
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        except Exception as e:
            logger.warning("Failed to fetch recent posts for agent %d: %s", agent_id, e)
            return []
    
    def _fetch_all_recent_posts(self, exclude_agent_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch recent posts from all agents (excluding current) for cross-agent deduplication."""
        try:
            from .. import db
            
            rows = db.fetch_all(
                """
                SELECT p.id, p.title, p.body, p.created_at, ca.name as agent_name
                FROM post p
                JOIN creator_agent ca ON p.agent_id = ca.id
                WHERE p.agent_id != %s
                ORDER BY p.created_at DESC
                LIMIT %s
                """,
                (exclude_agent_id, limit),
            )

            return [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "body": row["body"][:200] if row["body"] else "",  # Truncate for prompt context
                    "created_at": row["created_at"],
                    "agent_name": row["agent_name"],
                }
                for row in rows
            ]
        except Exception as e:
            logger.warning("Failed to fetch all recent posts: %s", e)
            return []

    def _aggregate_user_reactions(self, recent_posts: List[Dict[str, Any]]) -> Optional[Dict[str, int]]:
        """Aggregate like/dislike counts from recent posts."""
        try:
            from .. import db

            post_ids = [p.get("id") for p in recent_posts]

            if not post_ids:
                return None

            # Create placeholders for IN clause
            placeholders = ",".join(["%s"] * len(post_ids))
            query = f"""
                SELECT reaction_type
                FROM user_post_reaction
                WHERE post_id IN ({placeholders})
            """
            
            rows = db.fetch_all(query, tuple(post_ids))

            reaction_counts = {"like": 0, "dislike": 0}
            for row in rows:
                reaction = row.get("reaction_type")
                if reaction in reaction_counts:
                    reaction_counts[reaction] += 1

            return reaction_counts if sum(reaction_counts.values()) > 0 else None
        except Exception as e:
            logger.warning("Failed to aggregate user reactions: %s", e)
            return None

    def _coerce_sources(
        self,
        raw_sources: Optional[List[Dict[str, Any]]],
        events: List[Dict[str, Any]],
        documents: List[Dict[str, Any]],
    ) -> List[PostSource]:
        sources: List[PostSource] = []
        if raw_sources:
            for raw in raw_sources:
                try:
                    sources.append(PostSource(**raw))
                except ValidationError:
                    logger.warning("Discarded invalid LLM source payload: %s", raw)
        if sources:
            return sources

        for event in events:
            url = event.get("url")
            title = event.get("title")
            if url:
                sources.append(
                    PostSource(
                        source_kind="event",
                        source_identifier=url,
                        url=url,
                        title=title,
                    )
                )
            if len(sources) >= 2:
                break
        if sources:
            return sources

        for doc in documents:
            url = doc.get("url")
            title = doc.get("title")
            if url:
                sources.append(
                    PostSource(
                        source_kind="document",
                        source_identifier=url,
                        url=url,
                        title=title,
                    )
                )
            if len(sources) >= 2:
                break
        return sources
