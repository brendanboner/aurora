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
    Returns dict with id, email, role, groups.
    """
    return {
        "id": id_token_claims.get("sub"),
        "email": id_token_claims.get("email"),
        "role": id_token_claims.get("custom:role", "user"),  # Default to 'user' if not set
        "groups": id_token_claims.get("cognito:groups", []),  # Cognito groups from token
    }


def validate_user_group(user_info: Dict[str, Any], required_groups: list[str]) -> None:
    """
    Validate that user is a member of at least one of the required Cognito groups.
    Raises HTTPException if user is not in any of the required groups.
    
    Args:
        user_info: User information dict containing 'groups' key
        required_groups: List of allowed Cognito group names (user must be in at least one)
    """
    user_groups = user_info.get("groups", [])
    user_email = user_info.get("email", "unknown")
    
    # Check if user is in any of the allowed groups
    if not any(group in user_groups for group in required_groups):
        logger.warning(
            f"Access denied - user not in required group: "
            f"user={user_email}, groups={user_groups}, required={required_groups}"
        )
        
        # Format group list for error message
        groups_str = "', '".join(required_groups)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied. You must be a member of one of these groups to access this application: '{groups_str}'."
        )
    
    logger.debug(f"Group validation passed for user {user_email}: groups={user_groups}")


# ─── Azure AD token validation (for Teams SSO) ────────────────────────────────

_azure_jwks_cache: Optional[Dict[str, Any]] = None
_azure_jwks_cache_time: Optional[float] = None


async def get_azure_jwks(tenant_id: str) -> Dict[str, Any]:
    """Fetch and cache Azure AD JWKS (public keys for Teams SSO token validation)."""
    global _azure_jwks_cache, _azure_jwks_cache_time

    now = time.time()
    if _azure_jwks_cache is None or (_azure_jwks_cache_time and (now - _azure_jwks_cache_time) > JWKS_CACHE_TTL):
        jwks_url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        async with httpx.AsyncClient() as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            _azure_jwks_cache = response.json()
            _azure_jwks_cache_time = now

    return _azure_jwks_cache


async def validate_azure_sso_token(token: str, tenant_id: str, app_client_id: str) -> Dict[str, Any]:
    """
    Validate a Teams SSO token (Azure AD-issued JWT) and return its claims.

    The Teams JS SDK's authentication.getAuthToken() returns an Azure AD access
    token scoped to the app.  We validate it against Azure's JWKS, then extract
    the user's email and identity.

    Args:
        token: The Azure AD JWT from Teams authentication.getAuthToken()
        tenant_id: Azure AD tenant ID (GUID) — set AZURE_TENANT_ID in .env
        app_client_id: Azure App Registration client ID — matches manifest webApplicationInfo.id

    Returns:
        Decoded token claims dict.

    Raises:
        HTTPException 401 if the token is invalid or untrusted.
    """
    try:
        headers = jwt.get_unverified_headers(token)
        kid = headers.get("kid")

        jwks = await get_azure_jwks(tenant_id)
        key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)

        if not key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Azure SSO: unable to find matching signing key",
            )

        # Azure AD tokens may use the app client ID or api://<client_id> as audience
        for audience in [app_client_id, f"api://{app_client_id}"]:
            try:
                claims = jwt.decode(
                    token,
                    key,
                    algorithms=["RS256"],
                    audience=audience,
                    issuer=f"https://login.microsoftonline.com/{tenant_id}/v2.0",
                )
                logger.info(f"Teams SSO token validated for audience={audience}")
                return claims
            except JWTError:
                continue

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Azure SSO: token audience mismatch",
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Azure SSO token validation error: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Azure SSO: invalid or expired token",
        )


def extract_azure_user_info(claims: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract Aurora-compatible user info from Azure AD token claims.
    Maps Azure claims to the same format as extract_user_info() for Cognito tokens.
    """
    email = claims.get("email") or claims.get("preferred_username", "")
    name = claims.get("name", "")
    given_name = claims.get("given_name", "")
    family_name = claims.get("family_name", "")

    # Check role override list — ensures admins migrating from Cognito to SSO
    # keep their role even though Azure AD tokens don't carry custom:role.
    from auth.settings import get_settings as _get_settings
    _role = _get_settings().get_role_for_email(email)

    return {
        "id": claims.get("oid") or claims.get("sub"),  # Azure OID is the stable user GUID
        "email": email,
        "role": _role,
        "groups": [],    # Group membership checked separately via Cognito group
        "display_name": name or f"{given_name} {family_name}".strip() or email,
        "given_name": given_name,
        "family_name": family_name,
        "auth_method": "teams_sso",
    }
