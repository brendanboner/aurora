"""Shared authentication middleware for Aurora services.

This module provides FastAPI dependencies and decorators for handling
user authentication context passed from the auth service via headers.

Security Model:
--------------
This implementation relies on Docker network isolation. Internal services are
not exposed publicly and can only be reached through the auth service or by
other internal services. The auth service validates user authentication and
passes user context via headers.

Usage:
------
    from common.auth_middleware import get_user_context, require_user_context
    
    # Endpoint that requires authentication
    @app.get("/my-endpoint")
    @require_user_context
    async def my_endpoint(user: Optional[dict] = Depends(get_user_context)):
        # user is guaranteed to be not None
        return {"user": user}
    
    # Endpoint that works with or without authentication
    @app.get("/flexible-endpoint")
    async def flexible_endpoint(user: Optional[dict] = Depends(get_user_context)):
        if user:
            # User-initiated request
            return {"message": f"Hello {user['email']}"}
        else:
            # Service-to-service or scheduled job
            return {"message": "Hello service"}
    
    # Admin-only endpoint
    @app.get("/admin-endpoint")
    @require_role(["admin", "superadmin"])
    async def admin_endpoint(user: Optional[dict] = Depends(get_user_context)):
        return {"admin_data": "sensitive information"}
"""

from fastapi import Header, HTTPException, status
from typing import Optional
from functools import wraps
import logging

logger = logging.getLogger(__name__)


async def get_user_context(
    x_user_id: Optional[str] = Header(None),
    x_user_email: Optional[str] = Header(None),
    x_user_role: Optional[str] = Header(None),
) -> Optional[dict]:
    """
    Extract user context from headers.
    
    Returns user context dict if headers are present, None otherwise.
    Use this for user-initiated requests that come through the auth service.
    
    For service-to-service calls (scheduled jobs, events), these headers 
    may not be present, which is expected behavior.
    
    Args:
        x_user_id: User ID from X-User-Id header
        x_user_email: User email from X-User-Email header
        x_user_role: User role from X-User-Role header
    
    Returns:
        dict with keys: user_id, email, role (if headers present)
        None (if no user headers present)
    
    Examples:
        >>> # In a route handler
        >>> async def my_route(user: Optional[dict] = Depends(get_user_context)):
        ...     if user:
        ...         print(f"User: {user['email']}, Role: {user['role']}")
        ...     else:
        ...         print("Service-to-service call")
    """
    if not x_user_id:
        return None
    
    user_context = {
        "user_id": x_user_id,
        "email": x_user_email or "unknown",
        "role": x_user_role or "user",
    }
    
    # Log user context for security monitoring
    logger.debug(f"User context extracted: {user_context['email']} (role: {user_context['role']})")
    
    return user_context


def require_user_context(func):
    """
    Decorator to require user context for an endpoint.
    Use this for endpoints that should ONLY be called by authenticated users.
    
    Raises HTTPException 401 if user context is not present.
    
    Usage:
        from common.auth_middleware import get_user_context, require_user_context
        
        @app.get("/protected")
        @require_user_context
        async def protected_route(user: Optional[dict] = Depends(get_user_context)):
            # user is guaranteed to be not None
            return {"user_id": user["user_id"]}
    
    Args:
        func: The route handler function to wrap
    
    Returns:
        Wrapped function that validates user context
    """
    @wraps(func)
    async def wrapper(*args, user: Optional[dict] = None, **kwargs):
        if user is None:
            logger.warning(
                f"Unauthorized access attempt to {func.__name__}: No user context provided"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required. User context not found in request headers."
            )
        return await func(*args, user=user, **kwargs)
    return wrapper


def require_role(allowed_roles: list[str]):
    """
    Decorator to require specific roles for an endpoint.
    
    Args:
        allowed_roles: List of roles that are allowed to access the endpoint
                      (e.g., ["admin", "superadmin"])
    
    Usage:
        from common.auth_middleware import get_user_context, require_role
        
        @app.get("/admin/settings")
        @require_role(["admin", "superadmin"])
        async def admin_settings(user: Optional[dict] = Depends(get_user_context)):
            # Only admin and superadmin can access
            return {"settings": "sensitive data"}
        
        @app.delete("/admin/users/{user_id}")
        @require_role(["superadmin"])
        async def delete_user(user_id: str, user: Optional[dict] = Depends(get_user_context)):
            # Only superadmin can delete users
            return {"deleted": user_id}
    
    Returns:
        Decorator function that validates user role
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, user: Optional[dict] = None, **kwargs):
            if user is None:
                logger.warning(
                    f"Unauthorized access attempt to {func.__name__}: No user context"
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required"
                )
            
            user_role = user.get("role", "user")
            if user_role not in allowed_roles:
                logger.warning(
                    f"Forbidden access attempt to {func.__name__}: "
                    f"User {user.get('email')} has role '{user_role}', "
                    f"requires one of {allowed_roles}"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Insufficient permissions. Required roles: {', '.join(allowed_roles)}"
                )
            
            # Log privileged access for security monitoring
            if user_role in ["admin", "superadmin"]:
                logger.info(
                    f"Privileged access: {user.get('email')} (role: {user_role}) "
                    f"accessed {func.__name__}"
                )
            
            return await func(*args, user=user, **kwargs)
        return wrapper
    return decorator


def check_resource_ownership(resource_owner_id: str, user: dict, allow_admin: bool = True) -> bool:
    """
    Helper function to check if a user owns a resource or has admin privileges.
    
    Args:
        resource_owner_id: The user_id of the resource owner
        user: User context dict from get_user_context
        allow_admin: If True, admin/superadmin can access any resource (default: True)
    
    Returns:
        True if user can access the resource, False otherwise
    
    Usage:
        @app.get("/documents/{doc_id}")
        @require_user_context
        async def get_document(doc_id: str, user: Optional[dict] = Depends(get_user_context)):
            doc = get_document_from_db(doc_id)
            
            if not check_resource_ownership(doc.owner_id, user):
                raise HTTPException(status_code=403, detail="Access denied")
            
            return doc
    """
    # Check if user owns the resource
    if user["user_id"] == resource_owner_id:
        return True
    
    # Check if user has admin privileges (if allowed)
    if allow_admin and user.get("role") in ["admin", "superadmin"]:
        logger.info(
            f"Admin override: {user.get('email')} (role: {user.get('role')}) "
            f"accessing resource owned by {resource_owner_id}"
        )
        return True
    
    return False
