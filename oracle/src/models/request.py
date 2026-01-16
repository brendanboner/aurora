"""Oracle Service - Pydantic request models."""

from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum


class AnalyzeRequest(BaseModel):
    """Request model for /oracle/analyze endpoint."""
    question: str = Field(..., min_length=1, max_length=2000, description="The query to analyze")


class AnalyzeResponse(BaseModel):
    """Response model for /oracle/analyze endpoint."""
    is_good_query: bool = Field(..., description="Whether the query is well-formed")
    issues: list[str] = Field(default_factory=list, description="List of issues found with the query")
    suggested_query: Optional[str] = Field(default=None, description="Improved version of the query")
    suggestion_reason: Optional[str] = Field(default=None, description="Why the suggestion is better")


class QueryMode(str, Enum):
    """Response mode for query endpoint."""
    RETRIEVAL = "retrieval"
    ANSWER = "answer"
    AUTO = "auto"


class PersonalizeMode(str, Enum):
    """Personalization mode for query endpoint."""
    OFF = "off"
    ON = "on"
    AUTO = "auto"


class FeedbackType(str, Enum):
    """Type of user feedback."""
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"


class FeedbackRequest(BaseModel):
    """Request model for /oracle/feedback endpoint.
    
    Allows users to provide feedback on query responses.
    Phase 6 of Oracle Service implementation.
    """
    query_id: str = Field(..., description="The query ID to provide feedback for")
    feedback: FeedbackType = Field(..., description="Type of feedback: 'helpful' or 'not_helpful'")
    comment: Optional[str] = Field(
        default=None, 
        max_length=1000, 
        description="Optional additional feedback comment"
    )
    # Optional context for better analytics
    intent: Optional[str] = Field(default=None, description="Query intent if available")
    mode: Optional[str] = Field(default=None, description="Response mode if available")
    
    class Config:
        json_schema_extra = {
            "example": {
                "query_id": "550e8400-e29b-41d4-a716-446655440000",
                "feedback": "helpful",
                "comment": "The answer was accurate and well-cited",
                "intent": "topic_discovery",
                "mode": "answer"
            }
        }


class QueryOptions(BaseModel):
    """Optional settings for query behavior."""
    max_documents: int = Field(default=20, ge=1, le=100, description="Maximum documents to retrieve")
    include_graph_context: bool = Field(default=True, description="Include graph relationships in response")
    date_start: Optional[str] = Field(default=None, description="Filter documents from this date (ISO format)")
    date_end: Optional[str] = Field(default=None, description="Filter documents until this date (ISO format)")
    topics: Optional[list[str]] = Field(default=None, description="Filter by specific topics")
    organizations: Optional[list[str]] = Field(default=None, description="Filter by specific organizations")
    datasource_ids: Optional[list[str]] = Field(default=None, description="Filter by specific datasource IDs (e.g., ['wifi8mtg', 'wfa'])")
    recency_boost: bool = Field(default=True, description="Boost more recent documents in ranking")
    personalize: PersonalizeMode = Field(
        default=PersonalizeMode.AUTO, 
        description="Personalization mode: 'off' (generic), 'on' (always personalize), 'auto' (system decides)"
    )


class QueryRequest(BaseModel):
    """Request model for /oracle/query endpoint."""
    user_id: str = Field(..., description="User ID (Cognito UUID)")
    question: str = Field(..., min_length=1, max_length=2000, description="The question to answer")
    mode: QueryMode = Field(default=QueryMode.ANSWER, description="Response mode: 'retrieval', 'answer', or 'auto'")
    options: Optional[QueryOptions] = Field(default=None, description="Optional query settings")
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "question": "What are the latest updates on Wi-Fi 7?",
                "mode": "answer",
                "options": {
                    "max_documents": 10,
                    "include_graph_context": True
                }
            }
        }


class EnhanceDocumentReference(BaseModel):
    """Reference to a document for enhancement."""
    url: str = Field(..., description="Document URL")
    datasource_id: str = Field(..., description="Datasource ID (e.g., 'wfa', 'wfa_causeway')")
    title: Optional[str] = Field(default=None, description="Document title (for display)")


class EnhanceRequest(BaseModel):
    """Request model for /oracle/enhance endpoint.
    
    This endpoint enhances a previous answer by fetching and analyzing
    the full content of the referenced documents.
    """
    question: str = Field(..., min_length=1, max_length=2000, description="The original question")
    documents: list[EnhanceDocumentReference] = Field(
        ..., 
        min_length=1,
        max_length=10,
        description="Documents to fetch full content for"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "question": "What are the MLO requirements in Wi-Fi 7?",
                "documents": [
                    {
                        "url": "https://www.wi-fi.org/doc1",
                        "datasource_id": "wfa",
                        "title": "Wi-Fi 7 Certification Overview"
                    },
                    {
                        "url": "https://www.wi-fi.org/doc2", 
                        "datasource_id": "wfa",
                        "title": "MLO Technical Guide"
                    }
                ]
            }
        }
