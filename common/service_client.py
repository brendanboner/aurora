"""
Service-to-Service Communication Utilities

This module provides utility functions for internal Aurora services to call
each other with optional user context propagation.

Example Usage:
--------------

# In backend service, calling curator service
from common.service_client import call_internal_service

# User-initiated request (propagate user context)
async def user_requested_analysis(document_id: str, user: dict):
    result = await call_internal_service(
        service_url=os.getenv("CURATOR_SERVICE_URL", "http://curator:8000"),
        path="/trigger/topics",
        method="POST",
        user_context=user  # Pass through user context
    )
    return result

# System/scheduled job (no user context)
async def scheduled_cleanup():
    result = await call_internal_service(
        service_url=os.getenv("CURATOR_SERVICE_URL", "http://curator:8000"),
        path="/status",
        method="GET"
        # No user_context - system operation
    )
    return result

Security Model:
--------------
This implementation relies on Docker network isolation:
- Internal services are NOT exposed publicly
- Services can only be reached through the auth service OR by other internal services
- The auth service validates user authentication for external requests
- Internal services trust headers from other internal services (same trust boundary)
"""

import httpx
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


async def call_internal_service(
    service_url: str,
    path: str,
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    user_context: Optional[dict] = None,
    timeout: float = 30.0
) -> Dict[str, Any]:
    """
    Generic function to call internal Aurora services.
    
    This function handles:
    - Optional user context propagation via headers
    - Error handling and logging
    - Timeout management
    - Both form data and JSON payloads
    
    Args:
        service_url: Base URL of the internal service (e.g., "http://curator:8000")
        path: API path (e.g., "/trigger/topics")
        method: HTTP method (GET, POST, PUT, DELETE, etc.)
        data: Form data to send (for application/x-www-form-urlencoded)
        json_data: JSON data to send (for application/json)
        user_context: Optional user context dict with keys: user_id, email, role
                     If provided, will be passed via X-User-* headers
        timeout: Request timeout in seconds (default: 30)
    
    Returns:
        Response data as dict
    
    Raises:
        httpx.HTTPError: If the request fails
    
    Examples:
        # GET request with user context
        result = await call_internal_service(
            service_url="http://backend:8000",
            path="/users/123",
            method="GET",
            user_context={"user_id": "123", "email": "user@example.com", "role": "user"}
        )
        
        # POST request without user context (system operation)
        result = await call_internal_service(
            service_url="http://curator:8000",
            path="/trigger/topics",
            method="POST"
        )
        
        # POST with JSON data and user context
        result = await call_internal_service(
            service_url="http://backend:8000",
            path="/upload",
            method="POST",
            json_data={"title": "Document", "content": "..."},
            user_context=current_user
        )
    """
    headers = {}
    
    # Pass through user context if available (for audit logging and authorization)
    if user_context:
        headers["X-User-Id"] = user_context.get("user_id", "")
        headers["X-User-Email"] = user_context.get("email", "")
        headers["X-User-Role"] = user_context.get("role", "user")
        logger.debug(
            f"Calling {service_url}{path} with user context: "
            f"{user_context.get('email')} (role: {user_context.get('role')})"
        )
    else:
        logger.debug(f"Calling {service_url}{path} as system/service operation")
    
    # Build full URL
    url = f"{service_url}{path}"
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                data=data,
                json=json_data
            )
            response.raise_for_status()
            
            # Try to parse JSON response
            try:
                return response.json()
            except ValueError:
                # Not JSON, return text
                return {"text": response.text}
                
        except httpx.HTTPError as e:
            logger.error(
                f"Service call failed: {method} {url} - {e}",
                exc_info=True
            )
            raise


async def call_backend_service(
    path: str,
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    user_context: Optional[dict] = None
) -> Dict[str, Any]:
    """
    Convenience function to call the backend service.
    
    Uses BACKEND_SERVICE_URL from environment or defaults to http://backend:8000
    """
    import os
    service_url = os.getenv("BACKEND_SERVICE_URL", "http://backend:8000")
    return await call_internal_service(
        service_url=service_url,
        path=path,
        method=method,
        data=data,
        json_data=json_data,
        user_context=user_context
    )


async def call_curator_service(
    path: str,
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    user_context: Optional[dict] = None
) -> Dict[str, Any]:
    """
    Convenience function to call the curator service.
    
    Uses CURATOR_SERVICE_URL from environment or defaults to http://curator:8000
    """
    import os
    service_url = os.getenv("CURATOR_SERVICE_URL", "http://curator:8000")
    return await call_internal_service(
        service_url=service_url,
        path=path,
        method=method,
        data=data,
        json_data=json_data,
        user_context=user_context
    )


async def call_retriever_service(
    path: str,
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    user_context: Optional[dict] = None
) -> Dict[str, Any]:
    """
    Convenience function to call the retriever service.
    
    Uses RETRIEVER_SERVICE_URL from environment or defaults to http://retriever:8000
    """
    import os
    service_url = os.getenv("RETRIEVER_SERVICE_URL", "http://retriever:8000")
    return await call_internal_service(
        service_url=service_url,
        path=path,
        method=method,
        data=data,
        json_data=json_data,
        user_context=user_context
    )


# ============================================================================
# Example Use Cases
# ============================================================================

async def example_user_initiated_action(user: dict):
    """
    Example: User clicks 'analyze' button in frontend.
    The user context should be propagated to track who initiated the action.
    """
    logger.info(f"User {user['email']} requested topic organization")
    
    result = await call_curator_service(
        path="/trigger/topics",
        method="POST",
        user_context=user  # Propagate user context
    )
    
    return result


async def example_scheduled_job():
    """
    Example: Scheduled nightly cleanup job.
    No user involved, so no user_context is passed.
    """
    logger.info("Running scheduled cleanup job")
    
    # Get curator status (no user context needed)
    status = await call_curator_service(
        path="/status",
        method="GET"
        # No user_context - this is a system operation
    )
    
    # Trigger reconciliation if needed (still no user context)
    if status.get("jobs", []):
        await call_curator_service(
            path="/trigger/reconcile",
            method="POST"
            # No user_context - system operation
        )
    
    return status


async def example_service_to_service_with_context(document_id: str, user: dict):
    """
    Example: Backend receives user request, needs to call multiple services.
    User context is propagated through the chain.
    """
    # Get document from backend
    doc = await call_backend_service(
        path=f"/documents/{document_id}",
        method="GET",
        user_context=user
    )
    
    # Trigger analysis in curator
    analysis = await call_curator_service(
        path="/trigger/topics",
        method="POST",
        user_context=user
    )
    
    # Start retrieval of related documents
    related = await call_retriever_service(
        path=f"/scrape/datasource/{doc['datasource_id']}",
        method="POST",
        user_context=user
    )
    
    return {
        "document": doc,
        "analysis": analysis,
        "related": related
    }


async def example_mixed_operations(user: dict):
    """
    Example: Some operations need user context, others don't.
    """
    # User-initiated query (needs auth)
    query_result = await call_backend_service(
        path="/query",
        method="POST",
        json_data={"user_id": user["user_id"], "question": "What's new?"},
        user_context=user  # User context for authorization
    )
    
    # Get curator status (doesn't require user, but nice to log who asked)
    curator_status = await call_curator_service(
        path="/status",
        method="GET",
        user_context=user  # Optional - for audit logging
    )
    
    # Get retriever status (internal monitoring, no user context needed)
    retriever_status = await call_retriever_service(
        path="/status",
        method="GET"
        # No user_context - just checking system health
    )
    
    return {
        "query_result": query_result,
        "curator_status": curator_status,
        "retriever_status": retriever_status
    }
