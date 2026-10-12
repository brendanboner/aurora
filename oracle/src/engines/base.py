"""Base interface for answer engines."""

from typing import Protocol, Optional, Dict, List
from src.models.request import QueryRequest
from src.models.response import QueryResponse


class AnswerEngine(Protocol):
    """
    Protocol defining the interface for answer engines.
    
    All engines must implement these methods to provide
    a consistent interface for query processing.
    """
    
    async def query(
        self,
        request: QueryRequest,
        user: Optional[dict] = None,
        span = None,
        query_id: Optional[str] = None
    ) -> QueryResponse:
        """
        Process a query and return an answer.
        
        Args:
            request: The query request with question and options
            user: Optional user context from auth middleware
            span: Optional OpenTelemetry span for tracing
            query_id: Optional query ID for tracking
            
        Returns:
            QueryResponse with answer, documents, and metadata
            
        Raises:
            HTTPException: On errors during query processing
        """
        ...
    
    def get_capabilities(self) -> Dict[str, any]:
        """
        Get engine capabilities and configuration.
        
        Returns:
            Dictionary describing engine features, supported modes, etc.
        """
        ...
    
    def get_name(self) -> str:
        """Get the engine name for logging and metrics."""
        ...
