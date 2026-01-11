"""Confidence Scoring - Multi-factor confidence calculation for Oracle answers.

Phase 4 of Oracle Service implementation.

This module provides confidence scoring for LLM-generated answers to help users
assess reliability. The score considers multiple factors including document
coverage, source quality, recency, consensus, and query match.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import re
from typing import Optional

from src.models.response import Document, Citation, QueryIntent

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceFactors:
    """Individual factors contributing to confidence score."""
    document_coverage: float = 0.0  # How well citations cover the answer (30%)
    source_quality: float = 0.0  # Average relevance of cited documents (25%)
    recency: float = 0.0  # How recent are the source documents (20%)
    consensus: float = 0.0  # Do multiple documents agree (15%)
    query_match: float = 0.0  # How well documents match query intent (10%)


@dataclass
class ConfidenceScore:
    """Result of confidence calculation."""
    score: float
    level: str  # "high", "medium", "low"
    factors: ConfidenceFactors
    explanation: str
    warnings: list[str] = field(default_factory=list)


# Weights for each factor (must sum to 1.0)
FACTOR_WEIGHTS = {
    "document_coverage": 0.30,
    "source_quality": 0.25,
    "recency": 0.20,
    "consensus": 0.15,
    "query_match": 0.10,
}

# Hedging phrases that indicate uncertainty
HEDGING_PHRASES = [
    "i'm not sure",
    "it's unclear",
    "may or may not",
    "possibly",
    "perhaps",
    "might be",
    "could be",
    "insufficient information",
    "cannot determine",
    "no information available",
    "unable to find",
    "not enough data",
    "limited information",
    "uncertain",
]


def calculate_confidence(
    answer: str,
    documents: list[Document],
    citations: list[Citation],
    query: str,
    intent: QueryIntent,
) -> ConfidenceScore:
    """
    Calculate a multi-factor confidence score for a generated answer.
    
    The confidence score helps users understand how reliable the answer is
    based on the quality and coverage of source documents.
    
    Args:
        answer: The generated answer text
        documents: Retrieved documents used for the answer
        citations: Citations extracted from the answer
        query: Original user query
        intent: Classified query intent
        
    Returns:
        ConfidenceScore with breakdown of factors
    """
    if not documents:
        return ConfidenceScore(
            score=0.0,
            level="low",
            factors=ConfidenceFactors(),
            explanation="No documents available to support the answer.",
            warnings=["No source documents found"]
        )
    
    if not answer or answer.strip() == "":
        return ConfidenceScore(
            score=0.0,
            level="low",
            factors=ConfidenceFactors(),
            explanation="No answer was generated.",
            warnings=["Empty answer"]
        )
    
    factors = ConfidenceFactors()
    warnings = []
    
    # Factor 1: Document Coverage (30%)
    # Measures how many documents are cited relative to what's available
    factors.document_coverage = _calculate_document_coverage(
        answer, documents, citations
    )
    if factors.document_coverage < 0.3:
        warnings.append("Answer cites few sources")
    
    # Factor 2: Source Quality (25%)
    # Average relevance score of cited documents
    factors.source_quality = _calculate_source_quality(documents, citations)
    if factors.source_quality < 0.5:
        warnings.append("Source documents have low relevance scores")
    
    # Factor 3: Recency (20%)
    # How recent are the source documents
    factors.recency = _calculate_recency_score(documents, citations)
    if factors.recency < 0.3:
        warnings.append("Source documents may be outdated")
    
    # Factor 4: Consensus (15%)
    # Do multiple documents agree on key points
    factors.consensus = _calculate_consensus_score(answer, documents, citations)
    if factors.consensus < 0.3:
        warnings.append("Limited consensus across sources")
    
    # Factor 5: Query Match (10%)
    # How well do documents match the query intent
    factors.query_match = _calculate_query_match_score(
        query, documents, intent
    )
    
    # Calculate weighted total
    total_score = (
        factors.document_coverage * FACTOR_WEIGHTS["document_coverage"] +
        factors.source_quality * FACTOR_WEIGHTS["source_quality"] +
        factors.recency * FACTOR_WEIGHTS["recency"] +
        factors.consensus * FACTOR_WEIGHTS["consensus"] +
        factors.query_match * FACTOR_WEIGHTS["query_match"]
    )
    
    # Apply hedging penalty
    hedging_penalty = _calculate_hedging_penalty(answer)
    if hedging_penalty > 0:
        total_score = max(0.1, total_score - hedging_penalty)
        if hedging_penalty > 0.1:
            warnings.append("Answer contains uncertainty language")
    
    # Clamp score to valid range
    total_score = max(0.0, min(1.0, total_score))
    
    # Determine confidence level
    if total_score >= 0.75:
        level = "high"
    elif total_score >= 0.5:
        level = "medium"
    else:
        level = "low"
    
    # Generate explanation
    explanation = _generate_explanation(total_score, factors, warnings)
    
    return ConfidenceScore(
        score=round(total_score, 3),
        level=level,
        factors=factors,
        explanation=explanation,
        warnings=warnings
    )


def _calculate_document_coverage(
    answer: str,
    documents: list[Document],
    citations: list[Citation],
) -> float:
    """
    Calculate how well citations cover the answer.
    
    Considers:
    - Number of unique documents cited
    - Distribution of citations across documents
    - Ratio of cited to available documents
    """
    if not citations:
        # Check if answer references documents without formal citations
        doc_references = len(re.findall(r'\[\d+\]', answer))
        if doc_references == 0:
            return 0.2  # Baseline for answers without citations
        return min(doc_references / min(len(documents), 5), 1.0) * 0.6
    
    # Calculate coverage ratio
    num_cited = len(set(c.document_url for c in citations))
    target_citations = min(len(documents), 5)  # Ideal: cite up to 5 documents
    
    coverage_ratio = min(num_cited / target_citations, 1.0)
    
    # Bonus for diverse citations (citing from different sources)
    unique_sources = set()
    for citation in citations:
        if citation.document_url:
            # Extract domain/source from URL
            source = citation.document_url.split('/')[2] if '/' in citation.document_url else citation.document_url
            unique_sources.add(source)
    
    diversity_bonus = min(len(unique_sources) / 3, 0.2)  # Up to 0.2 bonus
    
    return min(coverage_ratio + diversity_bonus, 1.0)


def _calculate_source_quality(
    documents: list[Document],
    citations: list[Citation],
) -> float:
    """
    Calculate average quality of source documents.
    
    Uses relevance scores of cited documents, or top documents if no citations.
    """
    if not documents:
        return 0.0
    
    if citations:
        # Get relevance scores for cited documents
        cited_urls = {c.document_url for c in citations}
        cited_docs = [d for d in documents if d.url in cited_urls]
        
        if cited_docs:
            avg_relevance = sum(d.relevance_score for d in cited_docs) / len(cited_docs)
            return min(avg_relevance, 1.0)
    
    # Fall back to top 3 documents
    top_docs = documents[:3]
    avg_relevance = sum(d.relevance_score for d in top_docs) / len(top_docs)
    return min(avg_relevance * 0.8, 1.0)  # Slight penalty for not using citations


def _calculate_recency_score(
    documents: list[Document],
    citations: list[Citation],
) -> float:
    """
    Calculate how recent the source documents are.
    
    More recent documents contribute to higher confidence.
    """
    if not documents:
        return 0.0
    
    # Get relevant documents (cited or top 5)
    if citations:
        cited_urls = {c.document_url for c in citations}
        relevant_docs = [d for d in documents if d.url in cited_urls]
    else:
        relevant_docs = documents[:5]
    
    if not relevant_docs:
        return 0.5  # Neutral score
    
    now = datetime.now()
    scores = []
    
    for doc in relevant_docs:
        if not doc.publish_date:
            scores.append(0.5)  # Unknown date gets neutral score
            continue
        
        try:
            if isinstance(doc.publish_date, str):
                pub_date = datetime.fromisoformat(doc.publish_date.replace("Z", "+00:00"))
            else:
                pub_date = doc.publish_date
            
            # Make both datetimes offset-naive for comparison
            if pub_date.tzinfo is not None:
                pub_date = pub_date.replace(tzinfo=None)
            
            days_old = (now - pub_date).days
            
            # Score based on age
            if days_old <= 30:
                scores.append(1.0)  # Very recent
            elif days_old <= 90:
                scores.append(0.8)  # Recent
            elif days_old <= 180:
                scores.append(0.6)  # Somewhat recent
            elif days_old <= 365:
                scores.append(0.4)  # Within a year
            else:
                scores.append(0.2)  # Older
                
        except (ValueError, TypeError) as e:
            logger.debug(f"Could not parse date for recency scoring: {e}")
            scores.append(0.5)
    
    return sum(scores) / len(scores) if scores else 0.5


def _calculate_consensus_score(
    answer: str,
    documents: list[Document],
    citations: list[Citation],
) -> float:
    """
    Calculate whether multiple documents agree on key points.
    
    Higher score when multiple sources provide corroborating information.
    """
    if len(documents) < 2:
        return 0.5  # Can't calculate consensus with one document
    
    # Count documents from multiple sources
    sources = {}
    for doc in documents[:10]:  # Consider top 10 documents
        if doc.source:
            sources[doc.source] = sources.get(doc.source, 0) + 1
    
    # Multiple sources is good for consensus
    num_sources = len(sources)
    
    if num_sources >= 4:
        source_score = 1.0
    elif num_sources >= 3:
        source_score = 0.8
    elif num_sources >= 2:
        source_score = 0.6
    else:
        source_score = 0.4
    
    # Check topic overlap across documents
    topic_counts = {}
    for doc in documents[:10]:
        for topic in doc.topics:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
    
    # Topics mentioned in multiple documents indicate consensus
    shared_topics = sum(1 for count in topic_counts.values() if count >= 2)
    topic_score = min(shared_topics / 3, 1.0) if topic_counts else 0.5
    
    # Combine scores
    return (source_score * 0.6) + (topic_score * 0.4)


def _calculate_query_match_score(
    query: str,
    documents: list[Document],
    intent: QueryIntent,
) -> float:
    """
    Calculate how well documents match the query intent.
    """
    if not documents:
        return 0.0
    
    query_words = set(query.lower().split())
    
    # Remove common stop words
    stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'what', 'when', 
                  'where', 'who', 'why', 'how', 'in', 'on', 'at', 'to', 'for',
                  'of', 'with', 'by', 'from', 'about', 'latest', 'recent'}
    query_words = query_words - stop_words
    
    if not query_words:
        return 0.5  # No meaningful query words
    
    # Check how many query words appear in document titles/summaries
    match_scores = []
    for doc in documents[:5]:
        doc_text = f"{doc.title or ''} {doc.summary or ''}".lower()
        matches = sum(1 for word in query_words if word in doc_text)
        match_scores.append(matches / len(query_words))
    
    avg_match = sum(match_scores) / len(match_scores) if match_scores else 0
    
    # Boost score if top documents have high relevance
    top_relevance = documents[0].relevance_score if documents else 0
    relevance_boost = top_relevance * 0.2
    
    return min(avg_match + relevance_boost, 1.0)


def _calculate_hedging_penalty(answer: str) -> float:
    """
    Calculate penalty for hedging language in the answer.
    
    Hedging indicates uncertainty and should reduce confidence.
    """
    answer_lower = answer.lower()
    
    hedging_count = sum(1 for phrase in HEDGING_PHRASES if phrase in answer_lower)
    
    # More hedging = larger penalty
    if hedging_count == 0:
        return 0.0
    elif hedging_count == 1:
        return 0.05
    elif hedging_count == 2:
        return 0.10
    else:
        return 0.15


def _generate_explanation(
    score: float,
    factors: ConfidenceFactors,
    warnings: list[str],
) -> str:
    """Generate a human-readable explanation of the confidence score."""
    
    parts = []
    
    # Overall assessment
    if score >= 0.75:
        parts.append("High confidence: Answer is well-supported by multiple relevant sources.")
    elif score >= 0.5:
        parts.append("Medium confidence: Answer has reasonable support but may benefit from additional verification.")
    else:
        parts.append("Low confidence: Answer has limited source support. Consider verifying with additional research.")
    
    # Highlight strong factors
    strong_factors = []
    if factors.source_quality >= 0.8:
        strong_factors.append("high-quality sources")
    if factors.recency >= 0.8:
        strong_factors.append("recent information")
    if factors.consensus >= 0.8:
        strong_factors.append("multiple corroborating sources")
    if factors.document_coverage >= 0.8:
        strong_factors.append("comprehensive citation coverage")
    
    if strong_factors:
        parts.append(f"Strengths: {', '.join(strong_factors)}.")
    
    # Add warnings
    if warnings:
        parts.append(f"Considerations: {'; '.join(warnings)}.")
    
    return " ".join(parts)


def interpret_confidence(score: float) -> str:
    """
    Convert confidence score to human-readable interpretation.
    
    Args:
        score: Confidence score between 0 and 1
        
    Returns:
        Human-readable interpretation string
    """
    if score >= 0.85:
        return "Very high confidence - Answer is strongly supported by multiple authoritative sources"
    elif score >= 0.75:
        return "High confidence - Answer has good source support"
    elif score >= 0.60:
        return "Moderate confidence - Answer is reasonably supported but may have gaps"
    elif score >= 0.45:
        return "Low-moderate confidence - Limited source support, verify important details"
    elif score >= 0.30:
        return "Low confidence - Answer has minimal source support"
    else:
        return "Very low confidence - Insufficient sources to verify this answer"
