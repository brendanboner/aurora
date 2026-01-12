"""JWT validation middleware utilities."""

from fastapi import Request, HTTPException, status
from .oauth import validate_jwt_token, refresh_access_token, extract_user_info
from settings import get_settings

settings = get_settings()


async def validate_request_token(request: Request) -> dict:
    """
    Middleware function to validate JWT token from cookies.
    Automatically refreshes token if expired.
    Returns user info dict.
    """
    # Get tokens from cookies
    access_token = request.cookies.get("access_token")
    id_token = request.cookies.get("id_token")
    refresh_token = request.cookies.get("refresh_token")
    
    if not access_token:
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
        
        return user_info
    
    except HTTPException as e:
        # If access token expired, try to refresh
        if "expired" in str(e.detail).lower() and refresh_token:
            try:
                logger.info(f"Access token expired, attempting refresh for user session")
                # Get new tokens using refresh token (includes both access_token and id_token)
                new_tokens = await refresh_access_token(refresh_token)
                new_access_token = new_tokens["access_token"]
                new_id_token = new_tokens.get("id_token")  # Cognito returns id_token on refresh
                
                # Validate new ID token and extract user info (prefer ID token as it has more claims)
                if new_id_token:
                    id_token_claims = await validate_jwt_token(new_id_token, access_token=new_access_token)
                    user_info = extract_user_info(id_token_claims)
                    # Store both tokens for response (will be set by proxy)
                    request.state.new_access_token = new_access_token
                    request.state.new_id_token = new_id_token
                    logger.info(f"Successfully refreshed tokens for user: {user_info.get('email')}")
                else:
                    # Fallback: extract from access token if no ID token
                    token_claims = await validate_jwt_token(new_access_token)
                    user_info = extract_user_info(token_claims)
                    request.state.new_access_token = new_access_token
                    logger.info(f"Successfully refreshed access token for user: {user_info.get('email')}")
                
                return user_info
            
            except Exception as refresh_error:
                logger.warning(f"Token refresh failed: {refresh_error}. Session expired - login required.")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session expired. Please login again."
                )
        
        # Re-raise original exception if not expired or no refresh token
        logger.info(f"Token validation failed: {e.detail}. Refresh not attempted.")
        raise e
