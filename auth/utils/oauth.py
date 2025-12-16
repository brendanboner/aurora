"""OAuth and JWT token validation utilities."""

import httpx
import logging
from jose import jwt, jwk, JWTError
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import time
from fastapi import HTTPException, status
from settings import get_settings

settings = get_settings()
logger = logging.getLogger("auth")

# Cache for JWKS keys (public keys from Cognito)
_jwks_cache: Optional[Dict[str, Any]] = None
_jwks_cache_time: Optional[float] = None
JWKS_CACHE_TTL = 3600  # 1 hour - refresh periodically in case AWS rotates keys


async def get_jwks() -> Dict[str, Any]:
    """Fetch and cache Cognito JWKS (public keys for JWT validation)"""
    global _jwks_cache, _jwks_cache_time
    
    now = time.time()
    # Refresh cache if it's None or older than TTL
    if _jwks_cache is None or (_jwks_cache_time and (now - _jwks_cache_time) > JWKS_CACHE_TTL):
        async with httpx.AsyncClient() as client:
            response = await client.get(settings.cognito_jwks_url)
            response.raise_for_status()
            _jwks_cache = response.json()
            _jwks_cache_time = now
    
    return _jwks_cache


async def validate_jwt_token(token: str, access_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Validate JWT token from Cognito.
    Returns decoded token claims if valid.
    Raises HTTPException if invalid.
    
    Args:
        token: The ID token to validate
        access_token: Optional access token for at_hash validation
    """
    try:
        # Get the key ID from token header
        headers = jwt.get_unverified_headers(token)
        kid = headers["kid"]
        
        # Get the public key from JWKS
        jwks = await get_jwks()
        key = None
        for jwk_key in jwks["keys"]:
            if jwk_key["kid"] == kid:
                key = jwk_key
                break
        
        if not key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to find appropriate key"
            )
        
        # Verify the token signature and claims
        decoded_token = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.cognito_app_client_id,
            issuer=settings.cognito_issuer,
            access_token=access_token  # Provide access_token for at_hash validation
        )
        
        # Check if token is expired (use timezone-aware datetime)
        exp = decoded_token.get("exp")
        if exp and datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired"
            )
        
        return decoded_token
    
    except JWTError as e:
        logger.error(f"JWT validation failed: {type(e).__name__}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
        )


async def exchange_code_for_tokens(code: str) -> Dict[str, str]:
    """
    Exchange authorization code for tokens from Cognito.
    Returns dict with access_token, id_token, refresh_token.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            settings.cognito_token_endpoint,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.cognito_app_client_id,
                "client_secret": settings.cognito_app_client_secret,
                "code": code,
                "redirect_uri": settings.oauth_redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        if response.status_code != 200:
            # Log detailed error for debugging, but don't expose to user
            logger.error(f"Token exchange failed: status={response.status_code}, body={response.text}")
            
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Authentication failed. Please try again."
            )
        
        tokens = response.json()
        logger.info(f"Token exchange successful. Token keys: {list(tokens.keys())}")
        return tokens


async def refresh_access_token(refresh_token: str) -> Dict[str, str]:
    """
    Use refresh token to get new access token from Cognito.
    Returns dict with new access_token.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            settings.cognito_token_endpoint,
            data={
                "grant_type": "refresh_token",
                "client_id": settings.cognito_app_client_id,
                "client_secret": settings.cognito_app_client_secret,
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token invalid or expired"
            )
        
        return response.json()


def extract_user_info(id_token_claims: Dict[str, Any]) -> Dict[str, str]:
    """
    Extract user information from ID token claims.
    Returns dict with user_id, email, role.
    """
    return {
        "user_id": id_token_claims.get("sub"),
        "email": id_token_claims.get("email"),
        "role": id_token_claims.get("custom:role", "user"),  # Default to 'user' if not set
    }
