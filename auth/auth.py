"""Auth service main entry point."""

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import urlencode
import os
import secrets
import httpx
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from settings import get_settings
from utils.oauth import exchange_code_for_tokens, validate_jwt_token
from utils.middleware import validate_request_token
from services.proxy import proxy_request
from utils.logger import setup_logger
from utils.state_storage import store_oauth_state, get_oauth_state, delete_oauth_state

# Import OpenTelemetry instrumentation
try:
    from common.telemetry import init_telemetry, instrument_fastapi
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

settings = get_settings()
log_level = os.getenv("LOG_LEVEL", "INFO")
logger = setup_logger("auth", level=log_level)

# Initialize OpenTelemetry
if OTEL_AVAILABLE:
    tracer, meter = init_telemetry(
        service_name="aurora-auth",
        service_version="1.0.0"
    )
else:
    tracer, meter = None, None

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Aurora Auth Service", 
    version="1.0.0",
    max_request_size=1024 * 1024  # 1 MB max request size
)

# Add rate limiter to app state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Instrument FastAPI with OpenTelemetry
if OTEL_AVAILABLE:
    instrument_fastapi(app)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.application_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# This is Aurora Application specific. Most likely this will not be needed in other projects. Or if so it will need to be modified.
async def _sync_user_on_login(user_id: str, email: str, display_name: str = None, given_name: str = None, family_name: str = None):
    """
    Sync user to backend (Postgres + Neo4j) on login.
    
    This is called once per login session to ensure the user exists in:
    1. Postgres (app_users table)
    2. Neo4j (Person node)
    
    The backend's get_or_create_user endpoint handles:
    - Creating user in Postgres if doesn't exist
    - Syncing to Neo4j with smart deduplication
    - Updating existing Person nodes with user_uuid
    
    Args:
        user_id: Cognito user UUID (sub claim)
        email: User email
        display_name: Optional display name / full name
        given_name: Optional first name
        family_name: Optional last name
    """
    logger.info(f"Syncing user {user_id} ({email}) to backend")
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.backend_service_url}/internal/sync-user",
                json={
                    "user_id": user_id,
                    "email": email,
                    "display_name": display_name,
                    "given_name": given_name,
                    "family_name": family_name
                }
            )
            
            if response.status_code == 200:
                logger.info(f"User {user_id} synced successfully to backend")
            else:
                logger.warning(
                    f"Failed to sync user {user_id}: "
                    f"status={response.status_code}, response={response.text}"
                )
    except Exception as e:
        # Don't fail login if backend sync fails - just log it
        logger.error(f"Error syncing user {user_id} to backend: {e}")


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "ok", "service": "auth"}


@app.get("/api/auth/login")
@limiter.limit("10/minute")  # Max 10 login attempts per minute per IP
async def login(request: Request):
    """
    Redirect to Cognito Hosted UI for login.
    Includes state parameter for CSRF protection.
    """
    # Generate cryptographically secure state parameter
    state = secrets.token_urlsafe(32)
    
    # Store state in Redis with automatic expiration (5 minutes)
    store_oauth_state(state, {
        "ip": request.client.host,
        "user_agent": request.headers.get("user-agent")
    })
    
    params = {
        "client_id": settings.cognito_app_client_id,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": settings.oauth_redirect_uri,
        "state": state,  # CSRF protection
    }
    
    cognito_login_url = f"https://{settings.cognito_domain}/login?{urlencode(params)}"
    return RedirectResponse(url=cognito_login_url)


@app.get("/api/auth/callback")
@limiter.limit("20/minute")  # Max 20 callback attempts per minute per IP
async def auth_callback(code: str, state: str, request: Request):
    """
    OAuth callback endpoint. Exchanges authorization code for tokens
    and sets httpOnly cookies.
    """
    try:
        # Verify state parameter (CSRF protection)
        stored_state = get_oauth_state(state)
        if not stored_state:
            logger.warning(f"Invalid or expired state parameter: state={state}, ip={request.client.host}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication request"
            )
        
        # Clean up used state (one-time use)
        delete_oauth_state(state)
        
        # Exchange code for tokens
        logger.info(f"Exchanging authorization code for tokens: code={code[:8]}..., state={state[:8]}...")
        tokens = await exchange_code_for_tokens(code)
        logger.info(f"Token exchange successful, validating ID token")
        
        # Validate ID token to get user info (pass access_token for at_hash validation)
        id_token_claims = await validate_jwt_token(tokens["id_token"], access_token=tokens["access_token"])
        user_id = id_token_claims.get("sub")  # Cognito user UUID
        user_email = id_token_claims.get("email")
        
        # Extract name information - Cognito standard attributes
        given_name = id_token_claims.get("given_name")  # First name
        family_name = id_token_claims.get("family_name")  # Last name
        display_name = id_token_claims.get("name") or id_token_claims.get("preferred_username")
        
        # Construct full name from parts if not provided
        if not display_name and (given_name or family_name):
            display_name = f"{given_name or ''} {family_name or ''}".strip()
        
        user_role = id_token_claims.get("custom:role", "user")
        
        logger.info(
            f"Successful authentication: user={user_email}, role={user_role}, "
            f"name={display_name}, ip={request.client.host}, user_agent={request.headers.get('user-agent')}"
        )
        
        # Aurora Application specific logic:
        # Sync user to backend (Postgres + Neo4j) on login
        # This ensures user exists in both databases before they access any endpoints
        await _sync_user_on_login(user_id, user_email, display_name, given_name, family_name)
        
        # Create response redirecting to frontend home page
        response = RedirectResponse(url=f"{settings.application_url}/")
        
        # Set httpOnly cookies with tokens
        response.set_cookie(
            key="access_token",
            value=tokens["access_token"],
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            max_age=3600,  # 1 hour
            domain=settings.validated_cookie_domain
        )
        
        response.set_cookie(
            key="id_token",
            value=tokens["id_token"],
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            max_age=3600,  # 1 hour (same as access token)
            domain=settings.validated_cookie_domain
        )
        
        response.set_cookie(
            key="refresh_token",
            value=tokens["refresh_token"],
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            max_age=604800,  # 7 days
            domain=settings.validated_cookie_domain
        )
        
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Authentication failed: error={str(e)}, ip={request.client.host}, "
            f"user_agent={request.headers.get('user-agent')}"
        )
        # Redirect to frontend with generic error
        error_url = f"{settings.application_url}/?error=auth_failed"
        return RedirectResponse(url=error_url)


@app.get("/api/auth/logout")
async def logout(request: Request):
    """
    Clear auth cookies and redirect to Cognito logout.
    """
    # Try to log user info if available
    try:
        user_info = await validate_request_token(request)
        logger.info(
            f"User logout: user={user_info.get('email')}, "
            f"ip={request.client.host}, user_agent={request.headers.get('user-agent')}"
        )
    except Exception:
        logger.info(f"Logout attempt (no valid session): ip={request.client.host}")
    
    # Build Cognito logout URL and redirect
    response = RedirectResponse(
        url=f"https://{settings.cognito_domain}/logout?"
            f"client_id={settings.cognito_app_client_id}&"
            f"logout_uri={settings.application_url}"
    )
    
    # Clear cookies
    response.delete_cookie(key="access_token", domain=settings.validated_cookie_domain)
    response.delete_cookie(key="id_token", domain=settings.validated_cookie_domain)
    response.delete_cookie(key="refresh_token", domain=settings.validated_cookie_domain)
    
    return response


@app.get("/api/auth/me")
async def get_current_user(request: Request):
    """
    Get current user info from token.
    """
    user_info = await validate_request_token(request)
    return user_info


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_to_services(request: Request, path: str):
    """
    Main proxy endpoint. Validates token and forwards to internal services.
    Handles all /api/backend/*, /api/curator/*, /api/retriever/* routes.
    """
    # Validate token and get user info
    user_info = await validate_request_token(request)
    
    # Log the authenticated request with security context
    logger.info(
        f"Proxying request: user={user_info['email']}, role={user_info['role']}, "
        f"method={request.method}, path=/{path}, ip={request.client.host}"
    )
    
    # Proxy request to internal service
    response = await proxy_request(request, user_info)
    
    # Log the response status
    logger.debug(f"Response status: {response.status_code}, user={user_info['email']}")
    
    # If token was refreshed, update cookie
    if hasattr(request.state, "new_access_token"):
        response.set_cookie(
            key="access_token",
            value=request.state.new_access_token,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            max_age=3600,
            domain=settings.validated_cookie_domain
        )
        logger.info(f"Token refreshed for user: {user_info['email']}")
    
    return response


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
