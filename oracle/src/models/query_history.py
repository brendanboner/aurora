"""Query History model for storing raw request/response data."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import Column, String, DateTime, Integer, Float, Text, Boolean, JSON, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
import uuid

Base = declarative_base()


class QueryHistory(Base):
    """
    Stores raw query request and response data for analytics.
    
    This table captures the full context of each Oracle query including:
    - The original question and parameters
    - The generated answer and citations
    - Retrieved documents and their relevance scores
    - Performance metrics and confidence scores
    - User feedback (if provided later)
    """
    __tablename__ = "oracle_query_history"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Query identification
    query_id = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # User context (if available)
    user_id = Column(String(255), nullable=True, index=True)
    session_id = Column(String(255), nullable=True)
    
    # Request data
    question = Column(Text, nullable=False)
    mode = Column(String(20), nullable=False)  # 'answer', 'retrieval', 'auto'
    max_documents = Column(Integer, nullable=True)
    include_graph_context = Column(Boolean, default=False)
    datasource_filter = Column(String(255), nullable=True)
    request_options = Column(JSON, nullable=True)  # Full request options as JSON
    
    # Response data
    effective_mode = Column(String(20), nullable=True)  # Actual mode used
    answer = Column(Text, nullable=True)  # Generated answer
    citations = Column(JSON, nullable=True)  # List of citations
    documents = Column(JSON, nullable=True)  # Retrieved documents (limited fields)
    graph_context = Column(JSON, nullable=True)  # Graph context if included
    suggestions = Column(JSON, nullable=True)  # Query suggestions
    
    # Intent classification
    intent = Column(String(50), nullable=True, index=True)
    intent_confidence = Column(Float, nullable=True)
    
    # Quality metrics
    confidence_score = Column(Float, nullable=True, index=True)
    confidence_level = Column(String(20), nullable=True)  # 'low', 'medium', 'high'
    documents_count = Column(Integer, nullable=True)
    total_candidates = Column(Integer, nullable=True)
    
    # Performance metrics
    processing_time_ms = Column(Integer, nullable=True, index=True)
    llm_tokens_used = Column(Integer, nullable=True)
    cache_hit = Column(Boolean, default=False)
    
    # Retrieval details
    strategies_used = Column(JSON, nullable=True)  # ['keyword', 'vector', 'graph']
    
    # Feedback (updated later via feedback endpoint)
    feedback_type = Column(String(20), nullable=True)  # 'positive', 'negative'
    feedback_comment = Column(Text, nullable=True)
    feedback_at = Column(DateTime, nullable=True)
    
    # Error tracking
    error = Column(Boolean, default=False)
    error_message = Column(Text, nullable=True)
    
    # Indexes for common query patterns
    __table_args__ = (
        Index('idx_query_history_date_intent', 'created_at', 'intent'),
        Index('idx_query_history_date_confidence', 'created_at', 'confidence_score'),
        Index('idx_query_history_user_date', 'user_id', 'created_at'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "query_id": self.query_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "user_id": self.user_id,
            "question": self.question,
            "mode": self.mode,
            "effective_mode": self.effective_mode,
            "answer": self.answer,
            "intent": self.intent,
            "intent_confidence": self.intent_confidence,
            "confidence_score": self.confidence_score,
            "confidence_level": self.confidence_level,
            "documents_count": self.documents_count,
            "processing_time_ms": self.processing_time_ms,
            "cache_hit": self.cache_hit,
            "feedback_type": self.feedback_type,
            "error": self.error,
        }
