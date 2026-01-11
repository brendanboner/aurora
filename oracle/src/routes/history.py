"""Query History API endpoints for viewing stored request/response data."""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
import logging

from common.auth_middleware import get_user_context, require_user_context
from src.services.query_history import get_query_history_service
from src.settings import settings

router = APIRouter(tags=["history"])
logger = logging.getLogger(__name__)


# Response models
class QueryHistoryItem(BaseModel):
    """Summary of a query history record."""
    id: str
    query_id: str
    created_at: Optional[str] = None
    user_id: Optional[str] = None
    question: str
    mode: str
    effective_mode: Optional[str] = None
    answer: Optional[str] = None
    intent: Optional[str] = None
    intent_confidence: Optional[float] = None
    confidence_score: Optional[float] = None
    confidence_level: Optional[str] = None
    documents_count: Optional[int] = None
    processing_time_ms: Optional[int] = None
    cache_hit: bool = False
    feedback_type: Optional[str] = None
    error: bool = False


class QueryHistoryListResponse(BaseModel):
    """Response for listing query history."""
    items: List[QueryHistoryItem]
    total: int
    limit: int
    offset: int


class QueryHistoryDetailResponse(BaseModel):
    """Detailed query history record."""
    id: str
    query_id: str
    created_at: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    question: str
    mode: str
    max_documents: Optional[int] = None
    include_graph_context: bool = True
    datasource_filter: Optional[str] = None
    effective_mode: Optional[str] = None
    answer: Optional[str] = None
    citations: Optional[list] = None
    documents: Optional[list] = None
    suggestions: Optional[list] = None
    intent: Optional[str] = None
    intent_confidence: Optional[float] = None
    confidence_score: Optional[float] = None
    confidence_level: Optional[str] = None
    documents_count: Optional[int] = None
    total_candidates: Optional[int] = None
    processing_time_ms: Optional[int] = None
    llm_tokens_used: Optional[int] = None
    cache_hit: bool = False
    strategies_used: Optional[list] = None
    feedback_type: Optional[str] = None
    feedback_comment: Optional[str] = None
    feedback_at: Optional[str] = None
    error: bool = False
    error_message: Optional[str] = None


class QueryStatisticsResponse(BaseModel):
    """Aggregated statistics for query history."""
    total_queries: int
    by_intent: dict
    feedback: dict
    performance: dict


# IMPORTANT: Static routes like /stats must come BEFORE dynamic routes like /{query_id}
# otherwise FastAPI will match /history/stats as /history/{query_id} with query_id="stats"

@router.get("/history/stats", response_model=QueryStatisticsResponse)
@require_user_context
async def get_query_statistics(
    days: int = Query(7, ge=1, le=90, description="Days of history to analyze"),
    user: Optional[dict] = Depends(get_user_context),
) -> QueryStatisticsResponse:
    """
    Get aggregated statistics for query history.
    
    Returns metrics like total queries, intent distribution,
    feedback stats, and average performance metrics.
    """
    if not settings.query_history_enabled:
        raise HTTPException(
            status_code=400,
            detail="Query history storage is disabled"
        )
    
    query_history = get_query_history_service()
    
    start_date = datetime.utcnow() - timedelta(days=days)
    
    stats = await query_history.get_statistics(start_date=start_date)
    
    return QueryStatisticsResponse(
        total_queries=stats.get("total_queries", 0),
        by_intent=stats.get("by_intent", {}),
        feedback=stats.get("feedback", {}),
        performance=stats.get("performance", {}),
    )


@router.delete("/history/cleanup")
@require_user_context
async def cleanup_old_history(
    user: Optional[dict] = Depends(get_user_context),
) -> dict:
    """
    Clean up query history records older than retention period.
    
    Deletes records older than the configured retention period
    (default 30 days). This is typically run via a scheduled job.
    """
    if not settings.query_history_enabled:
        raise HTTPException(
            status_code=400,
            detail="Query history storage is disabled"
        )
    
    query_history = get_query_history_service()
    
    deleted = await query_history.cleanup_old_records()
    
    return {
        "status": "success",
        "deleted_records": deleted,
        "retention_days": settings.query_history_retention_days,
    }


@router.get("/history", response_model=QueryHistoryListResponse)
@require_user_context
async def list_query_history(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    intent: Optional[str] = Query(None, description="Filter by intent type"),
    min_confidence: Optional[float] = Query(None, ge=0, le=1, description="Minimum confidence score"),
    max_confidence: Optional[float] = Query(None, ge=0, le=1, description="Maximum confidence score"),
    has_feedback: Optional[bool] = Query(None, description="Filter by feedback presence"),
    days: Optional[int] = Query(7, ge=1, le=90, description="Days of history to include"),
    limit: int = Query(50, ge=1, le=500, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    user: Optional[dict] = Depends(get_user_context),
) -> QueryHistoryListResponse:
    """
    List query history with optional filters.
    
    Returns a paginated list of past queries with summary information.
    Use this to review query patterns, identify issues, and analyze usage.
    """
    if not settings.query_history_enabled:
        raise HTTPException(
            status_code=400,
            detail="Query history storage is disabled"
        )
    
    query_history = get_query_history_service()
    
    start_date = datetime.utcnow() - timedelta(days=days)
    
    items = await query_history.list_queries(
        user_id=user_id,
        intent=intent,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
        has_feedback=has_feedback,
        start_date=start_date,
        limit=limit,
        offset=offset,
    )
    
    return QueryHistoryListResponse(
        items=[QueryHistoryItem(**item) for item in items],
        total=len(items),  # Would need a count query for true total
        limit=limit,
        offset=offset,
    )


@router.get("/history/{query_id}", response_model=QueryHistoryDetailResponse)
@require_user_context
async def get_query_detail(
    query_id: str,
    user: Optional[dict] = Depends(get_user_context),
) -> QueryHistoryDetailResponse:
    """
    Get detailed information about a specific query.
    
    Returns the full request and response data including
    the answer, documents, citations, and all metadata.
    """
    if not settings.query_history_enabled:
        raise HTTPException(
            status_code=400,
            detail="Query history storage is disabled"
        )
    
    query_history = get_query_history_service()
    
    result = await query_history.get_query(query_id)
    
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Query {query_id} not found"
        )
    
    return QueryHistoryDetailResponse(**result)
