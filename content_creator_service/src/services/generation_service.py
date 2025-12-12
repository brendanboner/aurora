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

logger = logging.getLogger(__name__)


class GenerationService:
    def __init__(self) -> None:
        self._context = get_context_gateway()
        self._settings = get_settings()

    def build_prompt(self, agent: CreatorAgent, context_payload: Dict[str, Any]) -> Dict[str, str]:
        system_prompt = (
            "You are CreatorAgent {name}, an autonomous expert persona. "
            "Only summarise facts grounded in the supplied context and cite sources."
        ).format(name=agent.name)
        user_prompt = (
            "Persona description: {persona}\n"
            "Tone/style: {tone}\n"
            "Generate a JSON response with title, summary, body, tags, and sources.\n"
            "Context: {context}"
        ).format(
            persona=agent.persona or agent.description or "",
            tone=agent.tone_style,
            context=context_payload,
        )
        return {"system": system_prompt, "user": user_prompt}

    def generate_post_payload(
        self,
        agent: CreatorAgent,
        topics: List[str],
        organisations: List[str],
    ) -> Optional[Dict[str, Any]]:
        topic_scope = topics or agent.expertise_topics
        organisation_scope = organisations or agent.expertise_organisations
        events = self._context.fetch_recent_events(topic_scope, organisation_scope, limit=8)
        documents = self._context.fetch_recent_documents(organisation_scope, limit=12)
        if not events and not documents:
            logger.info("No context available for agent %s", agent.name)
            return None
        prompt = self.build_prompt(agent, {"events": events, "documents": documents})
        llm_client = get_llm_client()
        llm_response = llm_client.generate(prompt["system"], prompt["user"])
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
            if url:
                sources.append(
                    PostSource(
                        source_kind="event",
                        source_identifier=url,
                        url=url,
                    )
                )
            if len(sources) >= 2:
                break
        if sources:
            return sources

        for doc in documents:
            url = doc.get("url")
            if url:
                sources.append(
                    PostSource(
                        source_kind="document",
                        source_identifier=url,
                        url=url,
                    )
                )
            if len(sources) >= 2:
                break
        return sources
