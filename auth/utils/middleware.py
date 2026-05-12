"""JWT validation middleware utilities."""

import logging
from fastapi import Request, HTTPException, status
from .oauth import validate_jwt_token, refresh_access_token, extract_user_info, validate_user_group
from .state_storage import get_teams_session
from settings import get_settings

settings = get_settings()
logger = logging.getLogger("auth")


async def _refresh_and_get_user_info(request: Request, refresh_token: str) -> dict:
    """
    Use refresh token to get new access/ID tokens and extract user info.
    Stores new tokens in request.state for the response to set as cookies.
    """
    logger.info("Attempting to refresh tokens")
    new_tokens = await refresh_access_token(refresh_token)
    new_access_token = new_tokens["access_token"]
    new_id_token = new_tokens.get("id_token")
    
    # Validate new ID token and extract user info
    if new_id_token:
        id_token_claims = await validate_jwt_token(new_id_token, access_token=new_access_token)
        user_info = extract_user_info(id_token_claims)
        request.state.new_access_token = new_access_token
        request.state.new_id_token = new_id_token
        logger.info(f"Successfully refreshed tokens for user: {user_info.get('email')}")
    else:
        token_claims = await validate_jwt_token(new_access_token)
        user_info = extract_user_info(token_claims)
        request.state.new_access_token = new_access_token
        logger.info(f"Successfully refreshed access token for user: {user_info.get('email')}")
    
    return user_info


async def validate_request_token(request: Request) -> dict:
    """
    Middleware function to validate JWT token from cookies.
    Checks in priority order:
      1. teams_session cookie (Azure-AD Teams SSO session stored in Redis)
      2. Cognito access_token / id_token cookies (standard web login)
      3. Cognito refresh_token (silently refresh expired tokens)
    Returns user info dict.
    """
    # ── 1. Teams SSO session (set by /api/auth/teams-sso) ────────────────────
    teams_session_id = request.cookies.get("teams_session")
    if teams_session_id:
        user_info = get_teams_session(teams_session_id)
        if user_info:
            logger.debug(f"Authenticated via Teams SSO session: user={user_info.get('email')}")
            return user_info
        # Session expired — fall through to standard Cognito auth
        logger.info("Teams SSO session expired, falling back to Cognito auth")

    # ── 2 & 3. Cognito cookies ────────────────────────────────────────────────
    access_token = request.cookies.get("access_token")
    id_token = request.cookies.get("id_token")
    refresh_token = request.cookies.get("refresh_token")
    
    # If no access token but we have a refresh token, try to get new tokens
    if not access_token:
        if refresh_token:
            try:
                logger.info("No access token cookie, attempting refresh")
                return await _refresh_and_get_user_info(request, refresh_token)
            except Exception as e:
                logger.warning(f"Token refresh failed (no access token): {e}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session expired. Please login again."
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No access token provided"
            )
    
    try:
        # Validate access token (for authentication)
        await validate_jwt_token(access_token)
        
        # Extract user info from ID token (has user claims)
        if id_token:
            id_token_claims = await validate_jwt_token(id_token, access_token=access_token)
            user_info = extract_user_info(id_token_claims)
        else:
            # Fallback: try to extract from access token (may have limited info)
            access_token_claims = await validate_jwt_token(access_token)
            user_info = extract_user_info(access_token_claims)
        
        # Validate user is in required group
        validate_user_group(user_info, settings.allowed_cognito_groups)
        
        return user_info
    
    except HTTPException as e:
        # If access token expired, try to refresh
        if "expired" in str(e.detail).lower() and refresh_token:
            try:
                logger.info("Access token expired, attempting refresh")
                return await _refresh_and_get_user_info(request, refresh_token)
            except Exception as refresh_error:
                logger.warning(f"Token refresh failed: {refresh_error}. Session expired - login required.")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session expired. Please login again."
                )
        
        # Re-raise original exception if not expired or no refresh token
        logger.info(f"Token validation failed: {e.detail}. Refresh not attempted.")
        raise e
