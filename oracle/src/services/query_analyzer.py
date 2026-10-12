"""Query Analyzer - Analyzes query quality and suggests improvements.

This module evaluates user queries before execution to determine if they
could be improved, and suggests better alternatives that aim to answer
the same question more effectively.
"""

from dataclasses import dataclass
import logging
import re
from typing import Optional

from src.services.llm_client import get_llm_client, call_llm
from src.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class QueryAnalysis:
    """Result of query analysis."""
    original_query: str
    is_good_query: bool
    quality_score: float  # 0.0 to 1.0
    issues: list[str]  # List of identified issues
    revised_query: Optional[str]  # Suggested improved query
    revision_reason: Optional[str]  # Why the revision is better
    tokens_used: int = 0


# Common issues that make queries less effective
QUERY_ISSUES = {
    "too_vague": "Query is too vague or general",
    "no_topic": "No specific topic or technology mentioned",
    "no_timeframe": "No time context for time-sensitive queries",
    "ambiguous_terms": "Contains ambiguous terms that could match too broadly",
    "missing_context": "Missing helpful context (organization, category, etc.)",
    "too_complex": "Query tries to ask multiple unrelated questions",
}


async def analyze_query(query: str) -> QueryAnalysis:
    """
    Analyze a query to determine if it could be improved.
    
    Returns analysis with optional revised query suggestion.
    Only suggests revisions when it would be significantly helpful.
    
    Args:
        query: The user's original query
        
    Returns:
        QueryAnalysis with quality assessment and optional revision
    """
    issues = []
    quality_score = 1.0
    
    query_lower = query.lower().strip()
    
    # Check for common issues using heuristics first
    
    # 1. Too short/vague
    word_count = len(query_lower.split())
    if word_count < 3:
        issues.append(QUERY_ISSUES["too_vague"])
        quality_score -= 0.3
    
    # 2. No specific topic mentioned
    topic_patterns = [
        r'wi-?fi\s*[678]', r'802\.11[a-z]{2}', r'6\s*ghz', r'mlo',
        r'5g|6g', r'bluetooth', r'thread', r'matter', r'zigbee',
        r'lora', r'uwb', r'passpoint', r'easymesh', r'wpa[23]',
    ]
    has_topic = any(re.search(p, query_lower) for p in topic_patterns)
    
    # Also check for organization mentions
    org_patterns = [
        r'wi-?fi\s*alliance', r'wfa', r'ieee', r'3gpp',
        r'qualcomm', r'broadcom', r'intel', r'mediatek',
    ]
    has_org = any(re.search(p, query_lower) for p in org_patterns)
    
    if not has_topic and not has_org and word_count < 6:
        issues.append(QUERY_ISSUES["no_topic"])
        quality_score -= 0.2
    
    # 3. Check for time-sensitive words without timeframe
    time_sensitive_words = ['latest', 'recent', 'new', 'update', 'announcement', 'news']
    has_time_sensitive = any(w in query_lower for w in time_sensitive_words)
    
    time_patterns = [
        r'last\s+(\d+\s+)?(week|month|year|quarter|day)s?',
        r'past\s+(\d+\s+)?(week|month|year|quarter|day)s?',
        r'this\s+(week|month|year)',
        r'in\s+20\d{2}',
        r'20\d{2}-\d{2}-\d{2}',
        r'(january|february|march|april|may|june|july|august|september|october|november|december)',
        r'today|yesterday|tomorrow',
        r'(\d+)\s+(day|week|month|year)s?\s+ago',
    ]
    has_timeframe = any(re.search(p, query_lower) for p in time_patterns)
    
    if has_time_sensitive and not has_timeframe:
        issues.append(QUERY_ISSUES["no_timeframe"])
        quality_score -= 0.15
    
    # 4. Check for overly generic queries
    generic_starts = [
        'tell me about', 'what is', 'explain', 'describe',
        'information about', 'details on', 'everything about',
    ]
    is_generic = any(query_lower.startswith(g) for g in generic_starts)
    if is_generic and word_count < 5:
        issues.append(QUERY_ISSUES["too_vague"])
        quality_score -= 0.1
    
    # 5. Check for questions that might be too broad
    broad_questions = ['what happened', 'what\'s new', 'any updates', 'what\'s going on']
    is_broad = any(b in query_lower for b in broad_questions)
    if is_broad and not has_topic and not has_timeframe:
        issues.append(QUERY_ISSUES["missing_context"])
        quality_score -= 0.2
    
    # Ensure score stays in valid range
    quality_score = max(0.0, min(1.0, quality_score))
    
    # Determine if query is good enough
    is_good_query = quality_score >= 0.7 and len(issues) == 0
    
    # Generate revised query only if quality is poor and we can improve it
    revised_query = None
    revision_reason = None
    tokens_used = 0
    
    if not is_good_query and quality_score < 0.6:
        # Try to generate a better query using LLM
        revised_query, revision_reason, tokens_used = await _generate_revised_query(
            query, issues
        )
    
    return QueryAnalysis(
        original_query=query,
        is_good_query=is_good_query,
        quality_score=quality_score,
        issues=issues,
        revised_query=revised_query,
        revision_reason=revision_reason,
        tokens_used=tokens_used,
    )


async def _generate_revised_query(
    query: str,
    issues: list[str],
) -> tuple[Optional[str], Optional[str], int]:
    """
    Generate a revised query using LLM.
    
    Returns (revised_query, reason, tokens_used)
    """
    client = get_llm_client()
    if client is None:
        # Fallback to heuristic improvements
        return _heuristic_revision(query, issues)
    
    try:
        system_prompt = """You are a query optimization assistant for a knowledge graph-based retrieval system about wireless standards and industry news.

## How Our Retrieval System Works

The system uses a Neo4j knowledge graph with these key nodes and relationships:
- **Document nodes**: Press releases, whitepapers, blog posts, news articles, specifications
- **Topic nodes**: Technologies like "Wi-Fi 7", "802.11be", "Matter", "6 GHz", "MLO"
- **Organization nodes**: Companies and bodies like "Wi-Fi Alliance", "IEEE", "Qualcomm", "Intel"
- **Person nodes**: Named individuals mentioned in documents

Relationships: Documents MENTIONS topics, PUBLISHED_BY organizations, MENTIONS people.

## How Queries Are Processed

1. **Entity Extraction**: We extract topics, organizations, people, dates from the query
2. **Keyword Retrieval**: Matches documents by topic/org names in Neo4j
3. **Vector Search**: Semantic similarity using embeddings (works well for conceptual queries)
4. **Graph Traversal**: Finds related documents through topic/org connections
5. **Results Fusion**: Combines results using Reciprocal Rank Fusion

## What Makes a Good Query

- **Specific topics**: "Wi-Fi 7", "802.11be", "Matter", "Thread", "6 GHz" match Topic nodes directly
- **Organization names**: "Wi-Fi Alliance", "IEEE", "Qualcomm" match Organization nodes
- **Time context**: "last month", "in 2025", "recent" helps filter by publish_date
- **Document types**: "press release", "whitepaper", "blog" can filter by category

## Knowledge Base Content

- Wi-Fi technologies: Wi-Fi 6, 6E, 7, 8 and 802.11ax, be, bn standards
- Spectrum: 6 GHz band, spectrum policy, AFC
- Features: MLO, 320 MHz, WPA3, Passpoint, EasyMesh
- Related tech: Matter, Thread, Bluetooth, 5G/6G, UWB, Zigbee
- Organizations: Wi-Fi Alliance, IEEE, 3GPP, FCC, major chip vendors

## Your Task

Improve user queries to match our retrieval better. Add specific entity names that will match our graph nodes."""

        user_prompt = f"""The user asked: "{query}"

Issues identified: {', '.join(issues) if issues else 'Query is vague'}

Suggest a revised query that would retrieve better results. Consider:
- Adding specific topic names that match our Topic nodes
- Adding organization names if relevant
- Adding time context for news/update queries
- Keep the user's original intent

Return ONLY a JSON object:
{{
  "revised_query": "<improved query>",
  "reason": "<brief explanation of why this helps retrieval>"
}}

If the query is too vague to improve meaningfully (e.g., just "hello" or "test"), return null values."""

        response = await call_llm(
            client=client,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=256,
            temperature=0.3
        )
        
        # Parse response
        import json
        content = response.content.strip()
        if content.startswith("```"):
            content = re.sub(r'^```\w*\n?', '', content)
            content = re.sub(r'\n?```$', '', content)
        
        data = json.loads(content)
        revised = data.get("revised_query")
        reason = data.get("reason")
        
        # Validate the revision is actually different and better
        if revised and revised.lower().strip() != query.lower().strip():
            return revised, reason, response.tokens_used
        
        # LLM returned null, fall back to heuristics
        logger.debug("LLM returned null revision, trying heuristics")
        heuristic_result = _heuristic_revision(query, issues)
        return heuristic_result[0], heuristic_result[1], response.tokens_used
        
    except Exception as e:
        logger.warning(f"LLM query revision failed: {e}")
        return _heuristic_revision(query, issues)


def _heuristic_revision(
    query: str,
    issues: list[str],
) -> tuple[Optional[str], Optional[str], int]:
    """
    Generate a revised query using heuristics when LLM is unavailable.
    """
    query_lower = query.lower().strip()
    query_clean = query.strip()
    
    # Handle very vague "what's new" type queries
    vague_news_patterns = ['whats new', "what's new", 'any news', 'any updates', 'anything new']
    if any(p in query_lower for p in vague_news_patterns):
        return (
            "What's new in Wi-Fi and wireless standards in the last month?",
            "Added topic focus and time context for more relevant results",
            0
        )
    
    # Add time context if missing for news-type queries
    if QUERY_ISSUES["no_timeframe"] in issues:
        news_words = ['latest', 'recent', 'new', 'update', 'news', 'announcement']
        if any(w in query_lower for w in news_words):
            revised = query_clean + " in the last month"
            return revised, "Added time context for more relevant results", 0
    
    # Handle vague queries about specific topics
    if QUERY_ISSUES["too_vague"] in issues or QUERY_ISSUES["missing_context"] in issues:
        # If it's a very short query, suggest adding time context
        if len(query_lower.split()) <= 3:
            revised = f"{query_clean} news and updates in the last month"
            return revised, "Added time context and scope for better results", 0
    
    return None, None, 0


def should_suggest_revision(analysis: QueryAnalysis) -> bool:
    """
    Determine if we should show the revision suggestion to the user.
    
    Only show when:
    - Query quality is notably poor
    - We have a meaningful revision
    - The revision is substantially different
    """
    if analysis.is_good_query:
        return False
    
    if not analysis.revised_query:
        return False
    
    if analysis.quality_score >= 0.7:
        return False
    
    # Check that revision is meaningfully different
    original = analysis.original_query.lower().strip()
    revised = analysis.revised_query.lower().strip()
    
    if original == revised:
        return False
    
    # Revision should be at least 20% different or add significant content
    if len(revised) < len(original) * 1.1 and len(revised.split()) <= len(original.split()):
        return False
    
    return True
