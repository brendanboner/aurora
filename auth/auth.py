"""Auth service main entry point."""

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import urlencode
import os
import secrets
import httpx
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from settings import get_settings
from utils.oauth import exchange_code_for_tokens, validate_jwt_token, extract_user_info, validate_user_group, validate_azure_sso_token, extract_azure_user_info
from utils.middleware import validate_request_token
from services.proxy import proxy_request
from utils.logger import setup_logger
from utils.state_storage import store_oauth_state, get_oauth_state, delete_oauth_state, store_teams_session, delete_teams_session, store_cognito_id_map

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
    max_request_size=50 * 1024 * 1024  # 50 MB max request size for file uploads
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
    allow_origins=[settings.effective_application_url],
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
                data = response.json()
                # The backend may return the EXISTING internal user_id if the SSO OID
                # was linked to a pre-existing account (sso_id mapping). Use that stable
                # internal ID so all downstream X-User-Id lookups hit the right account.
                resolved_id = data.get("user_id") or user_id
                if resolved_id != user_id:
                    logger.info(f"SSO mapping: Azure OID {user_id} resolved to internal ID {resolved_id}")
                    # Persist sub→internal_id in Redis so validate_request_token can
                    # substitute the stable id into X-User-Id without a DB round-trip.
                    store_cognito_id_map(user_id, resolved_id)
                logger.info(f"User {user_id} synced successfully to backend (internal id={resolved_id})")
                return resolved_id
            else:
                logger.warning(
                    f"Failed to sync user {user_id}: "
                    f"status={response.status_code}, response={response.text}"
                )
    except Exception as e:
        # Don't fail login if backend sync fails - just log it
        logger.error(f"Error syncing user {user_id} to backend: {e}")
    return user_id  # Fall back to the SSO ID if sync fails


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
            # Instead of showing an error, redirect to login to start fresh OAuth flow
            # This handles the case where user left login page open and came back later
            logger.info(f"Redirecting to login to start fresh OAuth flow")
            return RedirectResponse(url="/api/auth/login")
        
        # Clean up used state (one-time use)
        delete_oauth_state(state)
        
        # Exchange code for tokens
        logger.info(f"Exchanging authorization code for tokens: code={code[:8]}..., state={state[:8]}...")
        tokens = await exchange_code_for_tokens(code)
        logger.info(f"Token exchange successful, validating ID token")
        
        # Validate ID token to get user info (pass access_token for at_hash validation)
        id_token_claims = await validate_jwt_token(tokens["id_token"], access_token=tokens["access_token"])
        
        # Extract user info including groups
        user_info = extract_user_info(id_token_claims)
        
        # Validate user is in at least one of the required groups - reject login if not
        validate_user_group(user_info, settings.allowed_cognito_groups)
        
        user_id = id_token_claims.get("sub")  # Cognito user UUID
        user_email = id_token_claims.get("email")
        
        # Extract name information - Cognito standard attributes
        given_name = id_token_claims.get("given_name")  # First name
        family_name = id_token_claims.get("family_name")  # Last name
        display_name = id_token_claims.get("name") or id_token_claims.get("preferred_username")
        
        # Construct full name from parts if not provided
        if not display_name and (given_name or family_name):
            display_name = f"{given_name or ''} {family_name or ''}".strip()
        
        # Role: prefer Cognito's custom:role; fall back to override list (for SSO migration)
        user_role = id_token_claims.get("custom:role") or settings.get_role_for_email(user_email)
        
        logger.info(
            f"Successful authentication: user={user_email}, role={user_role}, "
            f"name={display_name}, ip={request.client.host}, user_agent={request.headers.get('user-agent')}"
        )
        
        # Aurora Application specific logic:
        # Sync user to backend (Postgres + Neo4j) on login
        # This ensures user exists in both databases before they access any endpoints
        await _sync_user_on_login(user_id, user_email, display_name, given_name, family_name)
        
        # Create response redirecting to frontend home page
        response = RedirectResponse(url=f"{settings.effective_application_url}/")
        
        # Set httpOnly cookies with tokens
        # Access/ID tokens: 1 hour cookie lifetime (matches actual token expiration)
        # Refresh token: 5 days (matches Cognito refresh token lifetime)
        # When access/ID token cookies expire, the middleware will use the refresh
        # token to obtain new ones seamlessly.
        response.set_cookie(
            key="access_token",
            value=tokens["access_token"],
            httponly=True,
            secure=settings.effective_cookie_secure,
            samesite="strict",
            max_age=3600,  # 1 hour (matches actual token expiration)
            domain=settings.validated_cookie_domain
        )
        
        response.set_cookie(
            key="id_token",
            value=tokens["id_token"],
            httponly=True,
            secure=settings.effective_cookie_secure,
            samesite="strict",
            max_age=3600,  # 1 hour (matches actual token expiration)
            domain=settings.validated_cookie_domain
        )
        
        response.set_cookie(
            key="refresh_token",
            value=tokens["refresh_token"],
            httponly=True,
            secure=settings.effective_cookie_secure,
            samesite="strict",
            max_age=432000,  # 5 days (matches Cognito refresh token lifetime)
            domain=settings.validated_cookie_domain
        )
        
        return response
    
    except HTTPException as http_exc:
        # Handle HTTP exceptions (like group validation failures) by redirecting to error page
        logger.error(
            f"Authentication failed: status={http_exc.status_code}, detail={http_exc.detail}, "
            f"ip={request.client.host}, user_agent={request.headers.get('user-agent')}"
        )
        # Redirect to frontend with generic error
        error_url = f"{settings.effective_application_url}/?error=auth_failed"
        return RedirectResponse(url=error_url)
    except Exception as e:
        logger.error(
            f"Authentication failed: error={str(e)}, ip={request.client.host}, "
            f"user_agent={request.headers.get('user-agent')}"
        )
        # Redirect to frontend with generic error
        error_url = f"{settings.effective_application_url}/?error=auth_failed"
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
            f"logout_uri={settings.effective_application_url}"
    )
    
    # Clear cookies
    response.delete_cookie(key="access_token", domain=settings.validated_cookie_domain)
    response.delete_cookie(key="id_token", domain=settings.validated_cookie_domain)
    response.delete_cookie(key="refresh_token", domain=settings.validated_cookie_domain)
    
    return response


@app.post("/api/auth/teams-sso")
@limiter.limit("30/minute")
async def teams_sso_exchange(request: Request):
    """
    Exchange a Microsoft Teams SSO token for an Aurora session.

    The Teams JS SDK's authentication.getAuthToken() returns an Azure AD JWT.
    This endpoint validates that token, extracts the user's identity, syncs them
    to the Aurora backend, then issues a `teams_session` httpOnly cookie so the
    user can call all /api/* endpoints without a full Cognito redirect.

    Required environment variables:
      AZURE_TENANT_ID      — Azure AD tenant GUID
      AZURE_APP_CLIENT_ID  — Azure App Registration client ID (same as manifest webApplicationInfo.id)
    """
    if not settings.azure_tenant_id or not settings.azure_app_client_id:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "Teams SSO is not configured. "
                "Set AZURE_TENANT_ID and AZURE_APP_CLIENT_ID environment variables."
            ),
        )

    body = await request.json()
    sso_token = body.get("token")
    if not sso_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing 'token' in request body")

    # Validate the Azure AD token
    claims = await validate_azure_sso_token(sso_token, settings.azure_tenant_id, settings.azure_app_client_id)
    user_info = extract_azure_user_info(claims)

    logger.info(f"Teams SSO: validated user email={user_info.get('email')}, id={user_info.get('id')}")

    # Sync user to Aurora backend (Postgres + Neo4j).
    # resolved_id is the INTERNAL stable user ID — it may differ from user_info["id"]
    # (Azure OID) if the user was originally registered via Cognito and their SSO OID
    # was stored in the sso_id column rather than migrating the primary key.
    resolved_id = await _sync_user_on_login(
        user_id=user_info["id"],
        email=user_info["email"],
        display_name=user_info.get("display_name"),
        given_name=user_info.get("given_name"),
        family_name=user_info.get("family_name"),
    )

    # Store the INTERNAL id (not the Azure OID) in the session so X-User-Id
    # headers carry the ID that all downstream database tables reference.
    session_user_info = {**user_info, "id": resolved_id or user_info["id"]}

    # Create a session in Redis and return a session cookie
    session_id = secrets.token_urlsafe(32)
    store_teams_session(session_id, session_user_info)

    response = JSONResponse(content={"status": "ok", "email": user_info["email"]})
    response.set_cookie(
        key="teams_session",
        value=session_id,
        httponly=True,
        secure=settings.effective_cookie_secure,
        # Teams iframe requires samesite=none (cross-origin) when served over HTTPS
        samesite="none" if settings.effective_cookie_secure else "lax",
        max_age=3600,  # 1 hour
        domain=settings.validated_cookie_domain,
    )
    return response




@app.post("/api/auth/teams-email-fallback")
@limiter.limit("20/minute")
async def teams_email_fallback(request: Request):
    """
    Interim Teams auth fallback: if the Azure AD SSO exchange isn't configured,
    a Teams tab can call this endpoint with the user's UPN (Teams userPrincipalName,
    which is their corporate email address). If that email is already registered in
    Aurora via Cognito, we issue a teams_session cookie and the user can query without
    a Cognito redirect.

    Security note: this trusts the email from the Teams JS SDK context without
    cryptographic proof. It is safe for demo/internal use under Docker network
    isolation, but should be disabled (TEAMS_EMAIL_FALLBACK_ENABLED=false) once
    proper AZURE_TENANT_ID / AZURE_APP_CLIENT_ID are configured.
    """
    if not getattr(settings, "teams_email_fallback_enabled", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Teams email fallback is disabled. Configure Azure SSO credentials.",
        )

    body = await request.json()
    email = (body.get("email") or "").lower().strip()
    upn = (body.get("upn") or email).lower().strip()

    if not email and not upn:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing 'email' or 'upn'")

    lookup_email = email or upn

    # Verify the user exists in Aurora (registered via Cognito)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.backend_service_url}/internal/lookup-user-by-email/{lookup_email}"
            )
    except Exception as e:
        logger.error(f"Teams email fallback: backend lookup failed: {e}")
        raise HTTPException(status_code=503, detail="User lookup service unavailable")

    if resp.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No Aurora account found for {lookup_email}. Ask an admin to create one.",
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="User lookup failed")

    user_data = resp.json()
    logger.info(f"Teams email fallback: issuing session for {lookup_email}")

    user_info = {
        "id": user_data["id"],
        "email": user_data["email"],
        "display_name": user_data.get("display_name") or user_data["email"],
        "role": user_data.get("role", "user"),
        "auth_method": "teams_email_fallback",
    }

    session_id = secrets.token_urlsafe(32)
    store_teams_session(session_id, user_info)

    response = JSONResponse(content={"status": "ok", "email": user_info["email"]})
    response.set_cookie(
        key="teams_session",
        value=session_id,
        httponly=True,
        secure=settings.effective_cookie_secure,
        samesite="none" if settings.effective_cookie_secure else "lax",
        max_age=3600,
        domain=settings.validated_cookie_domain,
    )
    return response



async def teams_sso_logout(request: Request):
    """Clear a Teams SSO session (called when user logs out from within the Teams tab)."""
    session_id = request.cookies.get("teams_session")
    if session_id:
        delete_teams_session(session_id)
    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie(key="teams_session", domain=settings.validated_cookie_domain)
    return response


@app.get("/api/auth/me")
async def get_current_user(request: Request):
    user_info = await validate_request_token(request)
    
    # Create response with user info
    response = JSONResponse(content=user_info)
    
    # If token was refreshed during validation, update cookies
    if hasattr(request.state, "new_access_token"):
        response.set_cookie(
            key="access_token",
            value=request.state.new_access_token,
            httponly=True,
            secure=settings.effective_cookie_secure,
            samesite="strict",
            max_age=3600,  # 1 hour
            domain=settings.validated_cookie_domain
        )
        logger.info(f"Access token refreshed for user: {user_info.get('email')}")
    
    if hasattr(request.state, "new_id_token"):
        response.set_cookie(
            key="id_token",
            value=request.state.new_id_token,
            httponly=True,
            secure=settings.effective_cookie_secure,
            samesite="strict",
            max_age=3600,  # 1 hour
            domain=settings.validated_cookie_domain
        )
    
    return response


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
    
    # If token was refreshed, update cookies
    if hasattr(request.state, "new_access_token"):
        response.set_cookie(
            key="access_token",
            value=request.state.new_access_token,
            httponly=True,
            secure=settings.effective_cookie_secure,
            samesite="strict",
            max_age=3600,  # 1 hour
            domain=settings.validated_cookie_domain
        )
        logger.info(f"Access token refreshed for user: {user_info['email']}")
    
    # Update ID token if it was also refreshed
    if hasattr(request.state, "new_id_token"):
        response.set_cookie(
            key="id_token",
            value=request.state.new_id_token,
            httponly=True,
            secure=settings.effective_cookie_secure,
            samesite="strict",
            max_age=3600,  # 1 hour
            domain=settings.validated_cookie_domain
        )
        logger.info(f"ID token refreshed for user: {user_info['email']}")
    
    return response


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
