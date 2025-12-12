"""Intelligent prompt builder for context-aware LLM-based content generation."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ..models.agent import CreatorAgent

logger = logging.getLogger(__name__)


class PromptBuilder:
    """Constructs rich system and user prompts with full agent context."""

    def __init__(self) -> None:
        pass

    def build_system_prompt(self, agent: CreatorAgent) -> str:
        """
        Build system prompt with agent personality, guidelines, and constraints.
        """
        base = (
            f"You are {agent.name}, an autonomous expert persona. "
            "Respond only with factual statements grounded in supplied context. "
            "Cite sources for all claims."
        )

        if agent.persona:
            base += f"\n\nPersona Details:\n{agent.persona}"

        # Tone and style guidance
        tone_guidance = {
            "analytical": "Provide in-depth analysis with data and reasoning.",
            "conversational": "Adopt a friendly, accessible tone suitable for broad audiences.",
            "technical": "Use precise technical terminology and focus on implementation details.",
            "journalistic": "Report facts objectively with news-style narrative.",
            "opinion": "Clearly distinguish fact from interpretation and personal analysis.",
        }
        tone = tone_guidance.get(agent.tone_style, "Maintain a professional tone.")
        base += f"\n\nStyle: {tone}"

        # Content length guidance
        length_guidance = {
            "short": "Keep summaries to 1-2 sentences; bodies to 2-3 paragraphs.",
            "medium": "Provide balanced summaries and 3-5 paragraph bodies.",
            "long": "Produce detailed summaries and comprehensive 6-10 paragraph bodies with examples.",
        }
        length = length_guidance.get(agent.content_length_preference, "Provide balanced length.")
        base += f"\n\n{length}"

        return base

    def build_user_prompt(
        self,
        agent: CreatorAgent,
        events: List[Dict[str, Any]],
        documents: List[Dict[str, Any]],
        recent_posts: Optional[List[Dict[str, Any]]] = None,
        user_reactions: Optional[Dict[str, int]] = None,
    ) -> str:
        """
        Build user prompt with current context, constraints, and examples.

        Args:
            agent: Creator agent persona
            events: Recent events/knowledge from Neo4j
            documents: Recent documents/resources
            recent_posts: Agent's last 5 posts (for deduplication)
            user_reactions: Like/dislike counts from user feedback
        """
        prompt = "Generate a new post with title, summary, body, tags, and sources.\n\n"

        # Context sources
        prompt += self._format_context_section(events, documents)

        # Deduplication hints
        if recent_posts:
            prompt += self._format_recent_posts_section(recent_posts)

        # Preference signals from user feedback
        if user_reactions:
            prompt += self._format_preference_signals_section(user_reactions)

        # Structure expectations
        prompt += (
            "\nRespond with a JSON object containing:\n"
            "{\n"
            '  "title": "string",\n'
            '  "summary": "string (1-2 sentences)",\n'
            '  "body": "string (main content)",\n'
            '  "tags": ["array", "of", "topic", "tags"],\n'
            '  "sources": [\n'
            '    {"source_kind": "event|document", "source_identifier": "url", "url": "url"}\n'
            "  ]\n"
            "}\n"
        )

        return prompt

    def _format_context_section(
        self,
        events: List[Dict[str, Any]],
        documents: List[Dict[str, Any]],
    ) -> str:
        """Format events and documents as context for the LLM."""
        prompt = "## Current Context\n\n"

        if events:
            prompt += "### Recent Events:\n"
            for i, event in enumerate(events[:8], 1):
                prompt += (
                    f"{i}. **{event.get('title', 'Untitled')}** "
                    f"(Importance: {event.get('importance', 'normal')})\n"
                    f"   {event.get('summary', '')}\n"
                    f"   Topics: {', '.join(event.get('topics', []))}\n"
                    f"   URL: {event.get('url', 'N/A')}\n\n"
                )

        if documents:
            prompt += "### Relevant Documents:\n"
            for i, doc in enumerate(documents[:5], 1):
                prompt += (
                    f"{i}. **{doc.get('title', 'Untitled')}**\n"
                    f"   {doc.get('summary', '')}\n"
                    f"   URL: {doc.get('url', 'N/A')}\n\n"
                )

        return prompt

    def _format_recent_posts_section(self, recent_posts: List[Dict[str, Any]]) -> str:
        """Add recent posts to guide against duplication."""
        if not recent_posts:
            return ""

        prompt = "## Recent Posts (Avoid Duplicating):\n"
        for post in recent_posts[:5]:
            prompt += f"- **{post.get('title', 'Untitled')}**: {post.get('body', '')[:100]}...\n"

        prompt += "\nEnsure the new post differs in angle, depth, or recency from above.\n\n"
        return prompt

    def _format_preference_signals_section(self, user_reactions: Dict[str, int]) -> str:
        """Add preference signals based on user feedback."""
        prompt = "## User Feedback Signals:\n"
        total_reactions = sum(user_reactions.values())
        if total_reactions == 0:
            return ""

        like_ratio = user_reactions.get("like", 0) / total_reactions if total_reactions > 0 else 0.5
        dislike_ratio = user_reactions.get("dislike", 0) / total_reactions if total_reactions > 0 else 0.5

        if like_ratio > 0.7:
            prompt += "- Users strongly like your recent content. Continue this style.\n"
        elif dislike_ratio > 0.5:
            prompt += "- Users have mixed reactions. Adjust tone or focus.\n"

        prompt += (
            f"- Like ratio: {like_ratio:.1%} | "
            f"Total reactions: {total_reactions}\n\n"
        )
        return prompt
