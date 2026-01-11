"""Request proxying service for forwarding to internal services."""

import httpx
from fastapi import Request, Response, HTTPException, status
from typing import Dict
from settings import get_settings

settings = get_settings()

# Service URL mapping
SERVICE_ROUTES = {
    "/api/backend": settings.backend_service_url,
    "/api/curator": settings.curator_service_url,
    "/api/retriever": settings.retriever_service_url,
    "/api/content_creator_service": settings.content_creator_service_url,
    "/api/content-creator": settings.content_creator_service_url,  # Alias for content creator
    "/api/oracle": settings.oracle_service_url,  # Oracle question-answering service
}

# Safe headers to forward (allowlist approach)
SAFE_HEADERS = {
    'content-type', 'content-length', 'accept', 'accept-encoding',
    'accept-language', 'user-agent', 'referer'
}


def get_target_service_url(path: str) -> str:
    """
    Determine which internal service to forward request to based on path.
    """
    for prefix, service_url in SERVICE_ROUTES.items():
        if path.startswith(prefix):
            # Remove the /api/backend prefix and forward rest of path
            internal_path = path.replace(prefix, "", 1)
            return f"{service_url}{internal_path}"
    
    raise HTTPException(status_code=404, detail="Service not found")


async def proxy_request(
    request: Request,
    user_info: Dict[str, str]
) -> Response:
    """
    Forward authenticated request to internal service with user context.
    """
    # Determine target service
    target_url = get_target_service_url(request.url.path)
    
    # Get request body to check if there's content
    body = await request.body()
    
    # Validate content-type for methods that send bodies
    if request.method in ["POST", "PUT", "PATCH"] and len(body) > 0:
        content_type = request.headers.get("content-type", "")
        # Require Content-Type header when body is present
        if not content_type:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Content-Type header is required for requests with body"
            )
        # Validate Content-Type is one of the allowed types
        if not content_type.startswith(("application/json", "application/x-www-form-urlencoded", "multipart/form-data")):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported media type: {content_type}. Allowed types: application/json, application/x-www-form-urlencoded, multipart/form-data"
            )
    
    # Prepare headers - only forward safe headers (prevents header injection)
    headers = {
        k: v for k, v in request.headers.items() 
        if k.lower() in SAFE_HEADERS
    }
    
    # Add user context headers (these are trusted as they come from our validation)
    headers["X-User-Id"] = user_info["id"]
    headers["X-User-Email"] = user_info["email"]
    headers["X-User-Role"] = user_info["role"]
    
    # Remove host header (will be set by httpx)
    headers.pop("host", None)
    
    # Forward request
    async with httpx.AsyncClient() as client:
        try:
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
                params=request.query_params,
                timeout=30.0
            )
            
            # Filter response headers - only pass through safe headers
            # Don't pass content-length, server, date as FastAPI will set these
            safe_response_headers = {
                k: v for k, v in response.headers.items()
                if k.lower() not in ('content-length', 'server', 'date', 'transfer-encoding', 'connection')
            }
            
            # Create response with same status and content
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=safe_response_headers,
                media_type=response.headers.get("content-type")
            )
        
        except httpx.RequestError as e:
            # Log detailed error for debugging
            import logging
            logger = logging.getLogger("auth")
            logger.error(f"Service unavailable: service={target_url}, error={str(e)}")
            
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service temporarily unavailable"
            )
