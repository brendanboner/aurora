"""Intelligent prompt builder for context-aware LLM-based content generation."""
from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ..models.agent import CreatorAgent

logger = logging.getLogger(__name__)


class PromptBuilder:
    """Constructs rich system and user prompts with full agent context."""

    # Alternative prompt templates for variety
    PROMPT_TEMPLATES = {
        "standard": {
            "description": "Balanced synthesis of developments",
            "instructions": [
                "Lead with a hook or key insight that grabs attention",
                "Reference 2-3 of the most relevant articles naturally (don't list them)",
                "Provide YOUR expert analysis and perspective",
                "Connect the dots between different developments if applicable",
                "End with a thought-provoking question or call-to-action"
            ]
        },
        "contrarian": {
            "description": "Challenge conventional wisdom or popular narrative",
            "instructions": [
                "Identify the mainstream interpretation of these developments",
                "Present an alternative viewpoint based on your expertise",
                "Support your contrarian take with specific evidence from the articles",
                "Acknowledge the conventional view while explaining why you see it differently",
                "Invite debate or alternative perspectives from your network"
            ]
        },
        "practical_guide": {
            "description": "Action-oriented advice for practitioners",
            "instructions": [
                "Frame the developments as actionable insights for your audience",
                "Explain what these changes mean for day-to-day practice",
                "Provide 2-3 concrete recommendations or steps",
                "Include real-world examples or scenarios where applicable",
                "End with next steps or resources for deeper exploration"
            ]
        },
        "trend_analysis": {
            "description": "Big picture view connecting dots across time",
            "instructions": [
                "Place these developments in the context of longer-term trends",
                "Connect current events to past developments in the field",
                "Identify patterns or signals about future direction",
                "Draw insights from comparing multiple sources",
                "Project what this might mean for the industry 6-12 months out"
            ]
        },
        "explainer": {
            "description": "Educational breakdown for broader audience",
            "instructions": [
                "Start by explaining the core concept or technology clearly",
                "Break down why this development matters and who it affects",
                "Use analogies or examples to make technical concepts accessible",
                "Address common misconceptions or questions",
                "End by connecting to practical implications your audience cares about"
            ]
        }
    }

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
            "- Use markdown formatting sparingly (bold for emphasis, lists for clarity)\n\n"
            "UNIQUENESS IMPERATIVE:\n"
            "- Write in YOUR distinctive voice—avoid generic phrasing typical of industry analysts\n"
            "- Your persona and background below define your UNIQUE perspective\n"
            "- Different professionals analyzing the same news will emphasize different angles\n"
            "- Let your expertise, tone, and priorities shape your take on developments\n"
            "- Avoid clichés like 'game-changer', 'paradigm shift', 'revolutionary' unless genuinely warranted\n"
            "- Be specific and concrete rather than using vague business speak"
        )

        # STRONGLY emphasize persona - this is the key differentiator
        if agent.persona:
            base += f"\n\n{'=' * 60}\n"
            base += f"YOUR UNIQUE PROFESSIONAL IDENTITY (Let this guide EVERY aspect of your writing):\n"
            base += f"{'=' * 60}\n"
            base += f"{agent.persona}\n"
            base += f"{'=' * 60}\n"

        # Tone and style guidance
        tone_guidance = {
            "analytical": "Provide data-driven insights with clear reasoning. Break down complex topics systematically for your network. Use numbers, comparisons, and evidence-based conclusions.",
            "conversational": "Share insights like you're explaining to a colleague over coffee. Be approachable, use personal anecdotes, and keep jargon minimal. Make complex topics relatable.",
            "technical": "Dive deep into technical details while keeping it readable. Your audience respects precision and technical accuracy. Use specific terminology correctly and explain implications.",
            "journalistic": "Report on developments objectively first, then add your expert take on what it means. Separate facts from interpretation clearly. Cite sources explicitly.",
            "opinion": "Lead with your distinctive perspective, then back it up with facts and industry context. Don't hedge—own your viewpoint while acknowledging complexity.",
        }
        tone = tone_guidance.get(agent.tone_style, "Maintain a professional, thoughtful tone.")
        base += f"\n\nYour Writing Style: {tone}"

        # Content length guidance
        length_guidance = {
            "short": "Keep posts concise: 2-3 short paragraphs (150-250 words total). Get to the point quickly. Every sentence must earn its place.",
            "medium": "Write 3-5 paragraphs (300-500 words). Balance depth with readability. Develop ideas without overexplaining.",
            "long": "Develop comprehensive posts with 5-8 paragraphs (600-1000 words). Include examples, nuances, and thorough analysis. Take time to explore implications.",
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
        all_agents_recent_posts: Optional[List[Dict[str, Any]]] = None,
        template_override: Optional[str] = None,
        freshness_note: Optional[str] = None,
    ) -> str:
        """
        Build user prompt with current context, constraints, and examples.

        Args:
            agent: Creator agent persona
            events: Recent events/knowledge from Neo4j
            documents: Recent documents/resources
            recent_posts: Agent's last 5 posts (for deduplication)
            user_reactions: Like/dislike counts from user feedback
            all_agents_recent_posts: Recent posts from all agents (for cross-agent deduplication)
            template_override: Force specific template (default: random selection)
            freshness_note: Optional framing note when content is older than the cadence window
        """
        # Select template for variety
        template_key = template_override or self._select_template(agent)
        template = self.PROMPT_TEMPLATES[template_key]
        
        prompt = (
            f"Write a professional LinkedIn-style post that synthesizes the following recent industry developments. "
            f"\n\n**Approach: {template['description']}**\n\n"
            "Your post should:\n"
        )
        
        for i, instruction in enumerate(template['instructions'], 1):
            prompt += f"{i}. {instruction}\n"
        
        prompt += "\n"

        # Freshness framing — prepend before context so the LLM sees it first
        if freshness_note:
            prompt += f"\n## IMPORTANT CONTENT FRAMING\n{freshness_note}\n\n"

        # Context sources
        prompt += self._format_context_section(events, documents)

        # Deduplication hints (own posts)
        if recent_posts:
            prompt += self._format_recent_posts_section(recent_posts)
        
        # Cross-agent deduplication (what others wrote)
        if all_agents_recent_posts:
            prompt += self._format_cross_agent_posts_section(all_agents_recent_posts)

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
            "REMEMBER: Synthesize and analyze in YOUR voice - don't copy. You're a professional sharing insights, not a news aggregator."
        )

        return prompt
    
    def _select_template(self, agent: CreatorAgent) -> str:
        """Select a prompt template based on agent characteristics and randomness."""
        # Weight templates based on agent tone_style
        weights = {
            "analytical": {"standard": 0.3, "trend_analysis": 0.4, "explainer": 0.2, "contrarian": 0.1, "practical_guide": 0.0},
            "conversational": {"standard": 0.2, "practical_guide": 0.4, "explainer": 0.3, "contrarian": 0.05, "trend_analysis": 0.05},
            "technical": {"standard": 0.2, "explainer": 0.3, "trend_analysis": 0.3, "practical_guide": 0.15, "contrarian": 0.05},
            "journalistic": {"standard": 0.4, "trend_analysis": 0.3, "contrarian": 0.2, "explainer": 0.05, "practical_guide": 0.05},
            "opinion": {"contrarian": 0.5, "standard": 0.2, "trend_analysis": 0.2, "practical_guide": 0.05, "explainer": 0.05},
        }
        
        agent_weights = weights.get(agent.tone_style, weights["analytical"])
        templates = list(agent_weights.keys())
        probabilities = list(agent_weights.values())
        
        return random.choices(templates, weights=probabilities, k=1)[0]

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
    
    def _format_cross_agent_posts_section(self, all_agents_posts: List[Dict[str, Any]]) -> str:
        """Add posts from other agents to avoid similar angles."""
        if not all_agents_posts:
            return ""

        prompt = "## RECENT POSTS FROM OTHER ANALYSTS (Avoid these angles - find YOUR unique take):\n"
        for post in all_agents_posts[:10]:
            agent_name = post.get('agent_name', 'Unknown')
            title = post.get('title', 'Untitled')
            snippet = post.get('body', '')[:100]
            prompt += f"- **{agent_name}** wrote: \"{title}\" — {snippet}...\n"

        prompt += (
            "\n**CRITICAL**: These angles have already been covered by other analysts. "
            "Your post MUST offer a distinctly different perspective, focus, or interpretation. "
            "Don't just reword—bring YOUR unique expertise and viewpoint to these same developments.\n\n"
        )
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

    def build_linkedin_parsing_prompt(self, linkedin_text: str) -> tuple[str, str]:
        """
        Build prompts to parse LinkedIn profile content into CreatorAgentBase config.
        
        Args:
            linkedin_text: Raw paste of LinkedIn profile page including posts
            
        Returns:
            Tuple of (system_prompt, user_prompt)
        """
        system_prompt = (
            "You are an expert at analyzing LinkedIn profiles and writing samples to create "
            "creator agent personas. Your task is to extract structured information from a "
            "LinkedIn profile paste and generate a complete agent configuration.\n\n"
            "CRITICAL REQUIREMENTS:\n"
            "- The profile created must be fictional and inspired by the real professional\n"
            "- Extract only factual information present in the paste\n"
            "- Infer tone, style, and expertise from actual posts shown\n"
            "- Use sensible defaults for any missing information\n"
            "- Ignore LinkedIn UI boilerplate (navigation, buttons, etc.)\n"
            "- Return valid JSON matching the exact schema provided"
        )
        
        user_prompt = (
            "Analyze the following LinkedIn profile content and extract agent configuration.\n\n"
            f"## LINKEDIN PROFILE CONTENT\n\n{linkedin_text}\n\n"
            "## EXTRACTION INSTRUCTIONS\n\n"
            "1. **name**: Create a short handle (e.g., 'Brendan Wireless', 'Sarah Security'). "
            "Base it on the person's actual initials, but always generate a fictional first name.\n\n"
            "2. **description**: Write a 2-3 paragraph summary of the fictional persona's background and expertise "
            "for UI/documentation purposes. Example: 'Dave is a highly experienced wireless standards "
            "expert with over two decades of hands-on involvement in Wi-Fi and related alliance activity. "
            "He actively follows Wi-Fi Alliance workgroups and observes adjacent bodies.' Focus on their "
            "professional domain, key areas of focus, and what they're known for.\n\n"
            "3. **persona**: Write detailed behavioral instructions for an LLM to embody this writing style. "
            "MUST START with: 'You are [fictional name with same initials], a [role/title based on their "
            "expertise]. This is a fictional internal creator agent inspired by writing samples from a real "
            "professional.'\n\n"
            "Then provide specific instructions covering:\n"
            "- Writing tone and style (confident, analytical, conversational, technical, etc.)\n"
            "- Content preferences (brevity, depth, structure)\n"
            "- What to prioritize (specific topics, organizations, standards)\n"
            "- What to avoid (hype, marketing language, speculation, off-topic content)\n"
            "- How to handle different scenarios (major news vs. incremental updates)\n"
            "- Specific behavioral rules derived from their actual post patterns\n\n"
            "Write this as direct instructions to the LLM in second person ('You write with...', "
            "'You avoid...', 'You prioritize...'). Be specific and actionable.\n\n"
            "4. **expertise_topics**: Extract 5-10 key topics from posts (e.g., ['Wi-Fi', '6 GHz spectrum', "
            "'wireless standards', 'AFC']). Look for recurring themes and hashtags.\n\n"
            "5. **expertise_organisations**: List 5-10 organizations mentioned frequently (e.g., "
            "['Extreme Networks', 'Wi-Fi Alliance', 'WBA']). Include companies, standards bodies, "
            "associations.\n\n"
            "6. **expertise_standards**: List technical standards or protocols mentioned (e.g., "
            "['802.11ax', 'Wi-Fi 6E', 'Wi-Fi 7']). Leave empty if none found.\n\n"
            "7. **tone_style**: Analyze post tone. Choose one: 'analytical', 'conversational', "
            "'technical', 'journalistic', 'opinion'. Default: 'analytical'.\n\n"
            "8. **posting_cadence**: Infer from post frequency patterns. Choose one: 'daily', "
            "'per-event', 'weekly', 'as-needed'. Default: 'per-event'.\n\n"
            "9. **content_length_preference**: Analyze typical post length. Choose one: 'short' "
            "(2-3 paragraphs), 'medium' (3-5 paragraphs), 'long' (5+ paragraphs). Default: 'medium'.\n\n"
            "10. **importance_threshold**: Based on post seriousness. Choose one: 'high' (only major news), "
            "'normal' (balanced coverage), 'low' (broad topics). Default: 'normal'.\n\n"
            "11. **discovery_tolerance**: How exploratory are topics? Range 0.0-1.0. If posts stick to "
            "narrow expertise: 0.3-0.5. If they explore adjacent areas: 0.6-0.8. Default: 0.5\n\n"
            "12. **cadence_window_days**: Infer posting frequency. If posting daily: 3-5 days. "
            "Weekly: 7-14 days. Less frequent: 21-30 days. Default: 7\n\n"
            "13. **enabled**: Always true\n\n"
            "## OUTPUT FORMAT\n\n"
            "Return ONLY valid JSON with this exact structure:\n"
            "{\n"
            '  "name": "handle_style_name",\n'
            '  "description": "Profile tagline/headline",\n'
            '  "persona": "Disclaimer + 2-3 paragraphs about style and expertise",\n'
            '  "expertise_topics": ["topic1", "topic2"],\n'
            '  "expertise_organisations": ["org1", "org2"],\n'
            '  "expertise_standards": ["standard1", "standard2"],\n'
            '  "tone_style": "analytical",\n'
            '  "posting_cadence": "per-event",\n'
            '  "content_length_preference": "medium",\n'
            '  "importance_threshold": "normal",\n'
            '  "discovery_tolerance": 0.5,\n'
            '  "cadence_window_days": 7,\n'
            '  "enabled": true\n'
            "}"
        )
        
        return system_prompt, user_prompt
