"""Query Refinement Suggestions - Suggests alternative queries when results are poor.

Phase 4 of Oracle Service implementation.

This module analyzes query results and suggests alternative queries that might
yield better results. It considers the original query, retrieved documents,
and graph context to generate helpful suggestions.
"""

from dataclasses import dataclass
import logging
from typing import Optional

from src.models.response import Document, GraphContext, QuerySuggestion, QueryIntent
from src.services.llm_client import get_llm_client, call_llm
from src.settings import settings

logger = logging.getLogger(__name__)


# Suggestion types
SUGGESTION_TYPE_BROADEN = "broaden"
SUGGESTION_TYPE_NARROW = "narrow"
SUGGESTION_TYPE_RELATED = "related"
SUGGESTION_TYPE_REPHRASE = "rephrase"
SUGGESTION_TYPE_ENTITY = "entity"


@dataclass
class SuggestionContext:
    """Context for generating suggestions."""
    query: str
    documents: list[Document]
    graph_context: Optional[GraphContext]
    intent: QueryIntent
    result_count: int
    avg_relevance: float


async def suggest_refinements(
    query: str,
    documents: list[Document],
    graph_context: Optional[GraphContext],
    intent: QueryIntent,
    max_suggestions: int = 3,
) -> list[QuerySuggestion]:
    """
    Generate query refinement suggestions when results are limited or poor.
    
    Suggestions are generated based on:
    - Result count: Too few results → broaden; too many → narrow
    - Relevance scores: Low scores → rephrase or use related terms
    - Graph context: Related topics/orgs from graph
    - Query analysis: Spelling corrections, entity alternatives
    
    Args:
        query: Original user query
        documents: Retrieved documents (may be empty or low-relevance)
        graph_context: Graph context if available
        intent: Classified query intent
        max_suggestions: Maximum suggestions to return
        
    Returns:
        List of QuerySuggestion with suggestion text and reason
    """
    suggestions: list[QuerySuggestion] = []
    
    # Calculate result quality metrics
    result_count = len(documents)
    avg_relevance = (
        sum(d.relevance_score for d in documents) / result_count
        if result_count > 0 else 0.0
    )
    
    context = SuggestionContext(
        query=query,
        documents=documents,
        graph_context=graph_context,
        intent=intent,
        result_count=result_count,
        avg_relevance=avg_relevance,
    )
    
    # Don't suggest refinements if results are good
    # Good results: at least 3 documents with average relevance >= 0.7
    if result_count >= 3 and avg_relevance >= 0.7:
        return []
    
    # Generate suggestions based on result quality
    
    # 1. Too few results - suggest broader queries
    if result_count < 3:
        broader_suggestions = _suggest_broader_queries(context)
        suggestions.extend(broader_suggestions)
    
    # 2. Low relevance - suggest rephrased queries
    if result_count > 0 and avg_relevance < 0.5:
        rephrase_suggestions = _suggest_rephrased_queries(context)
        suggestions.extend(rephrase_suggestions)
    
    # 3. Suggest related entities from graph context
    if graph_context:
        entity_suggestions = _suggest_from_graph_context(context)
        suggestions.extend(entity_suggestions)
    
    # 4. Suggest based on document topics
    if documents:
        topic_suggestions = _suggest_from_topics(context)
        suggestions.extend(topic_suggestions)
    
    # 5. If still no suggestions and results are poor, use LLM
    if len(suggestions) < 2 and (result_count == 0 or avg_relevance < 0.4):
        llm_suggestions = await _generate_llm_suggestions(context)
        suggestions.extend(llm_suggestions)
    
    # Deduplicate and limit suggestions
    unique_suggestions = _deduplicate_suggestions(suggestions)
    
    return unique_suggestions[:max_suggestions]


def _suggest_broader_queries(context: SuggestionContext) -> list[QuerySuggestion]:
    """Generate suggestions for broadening the query."""
    suggestions = []
    query_lower = context.query.lower()
    
    # Remove date qualifiers to broaden
    date_terms = ["this week", "this month", "today", "yesterday", "recent", "latest", "last week", "last month"]
    for term in date_terms:
        if term in query_lower:
            broader_query = query_lower.replace(term, "").strip()
            if len(broader_query) > 5:
                suggestions.append(QuerySuggestion(
                    suggestion=broader_query.title(),
                    reason=f"Remove '{term}' to search all time periods"
                ))
                break
    
    # Remove specific qualifiers
    specificity_terms = ["specific", "exactly", "only", "just"]
    for term in specificity_terms:
        if term in query_lower:
            broader_query = query_lower.replace(term, "").strip()
            suggestions.append(QuerySuggestion(
                suggestion=broader_query,
                reason=f"Remove '{term}' to broaden search"
            ))
            break
    
    # Suggest removing quotation marks if present
    if '"' in context.query or "'" in context.query:
        suggestions.append(QuerySuggestion(
            suggestion=context.query.replace('"', '').replace("'", ''),
            reason="Remove quotes to allow partial matches"
        ))
    
    return suggestions[:2]


def _suggest_rephrased_queries(context: SuggestionContext) -> list[QuerySuggestion]:
    """Generate suggestions for rephrasing the query."""
    suggestions = []
    query_lower = context.query.lower()
    
    # Common rephrasing patterns
    rephrasings = {
        "what is": "explain",
        "what are": "list",
        "how do": "guide for",
        "how to": "steps for",
        "why": "reasons for",
        "when did": "timeline of",
        "who is": "information about",
    }
    
    for pattern, replacement in rephrasings.items():
        if query_lower.startswith(pattern):
            rephrased = query_lower.replace(pattern, replacement, 1)
            suggestions.append(QuerySuggestion(
                suggestion=rephrased.capitalize(),
                reason=f"Try '{replacement}' instead of '{pattern}'"
            ))
            break
    
    # Suggest removing question words for direct search
    question_words = ["what", "how", "why", "when", "where", "who", "which"]
    words = query_lower.split()
    if words and words[0] in question_words:
        direct_query = " ".join(words[1:])
        if len(direct_query) > 3:
            suggestions.append(QuerySuggestion(
                suggestion=direct_query.capitalize(),
                reason="Try a direct search without question format"
            ))
    
    return suggestions[:2]


def _suggest_from_graph_context(context: SuggestionContext) -> list[QuerySuggestion]:
    """Generate suggestions from graph context (related topics, orgs)."""
    suggestions = []
    
    if not context.graph_context:
        return suggestions
    
    gc = context.graph_context
    query_lower = context.query.lower()
    
    # Suggest related topics not in the original query
    for topic in gc.central_topics[:3]:
        if topic.lower() not in query_lower and len(topic) > 2:
            suggestions.append(QuerySuggestion(
                suggestion=f"{context.query} {topic}",
                reason=f"Add related topic '{topic}'"
            ))
    
    # Suggest related organizations
    for org in gc.key_organizations[:2]:
        if org.lower() not in query_lower and len(org) > 2:
            suggestions.append(QuerySuggestion(
                suggestion=f"{org} {context.query}",
                reason=f"Focus on organization '{org}'"
            ))
    
    # Suggest related entities
    for entity in gc.related_entities[:2]:
        if entity.name.lower() not in query_lower:
            suggestions.append(QuerySuggestion(
                suggestion=f"{context.query} {entity.name}",
                reason=f"Include related {entity.type} '{entity.name}'"
            ))
    
    return suggestions[:2]


def _suggest_from_topics(context: SuggestionContext) -> list[QuerySuggestion]:
    """Generate suggestions based on topics found in retrieved documents."""
    suggestions = []
    
    if not context.documents:
        return suggestions
    
    query_lower = context.query.lower()
    
    # Collect topics from documents
    topic_counts: dict[str, int] = {}
    for doc in context.documents[:10]:
        for topic in doc.topics:
            if topic.lower() not in query_lower:
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
    
    # Suggest most common topics not in query
    sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)
    
    for topic, count in sorted_topics[:2]:
        if count >= 2:
            suggestions.append(QuerySuggestion(
                suggestion=f"{topic}",
                reason=f"Try searching for '{topic}' (found in {count} results)"
            ))
    
    return suggestions


async def _generate_llm_suggestions(context: SuggestionContext) -> list[QuerySuggestion]:
    """Use LLM to generate query suggestions when heuristics fail."""
    client = get_llm_client()
    
    if client is None:
        return []
    
    try:
        # Build context about what was found
        doc_info = ""
        if context.documents:
            topics = set()
            orgs = set()
            for doc in context.documents[:5]:
                topics.update(doc.topics)
                orgs.update(doc.organizations)
            
            doc_info = f"""
Found {context.result_count} documents with average relevance {context.avg_relevance:.2f}.
Topics in results: {', '.join(list(topics)[:10])}
Organizations in results: {', '.join(list(orgs)[:5])}
"""
        else:
            doc_info = "No documents were found for this query."
        
        messages = [
            {
                "role": "system",
                "content": """You are a search assistant helping users refine their queries.
Given a query that returned poor results, suggest 2-3 alternative queries.

Return suggestions in this exact format (one per line):
SUGGESTION: <alternative query> | REASON: <brief explanation>

Keep suggestions concise and focused on the user's likely intent."""
            },
            {
                "role": "user",
                "content": f"""Original query: "{context.query}"
Intent type: {context.intent.value}
{doc_info}

Suggest alternative queries that might yield better results."""
            }
        ]
        
        response = await call_llm(
            client=client,
            messages=messages,
            max_tokens=200,
            temperature=0.7
        )
        
        # Parse response
        suggestions = []
        for line in response.content.strip().split('\n'):
            if 'SUGGESTION:' in line and 'REASON:' in line:
                try:
                    parts = line.split('|')
                    suggestion_part = parts[0].replace('SUGGESTION:', '').strip()
                    reason_part = parts[1].replace('REASON:', '').strip() if len(parts) > 1 else "Alternative phrasing"
                    
                    if suggestion_part and len(suggestion_part) > 3:
                        suggestions.append(QuerySuggestion(
                            suggestion=suggestion_part,
                            reason=reason_part
                        ))
                except (IndexError, ValueError):
                    continue
        
        return suggestions[:2]
        
    except Exception as e:
        logger.warning(f"LLM suggestion generation failed: {e}")
        return []


def _deduplicate_suggestions(suggestions: list[QuerySuggestion]) -> list[QuerySuggestion]:
    """Remove duplicate suggestions based on normalized text."""
    seen = set()
    unique = []
    
    for suggestion in suggestions:
        normalized = suggestion.suggestion.lower().strip()
        if normalized not in seen:
            seen.add(normalized)
            unique.append(suggestion)
    
    return unique


def should_show_suggestions(
    documents: list[Document],
    min_results: int = 3,
    min_relevance: float = 0.5,
) -> bool:
    """
    Determine if query refinement suggestions should be shown.
    
    Args:
        documents: Retrieved documents
        min_results: Minimum results to consider "good enough"
        min_relevance: Minimum average relevance to consider "good enough"
        
    Returns:
        True if suggestions would be helpful
    """
    if len(documents) < min_results:
        return True
    
    if not documents:
        return True
    
    avg_relevance = sum(d.relevance_score for d in documents) / len(documents)
    if avg_relevance < min_relevance:
        return True
    
    return False
