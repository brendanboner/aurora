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
            f"You are {agent.name}, a seasoned industry professional and thought leader. "
            "You write LinkedIn-style professional content that synthesizes recent industry developments, "
            "provides expert analysis, and shares insights based on your expertise.\n\n"
            "CRITICAL RULES:\n"
            "- DO NOT copy or repeat article text verbatim\n"
            "- DO reference articles naturally (e.g., 'According to recent reports...', 'A new study shows...', 'Industry sources indicate...')\n"
            "- Provide YOUR professional perspective and analysis\n"
            "- Connect multiple sources to tell a bigger story\n"
            "- Write in first person when sharing opinions or observations\n"
            "- Keep tone professional but conversational\n"
            "- Use markdown formatting sparingly (bold for emphasis, lists for clarity)"
        )

        if agent.persona:
            base += f"\n\nYour Professional Background:\n{agent.persona}"

        # Tone and style guidance
        tone_guidance = {
            "analytical": "Provide data-driven insights with clear reasoning. Break down complex topics for your network.",
            "conversational": "Share insights in an accessible way, like you're explaining to a colleague over coffee.",
            "technical": "Dive into technical details while keeping it readable. Your audience respects precision.",
            "journalistic": "Report on developments objectively, then add your expert take on what it means.",
            "opinion": "Lead with your perspective, then back it up with facts and industry context.",
        }
        tone = tone_guidance.get(agent.tone_style, "Maintain a professional, thoughtful tone.")
        base += f"\n\nYour Writing Style: {tone}"

        # Content length guidance
        length_guidance = {
            "short": "Keep posts concise: 2-3 short paragraphs (150-250 words total). Get to the point quickly.",
            "medium": "Write 3-5 paragraphs (300-500 words). Balance depth with readability.",
            "long": "Develop comprehensive posts with 5-8 paragraphs (600-1000 words). Include examples and thorough analysis.",
        }
        length = length_guidance.get(agent.content_length_preference, "Write 3-5 balanced paragraphs.")
        base += f"\n\nPost Length: {length}"

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
        prompt = (
            "Write a professional LinkedIn-style post that synthesizes the following recent industry developments. "
            "Your post should:\n"
            "1. Lead with a hook or key insight that grabs attention\n"
            "2. Reference 2-3 of the most relevant articles naturally (don't list them)\n"
            "3. Provide YOUR expert analysis and perspective\n"
            "4. Connect the dots between different developments if applicable\n"
            "5. End with a thought-provoking question or call-to-action\n\n"
        )

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
            "\n## OUTPUT FORMAT\n"
            "Respond with a JSON object:\n"
            "{\n"
            '  "title": "Engaging headline (60-100 chars)",\n'
            '  "summary": "One compelling sentence that captures the main point",\n'
            '  "body": "Your full post in markdown format. Write 2-5 paragraphs that flow naturally. Reference articles inline like a professional would.",\n'
            '  "tags": ["industry-relevant", "topic-tags"],\n'
            '  "sources": [\n'
            '    {"source_kind": "event", "source_identifier": "url", "url": "url", "title": "article title"}\n'
            "  ]\n"
            "}\n\n"
            "REMEMBER: Synthesize and analyze - don't copy. You're a professional sharing insights, not a news aggregator."
        )

        return prompt

    def _format_context_section(
        self,
        events: List[Dict[str, Any]],
        documents: List[Dict[str, Any]],
    ) -> str:
        """Format events and documents as context for the LLM."""
        prompt = "## RECENT INDUSTRY DEVELOPMENTS\n\n"
        prompt += "Here are the latest articles and updates in your domain. Synthesize these into a cohesive narrative:\n\n"

        if events:
            prompt += "### Articles & News:\n"
            for i, event in enumerate(events[:8], 1):
                prompt += (
                    f"{i}. **{event.get('title', 'Untitled')}**\n"
                    f"   Summary: {event.get('summary', 'No summary available')}\n"
                    f"   Topics: {', '.join(event.get('topics', []))}\n"
                    f"   Importance: {event.get('importance', 'normal')}\n"
                    f"   URL: {event.get('url', 'N/A')}\n\n"
                )

        if documents:
            prompt += "### Additional Resources:\n"
            for i, doc in enumerate(documents[:5], 1):
                prompt += (
                    f"{i}. **{doc.get('title', 'Untitled')}**\n"
                    f"   {doc.get('summary', 'No summary available')}\n"
                    f"   URL: {doc.get('url', 'N/A')}\n\n"
                )

        return prompt

    def _format_recent_posts_section(self, recent_posts: List[Dict[str, Any]]) -> str:
        """Add recent posts to guide against duplication."""
        if not recent_posts:
            return ""

        prompt = "## YOUR RECENT POSTS (Don't repeat these topics/angles):\n"
        for post in recent_posts[:5]:
            prompt += f"- **{post.get('title', 'Untitled')}**: {post.get('body', '')[:150]}...\n"

        prompt += "\nMake sure your new post covers different aspects or provides a fresh perspective.\n\n"
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
