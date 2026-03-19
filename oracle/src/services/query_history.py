"""Query History service for storing and retrieving raw request/response data."""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from sqlalchemy import create_engine, text, delete
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

from src.models.query_history import QueryHistory, Base
from src.settings import settings

logger = logging.getLogger(__name__)


class QueryHistoryService:
    """
    Service for storing and retrieving Oracle query history.
    
    Stores raw request/response data in PostgreSQL for analytics,
    debugging, and compliance purposes.
    """
    
    def __init__(self):
        self._engine = None
        self._session_factory = None
        self._initialized = False
    
    def _get_engine(self):
        """Lazily create database engine."""
        if self._engine is None:
            self._engine = create_engine(
                settings.postgres_dsn,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
            )
        return self._engine
    
    def _get_session_factory(self):
        """Get session factory, creating if needed."""
        if self._session_factory is None:
            self._session_factory = sessionmaker(bind=self._get_engine())
        return self._session_factory
    
    async def initialize(self) -> bool:
        """
        Initialize the query history table.
        Creates the table if it doesn't exist.
        """
        if not settings.query_history_enabled:
            logger.info("Query history storage is disabled")
            return False
        
        try:
            engine = self._get_engine()
            Base.metadata.create_all(engine, tables=[QueryHistory.__table__])
            self._initialized = True
            logger.info("Query history table initialized")
            return True
        except SQLAlchemyError as e:
            logger.error(f"Failed to initialize query history table: {e}")
            return False
    
    def is_available(self) -> bool:
        """Check if query history storage is available."""
        return settings.query_history_enabled and self._initialized
    
    async def save_query(
        self,
        query_id: str,
        question: str,
        mode: str,
        response: Dict[str, Any],
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        max_documents: Optional[int] = None,
        include_graph_context: bool = False,
        datasource_filter: Optional[str] = None,
        request_options: Optional[Dict[str, Any]] = None,
        intent: Optional[str] = None,
        intent_confidence: Optional[float] = None,
        processing_time_ms: Optional[int] = None,
        llm_tokens_used: Optional[int] = None,
        cache_hit: bool = False,
        strategies_used: Optional[List[str]] = None,
        error: bool = False,
        error_message: Optional[str] = None,
    ) -> bool:
        """
        Save a query and its response to history.
        
        Args:
            query_id: Unique identifier for this query
            question: The user's question
            mode: Query mode ('answer', 'retrieval', 'auto')
            response: Full response data as dictionary
            user_id: Optional user identifier
            session_id: Optional session identifier
            ... other metadata fields
            
        Returns:
            True if saved successfully, False otherwise
        """
        if not self.is_available():
            return False
        
        try:
            session_factory = self._get_session_factory()
            session = session_factory()
            
            try:
                # Extract key fields from response
                answer = response.get("answer")
                citations = response.get("citations")
                documents = response.get("documents")
                graph_context = response.get("graph_context")
                suggestions = response.get("suggestions")
                metadata = response.get("metadata", {})
                confidence_score = response.get("confidence_score")
                
                # Truncate answer if too long
                if answer and len(answer) > settings.query_history_max_response_size:
                    answer = answer[:settings.query_history_max_response_size] + "... [truncated]"
                
                # Limit document storage to essential fields
                if documents:
                    documents = [
                        {
                            "id": doc.get("id"),
                            "title": doc.get("title"),
                            "relevance_score": doc.get("relevance_score"),
                            "source": doc.get("source"),
                            "datasource_id": doc.get("datasource_id"),
                        }
                        for doc in documents[:50]  # Max 50 documents
                    ]
                
                # Determine confidence level
                confidence_level = None
                if confidence_score is not None:
                    if confidence_score >= settings.confidence_high_threshold:
                        confidence_level = "high"
                    elif confidence_score >= settings.confidence_low_threshold:
                        confidence_level = "medium"
                    else:
                        confidence_level = "low"
                
                history = QueryHistory(
                    query_id=query_id,
                    user_id=user_id,
                    session_id=session_id,
                    question=question,
                    mode=mode,
                    max_documents=max_documents,
                    include_graph_context=include_graph_context,
                    datasource_filter=datasource_filter,
                    request_options=request_options,
                    effective_mode=response.get("mode"),
                    answer=answer,
                    citations=citations,
                    documents=documents,
                    graph_context=graph_context if include_graph_context else None,
                    suggestions=suggestions,
                    intent=intent or metadata.get("intent"),
                    intent_confidence=intent_confidence or metadata.get("intent_confidence"),
                    confidence_score=confidence_score,
                    confidence_level=confidence_level,
                    documents_count=len(response.get("documents", [])),
                    total_candidates=metadata.get("total_candidates"),
                    processing_time_ms=processing_time_ms or metadata.get("processing_time_ms"),
                    llm_tokens_used=llm_tokens_used or metadata.get("llm_tokens_used"),
                    cache_hit=cache_hit,
                    strategies_used=strategies_used or metadata.get("strategies_used"),
                    error=error,
                    error_message=error_message,
                )
                
                session.add(history)
                session.commit()
                
                logger.debug(f"Saved query history: {query_id}")
                return True
                
            except Exception as e:
                session.rollback()
                raise e
            finally:
                session.close()
                
        except SQLAlchemyError as e:
            logger.error(f"Failed to save query history: {e}")
            return False
    
    async def update_feedback(
        self,
        query_id: str,
        feedback_type: str,
        comment: Optional[str] = None,
    ) -> bool:
        """
        Update a query history record with user feedback.
        
        Args:
            query_id: The query to update
            feedback_type: 'positive' or 'negative'
            comment: Optional feedback comment
            
        Returns:
            True if updated successfully
        """
        if not self.is_available():
            return False
        
        try:
            session_factory = self._get_session_factory()
            session = session_factory()
            
            try:
                history = session.query(QueryHistory).filter(
                    QueryHistory.query_id == query_id
                ).first()
                
                if history:
                    history.feedback_type = feedback_type
                    history.feedback_comment = comment
                    history.feedback_at = datetime.utcnow()
                    session.commit()
                    logger.info(f"Updated feedback for query {query_id}: {feedback_type}")
                    return True
                else:
                    logger.warning(f"Query not found for feedback: {query_id}")
                    return False
                    
            except Exception as e:
                session.rollback()
                raise e
            finally:
                session.close()
                
        except SQLAlchemyError as e:
            logger.error(f"Failed to update feedback: {e}")
            return False
    
    async def get_query(self, query_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a specific query by ID.
        
        Returns:
            Query history record as dictionary, or None if not found
        """
        if not self.is_available():
            return None
        
        try:
            session_factory = self._get_session_factory()
            session = session_factory()
            
            try:
                history = session.query(QueryHistory).filter(
                    QueryHistory.query_id == query_id
                ).first()
                
                if history:
                    return history.to_dict()
                return None
                
            finally:
                session.close()
                
        except SQLAlchemyError as e:
            logger.error(f"Failed to get query: {e}")
            return None
    
    async def list_queries(
        self,
        user_id: Optional[str] = None,
        intent: Optional[str] = None,
        min_confidence: Optional[float] = None,
        max_confidence: Optional[float] = None,
        has_feedback: Optional[bool] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        List query history with optional filters.
        
        Args:
            user_id: Filter by user
            intent: Filter by intent type
            min_confidence: Minimum confidence score
            max_confidence: Maximum confidence score
            has_feedback: Filter by feedback presence
            start_date: Start of date range
            end_date: End of date range
            limit: Maximum results to return
            offset: Pagination offset
            
        Returns:
            List of query history records
        """
        if not self.is_available():
            return []
        
        try:
            session_factory = self._get_session_factory()
            session = session_factory()
            
            try:
                query = session.query(QueryHistory)
                
                if user_id:
                    query = query.filter(QueryHistory.user_id == user_id)
                if intent:
                    query = query.filter(QueryHistory.intent == intent)
                if min_confidence is not None:
                    query = query.filter(QueryHistory.confidence_score >= min_confidence)
                if max_confidence is not None:
                    query = query.filter(QueryHistory.confidence_score <= max_confidence)
                if has_feedback is not None:
                    if has_feedback:
                        query = query.filter(QueryHistory.feedback_type.isnot(None))
                    else:
                        query = query.filter(QueryHistory.feedback_type.is_(None))
                if start_date:
                    query = query.filter(QueryHistory.created_at >= start_date)
                if end_date:
                    query = query.filter(QueryHistory.created_at <= end_date)
                
                query = query.order_by(QueryHistory.created_at.desc())
                query = query.limit(limit).offset(offset)
                
                results = query.all()
                return [r.to_dict() for r in results]
                
            finally:
                session.close()
                
        except SQLAlchemyError as e:
            logger.error(f"Failed to list queries: {e}")
            return []
    
    async def cleanup_old_records(self) -> int:
        """
        Delete records older than retention period.
        
        Returns:
            Number of records deleted
        """
        if not self.is_available():
            return 0
        
        try:
            session_factory = self._get_session_factory()
            session = session_factory()
            
            try:
                cutoff_date = datetime.utcnow() - timedelta(days=settings.query_history_retention_days)
                
                result = session.execute(
                    delete(QueryHistory).where(QueryHistory.created_at < cutoff_date)
                )
                deleted = result.rowcount
                session.commit()
                
                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} old query history records")
                return deleted
                
            except Exception as e:
                session.rollback()
                raise e
            finally:
                session.close()
                
        except SQLAlchemyError as e:
            logger.error(f"Failed to cleanup old records: {e}")
            return 0
    
    async def get_statistics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Get aggregated statistics for query history.
        
        Returns:
            Dictionary with statistics
        """
        if not self.is_available():
            return {}
        
        try:
            session_factory = self._get_session_factory()
            session = session_factory()
            
            try:
                query = session.query(QueryHistory)
                
                if start_date:
                    query = query.filter(QueryHistory.created_at >= start_date)
                if end_date:
                    query = query.filter(QueryHistory.created_at <= end_date)
                
                total = query.count()
                
                # Get counts by intent
                intent_query = text("""
                    SELECT intent, COUNT(*) as count 
                    FROM oracle_query_history 
                    WHERE intent IS NOT NULL
                    GROUP BY intent
                """)
                intent_results = session.execute(intent_query).fetchall()
                
                # Get feedback stats
                feedback_query = text("""
                    SELECT 
                        COUNT(*) FILTER (WHERE feedback_type = 'positive') as positive,
                        COUNT(*) FILTER (WHERE feedback_type = 'negative') as negative,
                        COUNT(*) FILTER (WHERE feedback_type IS NOT NULL) as total_feedback
                    FROM oracle_query_history
                """)
                feedback_result = session.execute(feedback_query).fetchone()
                
                # Get performance stats
                perf_query = text("""
                    SELECT 
                        AVG(processing_time_ms) as avg_latency,
                        AVG(confidence_score) as avg_confidence,
                        AVG(documents_count) as avg_docs,
                        SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END)::float / COUNT(*) as cache_hit_rate
                    FROM oracle_query_history
                """)
                perf_result = session.execute(perf_query).fetchone()
                
                return {
                    "total_queries": total,
                    "by_intent": {row[0]: row[1] for row in intent_results},
                    "feedback": {
                        "positive": feedback_result[0] if feedback_result else 0,
                        "negative": feedback_result[1] if feedback_result else 0,
                        "total": feedback_result[2] if feedback_result else 0,
                    },
                    "performance": {
                        "avg_latency_ms": round(perf_result[0], 2) if perf_result and perf_result[0] else None,
                        "avg_confidence": round(perf_result[1], 3) if perf_result and perf_result[1] else None,
                        "avg_documents": round(perf_result[2], 1) if perf_result and perf_result[2] else None,
                        "cache_hit_rate": round(perf_result[3], 3) if perf_result and perf_result[3] else None,
                    },
                }
                
            finally:
                session.close()
                
        except SQLAlchemyError as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}

    async def get_hot_queries(
        self,
        days: int = 30,
        limit: int = 10,
        fast_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Return recent hot queries ranked by a simple frequency * latency score.

        Small punctuation variants are grouped together so repeated prompts
        differ only when the wording meaningfully changes.
        """
        if not self.is_available():
            return []

        try:
            session_factory = self._get_session_factory()
            session = session_factory()

            try:
                filters = ["created_at >= :cutoff_date", "error = false", "question IS NOT NULL"]
                params: Dict[str, Any] = {
                    "cutoff_date": datetime.utcnow() - timedelta(days=days),
                    "limit": limit,
                }

                if fast_only:
                    filters.append("(request_options->>'pipeline' = 'fast' OR request_options IS NULL)")

                hot_query_sql = text(f"""
                    WITH normalized AS (
                        SELECT
                            lower(trim(regexp_replace(question, '[[:punct:]]+$', '', 'g'))) AS normalized_question,
                            question,
                            user_id,
                            processing_time_ms,
                            cache_hit,
                            created_at,
                            request_options,
                            datasource_filter,
                            ROW_NUMBER() OVER (
                                PARTITION BY lower(trim(regexp_replace(question, '[[:punct:]]+$', '', 'g')))
                                ORDER BY created_at DESC
                            ) AS variant_rank
                        FROM oracle_query_history
                        WHERE {' AND '.join(filters)}
                    ),
                    aggregated AS (
                        SELECT
                            normalized_question,
                            COUNT(*) AS frequency,
                            ROUND(AVG(COALESCE(processing_time_ms, 0)))::int AS avg_processing_time_ms,
                            MAX(created_at) AS last_seen_at,
                            COALESCE(AVG(CASE WHEN cache_hit THEN 1.0 ELSE 0.0 END), 0) AS cache_hit_rate,
                            (COUNT(*) * GREATEST(AVG(COALESCE(processing_time_ms, 0)), 1)) AS hotness_score
                        FROM normalized
                        WHERE normalized_question <> ''
                        GROUP BY normalized_question
                    )
                    SELECT
                        aggregated.normalized_question,
                        latest.question AS sample_question,
                        latest.user_id AS sample_user_id,
                        latest.request_options AS sample_request_options,
                        latest.datasource_filter AS sample_datasource_filter,
                        aggregated.frequency,
                        aggregated.avg_processing_time_ms,
                        aggregated.last_seen_at,
                        aggregated.cache_hit_rate,
                        aggregated.hotness_score
                    FROM aggregated
                    JOIN normalized AS latest
                        ON latest.normalized_question = aggregated.normalized_question
                       AND latest.variant_rank = 1
                    ORDER BY aggregated.hotness_score DESC, aggregated.last_seen_at DESC
                    LIMIT :limit
                """)

                results = session.execute(hot_query_sql, params).mappings().all()
                return [dict(row) for row in results]

            finally:
                session.close()

        except SQLAlchemyError as e:
            logger.error(f"Failed to get hot queries: {e}")
            return []


# Singleton instance
_query_history_service: Optional[QueryHistoryService] = None


def get_query_history_service() -> QueryHistoryService:
    """Get the query history service singleton."""
    global _query_history_service
    if _query_history_service is None:
        _query_history_service = QueryHistoryService()
    return _query_history_service
