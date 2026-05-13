"""Oracle Service - Pydantic response models."""

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
from enum import Enum


class QueryIntent(str, Enum):
    """Types of query intent for routing."""
    ENTITY_FOCUSED = "entity_focused"
    TOPIC_DISCOVERY = "topic_discovery"
    RELATIONSHIP_QUERY = "relationship_query"
    TREND_ANALYSIS = "trend_analysis"
    COMPARATIVE = "comparative"


class Document(BaseModel):
    """A retrieved document with metadata."""
    url: str = Field(..., description="Document URL")
    title: Optional[str] = Field(default=None, description="Document title")
    summary: Optional[str] = Field(default=None, description="Document summary")
    publish_date: Optional[str] = Field(default=None, description="Publication date (ISO format)")
    temporal_confidence: Optional[str] = Field(default="high", description="'high' = valid publish_date found; 'low' = no reliable date")
    source: Optional[str] = Field(default=None, description="Source organization or website")
    category: Optional[str] = Field(default=None, description="Document category")
    datasource_id: Optional[str] = Field(default=None, description="Datasource identifier (e.g., 'wfa', 'wfa_causeway')")
    topics: list[str] = Field(default_factory=list, description="Related topics")
    organizations: list[str] = Field(default_factory=list, description="Mentioned organizations")
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Relevance score (0-1)")
    match_reasons: list[str] = Field(default_factory=list, description="Why this document was matched")


class Citation(BaseModel):
    """A citation reference in an answer."""
    index: int = Field(..., description="Citation index (1-based)")
    document_url: str = Field(..., description="URL of the cited document")
    title: Optional[str] = Field(default=None, description="Document title")
    excerpt: Optional[str] = Field(default=None, description="Relevant excerpt from document")


class RelatedEntity(BaseModel):
    """An entity related to the query results."""
    name: str = Field(..., description="Entity name")
    type: str = Field(..., description="Entity type (topic, organization, person)")
    relevance: float = Field(default=0.0, description="Relevance to query")


class GraphContext(BaseModel):
    """Graph-structured context around retrieved documents."""
    central_topics: list[str] = Field(default_factory=list, description="Main topics in results")
    key_organizations: list[str] = Field(default_factory=list, description="Key organizations mentioned")
    key_people: list[str] = Field(default_factory=list, description="Key people mentioned")
    related_entities: list[RelatedEntity] = Field(default_factory=list, description="Related entities")
    temporal_patterns: Optional[str] = Field(default=None, description="Observed temporal patterns")


class RetrievalMetadata(BaseModel):
    """Metadata about the retrieval process."""
    intent: QueryIntent = Field(..., description="Classified query intent")
    intent_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in intent classification")
    strategies_used: list[str] = Field(default_factory=list, description="Retrieval strategies applied")
    total_candidates: int = Field(default=0, description="Total documents considered")
    processing_time_ms: int = Field(default=0, description="Total processing time in milliseconds")
    llm_tokens_used: Optional[int] = Field(default=None, description="LLM tokens consumed")
    cache_hit: bool = Field(default=False, description="Whether any fast cache layer was hit")
    route_cache_hit: bool = Field(default=False, description="Whether route planning came from cache")
    result_cache_hit: bool = Field(default=False, description="Whether retrieval results came from cache")
    answer_cache_hit: bool = Field(default=False, description="Whether the final answer came from cache")
    cache_bypass_reason: Optional[str] = Field(default=None, description="Why a cache layer was intentionally bypassed")


class QuerySuggestion(BaseModel):
    """A suggested query refinement."""
    suggestion: str = Field(..., description="Suggested query text")
    reason: str = Field(..., description="Why this might help")


class QueryResponse(BaseModel):
    """Response model for /oracle/query endpoint."""
    query_id: Optional[str] = Field(default=None, description="Unique query ID for feedback")
    mode: Literal["retrieval", "answer"] = Field(..., description="Response mode used")
    answer: Optional[str] = Field(default=None, description="Generated answer (answer mode only)")
    citations: list[Citation] = Field(default_factory=list, description="Citations for answer")
    documents: list[Document] = Field(default_factory=list, description="Retrieved documents")
    graph_context: Optional[GraphContext] = Field(default=None, description="Graph context information")
    metadata: RetrievalMetadata = Field(..., description="Retrieval metadata")
    suggestions: list[QuerySuggestion] = Field(default_factory=list, description="Query refinement suggestions")
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Answer confidence (answer mode)")
    personalization_applied: bool = Field(default=False, description="Whether personalization was applied to the answer")
    pipeline: Optional[Literal["fast", "baseline"]] = Field(default=None, description="Pipeline used for query execution")
    
    class Config:
        json_schema_extra = {
            "example": {
                "mode": "answer",
                "answer": "Based on recent documents, Wi-Fi 7 (802.11be) certification...",
                "citations": [
                    {
                        "index": 1,
                        "document_url": "https://example.com/doc1",
                        "title": "Wi-Fi 7 Certification Launch",
                        "excerpt": "The Wi-Fi Alliance announced..."
                    }
                ],
                "documents": [
                    {
                        "url": "https://example.com/doc1",
                        "title": "Wi-Fi 7 Certification Launch",
                        "summary": "Wi-Fi Alliance launches Wi-Fi 7 certification...",
                        "publish_date": "2024-01-15",
                        "topics": ["Wi-Fi 7", "802.11be"],
                        "organizations": ["Wi-Fi Alliance"],
                        "relevance_score": 0.95
                    }
                ],
                "graph_context": {
                    "central_topics": ["Wi-Fi 7", "802.11be"],
                    "key_organizations": ["Wi-Fi Alliance", "IEEE"],
                    "key_people": [],
                    "related_entities": []
                },
                "metadata": {
                    "intent": "topic_discovery",
                    "intent_confidence": 0.92,
                    "strategies_used": ["keyword", "graph"],
                    "total_candidates": 45,
                    "processing_time_ms": 1250
                },
                "suggestions": [],
                "confidence_score": 0.88
            }
        }


class DirectQuote(BaseModel):
    """A direct quote extracted from document content."""
    text: str = Field(..., description="The exact quote text")
    source_url: str = Field(..., description="URL of the source document")
    source_title: Optional[str] = Field(default=None, description="Title of source document")
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Relevance to the question")


class EnhanceMetadata(BaseModel):
    """Metadata about the enhancement process."""
    documents_fetched: int = Field(default=0, description="Number of documents successfully fetched")
    documents_failed: int = Field(default=0, description="Number of documents that failed to fetch")
    chunks_analyzed: int = Field(default=0, description="Total chunks analyzed")
    chunks_used: int = Field(default=0, description="Chunks used in answer generation")
    total_tokens_analyzed: int = Field(default=0, description="Total tokens in analyzed content")
    processing_time_ms: int = Field(default=0, description="Total processing time")
    cache_hits: int = Field(default=0, description="Number of documents served from cache")


class EnhanceResponse(BaseModel):
    """Response model for /oracle/enhance endpoint."""
    enhanced_answer: str = Field(..., description="The enhanced answer based on document content")
    direct_quotes: list[DirectQuote] = Field(default_factory=list, description="Direct quotes supporting the answer")
    citations: list[Citation] = Field(default_factory=list, description="Citations to source documents")
    metadata: EnhanceMetadata = Field(..., description="Enhancement process metadata")
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence in the enhanced answer")
    
    class Config:
        json_schema_extra = {
            "example": {
                "enhanced_answer": "Wi-Fi 7 (802.11be) MLO (Multi-Link Operation) requirements include...",
                "direct_quotes": [
                    {
                        "text": "MLO enables devices to simultaneously use multiple frequency bands...",
                        "source_url": "https://www.wi-fi.org/doc1",
                        "source_title": "Wi-Fi 7 Technical Overview",
                        "relevance_score": 0.92
                    }
                ],
                "citations": [
                    {
                        "index": 1,
                        "document_url": "https://www.wi-fi.org/doc1",
                        "title": "Wi-Fi 7 Technical Overview",
                        "excerpt": "MLO is a key feature..."
                    }
                ],
                "metadata": {
                    "documents_fetched": 3,
                    "documents_failed": 0,
                    "chunks_analyzed": 25,
                    "chunks_used": 12,
                    "total_tokens_analyzed": 8500,
                    "processing_time_ms": 4200,
                    "cache_hits": 1
                },
                "confidence_score": 0.85
            }
        }


class DataSourceInfo(BaseModel):
    """Information about a datasource for autocomplete."""
    datasource_id: str = Field(..., description="Unique datasource identifier")
    name: str = Field(..., description="Human-readable name")
    description: Optional[str] = Field(default=None, description="Description of the datasource")
    document_count: int = Field(default=0, description="Number of documents from this source")
    parent_datasource_id: Optional[str] = Field(default=None, description="Parent datasource ID for hierarchy")
    scraper_type: Optional[str] = Field(default=None, description="Scraper type for grouping")


class DataSourcesResponse(BaseModel):
    """Response model for /oracle/datasources endpoint."""
    datasources: list[DataSourceInfo] = Field(default_factory=list, description="Available datasources")


class HealthStatus(str, Enum):
    """Health check status values."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthCheck(BaseModel):
    """Health check response model."""
    status: HealthStatus = Field(..., description="Overall health status")
    checks: dict[str, str] = Field(default_factory=dict, description="Individual component checks")
    version: str = Field(default="0.1.0", description="Service version")


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    details: Optional[dict] = Field(default=None, description="Additional error details")
    request_id: Optional[str] = Field(default=None, description="Request ID for tracking")


class FeedbackResponse(BaseModel):
    """Response model for /oracle/feedback endpoint.
    
    Phase 6 of Oracle Service implementation.
    """
    status: str = Field(default="recorded", description="Feedback submission status")
    feedback_id: str = Field(..., description="Unique identifier for this feedback")
    message: str = Field(default="Thank you for your feedback", description="Confirmation message")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "recorded",
                "feedback_id": "fb-550e8400-e29b-41d4-a716-446655440000",
                "message": "Thank you for your feedback"
            }
        }
