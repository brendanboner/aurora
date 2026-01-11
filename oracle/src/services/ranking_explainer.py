"""Ranking Explainability - Explains why documents were ranked at their positions.

Phase 4 of Oracle Service implementation.

This module provides human-readable explanations for document rankings,
helping users understand why specific results appear at certain positions.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Optional

from src.models.response import Document, QueryIntent

logger = logging.getLogger(__name__)


@dataclass
class RankingFactor:
    """A factor contributing to a document's ranking."""
    name: str
    weight: float  # 0.0 to 1.0
    score: float  # 0.0 to 1.0
    description: str
    positive: bool = True  # Whether this factor helped or hurt ranking


@dataclass
class RankingExplanation:
    """Detailed explanation of why a document was ranked at its position."""
    rank: int
    relevance_score: float
    keyword_rank: Optional[int]
    vector_rank: Optional[int]
    graph_rank: Optional[int]
    factors: list[RankingFactor]
    match_reasons: list[str]  # Combined reasons for display
    rrf_reasons: list[str]  # Original reasons from RRF fusion (actual retrieval)
    computed_reasons: list[str]  # Reasons computed by explainer (analysis)
    summary: str


def explain_ranking(
    document: Document,
    rank: int,
    query: str,
    intent: QueryIntent,
    retrieval_metadata: Optional[dict] = None,
) -> RankingExplanation:
    """
    Generate a detailed explanation of why a document was ranked at its position.
    
    Args:
        document: The document to explain
        rank: The document's position in results (1-indexed)
        query: Original search query
        intent: Classified query intent
        retrieval_metadata: Optional metadata from retrieval (keyword_rank, vector_rank, etc.)
        
    Returns:
        RankingExplanation with factors and summary
    """
    factors: list[RankingFactor] = []
    
    # Extract retrieval-specific ranks if available
    keyword_rank = None
    vector_rank = None
    graph_rank = None
    
    if retrieval_metadata:
        keyword_rank = retrieval_metadata.get("keyword_rank")
        vector_rank = retrieval_metadata.get("vector_rank")
        graph_rank = retrieval_metadata.get("graph_rank")
    
    # Factor 1: Overall relevance score
    relevance_factor = _analyze_relevance(document)
    factors.append(relevance_factor)
    
    # Factor 2: Keyword match
    keyword_factor = _analyze_keyword_match(document, query, keyword_rank)
    factors.append(keyword_factor)
    
    # Factor 3: Semantic similarity (vector search)
    if vector_rank is not None:
        vector_factor = _analyze_vector_match(document, vector_rank)
        factors.append(vector_factor)
    
    # Factor 4: Graph relationships
    if graph_rank is not None:
        graph_factor = _analyze_graph_match(document, graph_rank)
        factors.append(graph_factor)
    
    # Factor 5: Recency
    recency_factor = _analyze_recency(document)
    factors.append(recency_factor)
    
    # Factor 6: Topic match
    topic_factor = _analyze_topic_match(document, query, intent)
    factors.append(topic_factor)
    
    # Factor 7: Organization relevance
    org_factor = _analyze_org_match(document, query)
    if org_factor:
        factors.append(org_factor)
    
    # Separate RRF reasons (from actual retrieval) from computed reasons (our analysis)
    rrf_reasons = list(document.match_reasons)  # Original from RRF fusion
    computed_reasons = _generate_computed_reasons(document, factors, keyword_rank, vector_rank, graph_rank)
    
    # Combined reasons for display (RRF first, then computed extras)
    match_reasons = _combine_reasons(rrf_reasons, computed_reasons)
    
    # Generate summary
    summary = _generate_summary(document, rank, factors)
    
    return RankingExplanation(
        rank=rank,
        relevance_score=document.relevance_score,
        keyword_rank=keyword_rank,
        vector_rank=vector_rank,
        graph_rank=graph_rank,
        factors=factors,
        match_reasons=match_reasons,
        rrf_reasons=rrf_reasons,
        computed_reasons=computed_reasons,
        summary=summary,
    )


def _analyze_relevance(document: Document) -> RankingFactor:
    """Analyze the overall relevance score contribution."""
    score = document.relevance_score
    
    if score >= 0.9:
        desc = "Extremely high relevance score from retrieval"
    elif score >= 0.75:
        desc = "Very high relevance score"
    elif score >= 0.6:
        desc = "Good relevance score"
    elif score >= 0.4:
        desc = "Moderate relevance score"
    else:
        desc = "Lower relevance score"
    
    return RankingFactor(
        name="Relevance Score",
        weight=0.35,
        score=score,
        description=desc,
        positive=score >= 0.5
    )


def _analyze_keyword_match(
    document: Document,
    query: str,
    keyword_rank: Optional[int],
) -> RankingFactor:
    """Analyze keyword match contribution."""
    query_words = set(query.lower().split())
    
    # Remove stop words
    stop_words = {'the', 'a', 'an', 'is', 'are', 'what', 'how', 'why', 'when', 
                  'where', 'who', 'in', 'on', 'at', 'to', 'for', 'of', 'with'}
    query_words = query_words - stop_words
    
    # Check title and summary for keyword presence
    doc_text = f"{document.title or ''} {document.summary or ''}".lower()
    
    matches = sum(1 for word in query_words if word in doc_text)
    match_ratio = matches / len(query_words) if query_words else 0
    
    # Incorporate keyword rank if available
    if keyword_rank:
        if keyword_rank <= 5:
            rank_boost = 0.3
            rank_desc = f"Top keyword match (#{keyword_rank})"
        elif keyword_rank <= 15:
            rank_boost = 0.15
            rank_desc = f"Strong keyword match (#{keyword_rank})"
        else:
            rank_boost = 0
            rank_desc = f"Keyword match (#{keyword_rank})"
        
        score = min((match_ratio * 0.7) + rank_boost, 1.0)
        desc = rank_desc
    else:
        score = match_ratio
        if match_ratio >= 0.8:
            desc = "Strong keyword overlap with query"
        elif match_ratio >= 0.5:
            desc = "Partial keyword match"
        elif match_ratio > 0:
            desc = "Some keyword matches"
        else:
            desc = "No direct keyword matches"
    
    return RankingFactor(
        name="Keyword Match",
        weight=0.25,
        score=score,
        description=desc,
        positive=score >= 0.3
    )


def _analyze_vector_match(
    document: Document,
    vector_rank: int,
) -> RankingFactor:
    """Analyze semantic similarity contribution."""
    if vector_rank <= 3:
        score = 0.95
        desc = f"Top semantic match (#{vector_rank}) - Very similar meaning"
    elif vector_rank <= 10:
        score = 0.80
        desc = f"Strong semantic similarity (#{vector_rank})"
    elif vector_rank <= 25:
        score = 0.60
        desc = f"Good semantic similarity (#{vector_rank})"
    elif vector_rank <= 50:
        score = 0.40
        desc = f"Moderate semantic similarity (#{vector_rank})"
    else:
        score = 0.20
        desc = f"Lower semantic similarity (#{vector_rank})"
    
    return RankingFactor(
        name="Semantic Similarity",
        weight=0.25,
        score=score,
        description=desc,
        positive=score >= 0.4
    )


def _analyze_graph_match(
    document: Document,
    graph_rank: int,
) -> RankingFactor:
    """Analyze graph relationship contribution."""
    if graph_rank <= 3:
        score = 0.90
        desc = f"Top graph match (#{graph_rank}) - Strong relationship connections"
    elif graph_rank <= 10:
        score = 0.75
        desc = f"Strong graph relationships (#{graph_rank})"
    elif graph_rank <= 25:
        score = 0.55
        desc = f"Good graph connections (#{graph_rank})"
    else:
        score = 0.35
        desc = f"Some graph relationships (#{graph_rank})"
    
    return RankingFactor(
        name="Graph Relationships",
        weight=0.15,
        score=score,
        description=desc,
        positive=score >= 0.4
    )


def _analyze_recency(document: Document) -> RankingFactor:
    """Analyze recency contribution to ranking."""
    if not document.publish_date:
        return RankingFactor(
            name="Recency",
            weight=0.10,
            score=0.5,
            description="Publication date unknown",
            positive=True  # Neutral
        )
    
    try:
        if isinstance(document.publish_date, str):
            pub_date = datetime.fromisoformat(document.publish_date.replace("Z", "+00:00"))
        else:
            pub_date = document.publish_date
        
        # Make offset-naive for comparison
        if pub_date.tzinfo is not None:
            pub_date = pub_date.replace(tzinfo=None)
        
        now = datetime.now()
        days_old = (now - pub_date).days
        
        if days_old <= 7:
            score = 1.0
            desc = "Published within the last week"
        elif days_old <= 30:
            score = 0.9
            desc = "Published within the last month"
        elif days_old <= 90:
            score = 0.7
            desc = "Published within the last 3 months"
        elif days_old <= 180:
            score = 0.5
            desc = "Published within the last 6 months"
        elif days_old <= 365:
            score = 0.3
            desc = "Published within the last year"
        else:
            score = 0.15
            desc = f"Published {days_old // 365} year(s) ago"
        
        return RankingFactor(
            name="Recency",
            weight=0.10,
            score=score,
            description=desc,
            positive=score >= 0.5
        )
        
    except (ValueError, TypeError) as e:
        logger.debug(f"Could not analyze recency: {e}")
        return RankingFactor(
            name="Recency",
            weight=0.10,
            score=0.5,
            description="Could not determine recency",
            positive=True
        )


def _analyze_topic_match(
    document: Document,
    query: str,
    intent: QueryIntent,
) -> RankingFactor:
    """Analyze topic relevance to query."""
    if not document.topics:
        return RankingFactor(
            name="Topic Match",
            weight=0.10,
            score=0.3,
            description="No topics associated with document",
            positive=False
        )
    
    query_lower = query.lower()
    
    # Check how many document topics appear in query
    matching_topics = [t for t in document.topics if t.lower() in query_lower]
    
    if matching_topics:
        score = min(len(matching_topics) * 0.35, 1.0)
        if len(matching_topics) >= 2:
            desc = f"Multiple topic matches: {', '.join(matching_topics[:3])}"
        else:
            desc = f"Topic match: {matching_topics[0]}"
    else:
        # Partial matches (topic words in query)
        topic_words = set()
        for topic in document.topics:
            topic_words.update(topic.lower().split())
        
        query_words = set(query_lower.split())
        overlap = topic_words & query_words
        
        if overlap:
            score = min(len(overlap) * 0.2, 0.6)
            desc = f"Related topics: {', '.join(document.topics[:2])}"
        else:
            score = 0.2
            desc = f"Topics: {', '.join(document.topics[:2])}"
    
    return RankingFactor(
        name="Topic Match",
        weight=0.10,
        score=score,
        description=desc,
        positive=score >= 0.4
    )


def _analyze_org_match(
    document: Document,
    query: str,
) -> Optional[RankingFactor]:
    """Analyze organization relevance to query."""
    if not document.organizations:
        return None
    
    query_lower = query.lower()
    
    # Check for organization mentions in query
    matching_orgs = [
        org for org in document.organizations 
        if org.lower() in query_lower or any(word in query_lower for word in org.lower().split())
    ]
    
    if matching_orgs:
        score = min(len(matching_orgs) * 0.4, 1.0)
        desc = f"Mentions queried organization: {matching_orgs[0]}"
        positive = True
    else:
        score = 0.3
        desc = f"From: {document.organizations[0]}"
        positive = True  # Still somewhat relevant
    
    return RankingFactor(
        name="Organization",
        weight=0.05,
        score=score,
        description=desc,
        positive=positive
    )


def _generate_computed_reasons(
    document: Document,
    factors: list[RankingFactor],
    keyword_rank: Optional[int],
    vector_rank: Optional[int],
    graph_rank: Optional[int],
) -> list[str]:
    """
    Generate computed reasons based on our factor analysis.
    
    These are COMPUTED by the explainer, not from actual retrieval.
    They provide additional context about why a document might be relevant.
    """
    reasons = []
    
    for factor in factors:
        if factor.positive and factor.score >= 0.6:
            # Create a reason from the factor with [Computed] prefix
            if factor.name == "Recency":
                reasons.append(f"📅 {factor.description}")
            elif factor.name == "Topic Match":
                reasons.append(f"🏷️ {factor.description}")
            elif factor.name == "Organization":
                reasons.append(f"🏢 {factor.description}")
            elif factor.name == "Relevance Score" and factor.score >= 0.8:
                reasons.append(f"⭐ {factor.description}")
    
    return reasons


def _combine_reasons(
    rrf_reasons: list[str],
    computed_reasons: list[str],
) -> list[str]:
    """
    Combine RRF reasons and computed reasons for display.
    
    RRF reasons come first (they're from actual retrieval),
    then computed reasons (our analysis) are added if not redundant.
    """
    combined = []
    
    # Add RRF reasons first (these are from actual retrieval)
    for reason in rrf_reasons:
        combined.append(reason)
    
    # Add computed reasons that aren't redundant
    rrf_lower = " ".join(r.lower() for r in rrf_reasons)
    
    for reason in computed_reasons:
        # Skip if similar content already in RRF reasons
        reason_key = reason.lower().replace("📅", "").replace("🏷️", "").replace("🏢", "").replace("⭐", "").strip()
        if reason_key[:20] not in rrf_lower:
            combined.append(reason)
    
    # Limit to top 5 reasons
    return combined[:5]


def _generate_match_reasons(
    document: Document,
    factors: list[RankingFactor],
    keyword_rank: Optional[int],
    vector_rank: Optional[int],
    graph_rank: Optional[int],
) -> list[str]:
    """
    Legacy function - generates match reasons.
    
    DEPRECATED: Use _generate_computed_reasons and _combine_reasons instead.
    Kept for backward compatibility.
    """
    reasons = []
    
    # Start with existing match reasons from document
    reasons.extend(document.match_reasons)
    
    # Add factor-based reasons if not already covered
    existing_lower = [r.lower() for r in reasons]
    
    for factor in factors:
        if factor.positive and factor.score >= 0.6:
            # Create a simple reason from the factor
            if factor.name == "Recency" and "recent" not in " ".join(existing_lower):
                reasons.append(f"📅 {factor.description}")
            elif factor.name == "Topic Match" and "topic" not in " ".join(existing_lower):
                reasons.append(f"🏷️ {factor.description}")
            elif factor.name == "Organization" and "organization" not in " ".join(existing_lower):
                reasons.append(f"🏢 {factor.description}")
    
    # Limit to top 5 reasons
    return reasons[:5]


def _generate_summary(
    document: Document,
    rank: int,
    factors: list[RankingFactor],
) -> str:
    """Generate a summary explanation for the ranking."""
    # Find top contributing factors
    sorted_factors = sorted(
        factors, 
        key=lambda f: f.score * f.weight, 
        reverse=True
    )
    
    top_factors = [f for f in sorted_factors[:3] if f.positive and f.score >= 0.5]
    
    if not top_factors:
        return f"Ranked #{rank} with relevance score {document.relevance_score:.2f}"
    
    # Build summary
    parts = [f"Ranked #{rank}"]
    
    factor_descriptions = []
    for factor in top_factors:
        if factor.name == "Relevance Score":
            continue  # Skip generic relevance
        factor_descriptions.append(factor.description.lower())
    
    if factor_descriptions:
        parts.append(f"due to: {'; '.join(factor_descriptions)}")
    
    parts.append(f"(score: {document.relevance_score:.2f})")
    
    return " ".join(parts)


def add_explanations_to_documents(
    documents: list[Document],
    query: str,
    intent: QueryIntent,
    retrieval_data: Optional[dict] = None,
) -> list[Document]:
    """
    Add ranking explanations to a list of documents.
    
    Enriches each document's match_reasons field with detailed explanations.
    
    Args:
        documents: List of documents to explain
        query: Original search query
        intent: Classified query intent
        retrieval_data: Optional dict mapping URLs to retrieval metadata
        
    Returns:
        Documents with enriched match_reasons
    """
    retrieval_data = retrieval_data or {}
    
    for rank, doc in enumerate(documents, start=1):
        metadata = retrieval_data.get(doc.url, {})
        
        explanation = explain_ranking(
            document=doc,
            rank=rank,
            query=query,
            intent=intent,
            retrieval_metadata=metadata,
        )
        
        # Update document match reasons
        doc.match_reasons = explanation.match_reasons
    
    return documents


def get_ranking_breakdown(
    documents: list[Document],
    query: str,
    intent: QueryIntent,
    retrieval_data: Optional[dict] = None,
    max_documents: int = 10,
) -> list[dict]:
    """
    Get detailed ranking breakdown for top documents.
    
    Returns a list of dictionaries with full ranking analysis for each document.
    Useful for debugging or detailed explainability endpoints.
    
    Args:
        documents: List of documents to analyze
        query: Original search query
        intent: Classified query intent
        retrieval_data: Optional dict mapping URLs to retrieval metadata
        max_documents: Maximum documents to analyze
        
    Returns:
        List of ranking breakdown dictionaries
    """
    retrieval_data = retrieval_data or {}
    breakdowns = []
    
    for rank, doc in enumerate(documents[:max_documents], start=1):
        metadata = retrieval_data.get(doc.url, {})
        
        explanation = explain_ranking(
            document=doc,
            rank=rank,
            query=query,
            intent=intent,
            retrieval_metadata=metadata,
        )
        
        breakdown = {
            "rank": rank,
            "url": doc.url,
            "title": doc.title,
            "relevance_score": doc.relevance_score,
            "summary": explanation.summary,
            "match_reasons": explanation.match_reasons,  # Combined for display
            "rrf_reasons": explanation.rrf_reasons,  # From actual RRF retrieval
            "computed_reasons": explanation.computed_reasons,  # From our factor analysis
            "factors": [
                {
                    "name": f.name,
                    "score": round(f.score, 3),
                    "weight": f.weight,
                    "weighted_contribution": round(f.score * f.weight, 3),
                    "description": f.description,
                    "positive": f.positive,
                }
                for f in explanation.factors
            ],
            "retrieval_ranks": {
                "keyword": explanation.keyword_rank,
                "vector": explanation.vector_rank,
                "graph": explanation.graph_rank,
            }
        }
        
        breakdowns.append(breakdown)
    
    return breakdowns
