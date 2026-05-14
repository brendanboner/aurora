# Authentication Implementation Plan

## Document Purpose
This is a comprehensive, step-by-step implementation guide for adding authentication to the octo-rapid-aurora application. Follow this plan sequentially. If you get stuck or need clarification, refer back to the [AUTH_ARCHITECTURE.md](./AUTH_ARCHITECTURE.md) for architectural context.

## Prerequisites
- Docker and Docker Compose installed
- AWS account with Cognito access
- Python 3.9+ for backend services

**Note**: The authentication architecture is frontend-agnostic. While Phase 4 provides a React implementation example, the auth service works with any frontend framework (Vue, Angular, vanilla JS, mobile apps, etc.) as long as it:
1. Can redirect to Cognito Hosted UI for login
2. Receives and stores httpOnly cookies from the auth service
3. Sends cookies with API requests (`credentials: 'include'`)

You can skip or adapt Phase 4 based on your frontend needs.

---

## Table of Contents
1. [Phase 1: AWS Cognito Setup](#phase-1-aws-cognito-setup)
2. [Phase 2: Auth Service Implementation](#phase-2-auth-service-implementation)
3. [Phase 3: Internal Service Security](#phase-3-internal-service-security)
4. [Phase 4: Frontend Integration](#phase-4-frontend-integration)
5. [Phase 5: Docker Compose Integration](#phase-5-docker-compose-integration)
6. [Phase 6: Testing](#phase-6-testing)
7. [Phase 7: Deployment Preparation](#phase-7-deployment-preparation)
8. [Reference: Code Templates](#reference-code-templates)
9. [Troubleshooting Guide](#troubleshooting-guide)

---

## Phase 1: AWS Cognito Setup

### Objective
Set up AWS Cognito User Pool with proper configuration for OAuth 2.0 authentication.

### Steps

#### 1.1 Create Cognito User Pool

**Via AWS Console:**
1. Navigate to AWS Cognito in your AWS Console
2. Click "Create user pool"
3. Choose "Email" as sign-in option
4. **Configure password policy (IMPORTANT FOR SECURITY)**:
   - Minimum password length: **12 characters** (increase from default 8)
   - Require uppercase letters: **Yes**
   - Require lowercase letters: **Yes**
   - Require numbers: **Yes**
   - Require special characters: **Yes**
   - Prevent password reuse: **Yes** (remember last 5 passwords)
5. Enable MFA: Optional (recommended: **OFF for development, ON for production**)
   - **For production**: Enable MFA for admin and superadmin roles
6. Enable self-service account recovery: Email only

**Save these values** (you'll need them later):
- `User Pool ID`: e.g., `us-east-1_xxxxx`
- `AWS Region`: e.g., `us-east-1`

#### 1.2 Configure Custom Attributes

1. In your User Pool, go to "Sign-up experience" > "Custom attributes"
2. Add custom attribute:
   - **Attribute name**: `role`
   - **Type**: String
   - **Mutable**: Yes
   - **Required**: No

**Note**: This will be accessible as `custom:role` in JWT tokens.

#### 1.3 Create App Client

1. In your User Pool, go to "App integration" > "App clients"
2. Click "Create app client"
3. Configure:
   - **App client name**: `octo-aurora-web`
   - **Client secret**: Generate (Confidential client)
   - **Authentication flows**: 
     - ✅ ALLOW_USER_PASSWORD_AUTH
     - ✅ ALLOW_REFRESH_TOKEN_AUTH
   - **OAuth 2.0 grant types**:
     - ✅ Authorization code grant
   - **OAuth scopes**:
     - ✅ openid
     - ✅ email
     - ✅ profile
   - **Callback URLs**: 
     - Development: `http://localhost:8000/api/auth/callback`
     - Production: `https://yourdomain.com/api/auth/callback`
   - **Sign-out URLs**:
     - Development: `http://localhost:3000`
     - Production: `https://yourdomain.com`

**Save these values**:
- `Client ID`: e.g., `7xxxxxxxxxxxxx`
- `Client Secret`: e.g., `xxxxxxxxxxxxxxxxxxxxxxxx` (keep secure!)

#### 1.4 Configure Hosted UI Domain

1. Go to "App integration" > "Domain"
2. Choose "Use a Cognito domain"
3. Enter domain prefix: e.g., `octo-aurora-dev`
4. Click "Create"

**Save this value**:
- `Cognito Domain`: e.g., `octo-aurora-dev.auth.us-east-1.amazoncognito.com`

#### 1.5 Create Test Users

1. Go to "Users" tab
2. Click "Create user"
3. Create test users for each role:

**User 1 (Regular User)**:
- Email: `testuser@example.com`
- Temporary password: (you choose)
- Custom attribute `role`: `user`

**User 2 (Admin)**:
- Email: `admin@example.com`
- Temporary password: (you choose)
- Custom attribute `role`: `admin`

**User 3 (Super Admin)**:
- Email: `superadmin@example.com`
- Temporary password: (you choose)
- Custom attribute `role`: `superadmin`

#### 1.6 Document Your Configuration

Add the following to your root `.env` file (the one used by Docker Compose):
```env
# AWS Cognito Configuration
AWS_REGION=us-east-1
COGNITO_USER_POOL_ID=us-east-1_xxxxx
COGNITO_APP_CLIENT_ID=7xxxxxxxxxxxxx
COGNITO_APP_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx
COGNITO_DOMAIN=octo-aurora-dev.auth.us-east-1.amazoncognito.com
COGNITO_JWKS_URL=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_xxxxx/.well-known/jwks.json
COGNITO_TOKEN_ENDPOINT=https://octo-aurora-dev.auth.us-east-1.amazoncognito.com/oauth2/token

# Service URLs (internal Docker network)
# Note: These use internal container ports (8000), not host-mapped ports
BACKEND_SERVICE_URL=http://backend:8000
CURATOR_SERVICE_URL=http://curator:8000
RETRIEVER_SERVICE_URL=http://retriever:8000

# Frontend
FRONTEND_URL=http://localhost:3000
COOKIE_DOMAIN=localhost
COOKIE_SECURE=false

# For Production, change to:
# FRONTEND_URL=https://yourdomain.com
# COOKIE_DOMAIN=yourdomain.com
# COOKIE_SECURE=true
```

**Note**: Docker Compose will pass these variables to each service as configured in `docker-compose.yml`.

---

## Phase 2: Auth Service Implementation

### Objective
Build the FastAPI auth service that handles OAuth, token validation, and request proxying.

### 2.1 Create Auth Service Directory Structure

```bash
mkdir -p auth/services auth/utils
cd auth
touch Dockerfile requirements.txt auth.py settings.py
touch services/__init__.py services/proxy.py
touch utils/__init__.py utils/logger.py utils/oauth.py utils/middleware.py
```

**Directory structure:**
```
auth/
├── Dockerfile
├── requirements.txt
├── auth.py              # Main entry point
├── settings.py          # Configuration/settings (like other services)
├── services/
│   ├── __init__.py
│   └── proxy.py         # Request forwarding to internal services
└── utils/
    ├── __init__.py
    ├── logger.py        # Logger configuration
    ├── oauth.py         # OAuth & JWT helper functions
    └── middleware.py    # JWT validation helper functions
```

**Note**: Environment variables will be provided by Docker Compose from the root `.env` file.

### 2.2 Create `utils/logger.py`

```python
"""Logger setup for the auth service."""

import logging
import sys


def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """
    Setup and configure logger.
    
    Args:
        name: Logger name
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    
    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, level.upper()))
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    # Add handler to logger
    if not logger.handlers:
        logger.addHandler(handler)
    
    return logger
```

### 2.3 Create `requirements.txt`

```txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
python-jose[cryptography]==3.3.0
httpx==0.25.1
python-dotenv==1.0.0
pydantic==2.5.0
pydantic-settings==2.1.0
slowapi==0.1.9
```

### 2.4 Create `settings.py`

```python
"""Auth service settings configuration."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # AWS Cognito
    aws_region: str
    cognito_user_pool_id: str
    cognito_app_client_id: str
    cognito_app_client_secret: str
    cognito_domain: str
    cognito_jwks_url: str
    cognito_token_endpoint: str
    
    # Service URLs
    backend_service_url: str
    curator_service_url: str
    retriever_service_url: str
    
    # Frontend
    frontend_url: str
    cookie_domain: str
    cookie_secure: bool = True
    
    # Computed properties
    @property
    def cognito_issuer(self) -> str:
        return f"https://cognito-idp.{self.aws_region}.amazonaws.com/{self.cognito_user_pool_id}"
    
    @property
    def oauth_redirect_uri(self) -> str:
        """Dynamically construct redirect URI"""
        # For local development, use port 8000
        if "localhost" in self.frontend_url:
            return "http://localhost:8000/api/auth/callback"
        return f"{self.frontend_url.replace('http://', 'https://')}/api/auth/callback"
    
    @property
    def validated_cookie_domain(self) -> str:
        """Validate and return cookie domain"""
        domain = self.cookie_domain
        
        # Prevent overly broad wildcard domains
        if domain.startswith('.'):
            raise ValueError("Cookie domain should not start with '.' - this allows subdomains which may be insecure")
        
        # Prevent secure cookies on localhost (they won't work)
        if domain == 'localhost' and self.cookie_secure:
            raise ValueError("Cannot use secure cookies with localhost. Set COOKIE_SECURE=false for development")
        
        return domain
    
    class Config:
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
```

### 2.5 Create `utils/oauth.py`

```python
"""OAuth and JWT token validation utilities."""

import httpx
from jose import jwt, jwk, JWTError
from jose.utils import base64url_decode
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import time
from fastapi import HTTPException, status
from settings import get_settings

settings = get_settings()

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


async def validate_jwt_token(token: str) -> Dict[str, Any]:
    """
    Validate JWT token from Cognito.
    Returns decoded token claims if valid.
    Raises HTTPException if invalid.
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
            issuer=settings.cognito_issuer
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
            import logging
            logger = logging.getLogger("auth")
            logger.error(f"Token exchange failed: status={response.status_code}, body={response.text}")
            
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Authentication failed. Please try again."
            )
        
        return response.json()


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
```

### 2.6 Create `utils/middleware.py`

```python
"""JWT validation middleware utilities."""

from fastapi import Request, HTTPException, status
from typing import Optional
from .oauth import validate_jwt_token, refresh_access_token, extract_user_info
from settings import get_settings

settings = get_settings()


async def validate_request_token(request: Request) -> dict:
    """
    Middleware function to validate JWT token from cookies.
    Automatically refreshes token if expired.
    Returns user info dict.
    """
    # Get access token from cookie
    access_token = request.cookies.get("access_token")
    refresh_token = request.cookies.get("refresh_token")
    
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No access token provided"
        )
    
    try:
        # Try to validate access token
        token_claims = await validate_jwt_token(access_token)
        user_info = extract_user_info(token_claims)
        return user_info
    
    except HTTPException as e:
        # If access token expired, try to refresh
        if "expired" in str(e.detail).lower() and refresh_token:
            try:
                # Get new access token using refresh token
                new_tokens = await refresh_access_token(refresh_token)
                new_access_token = new_tokens["access_token"]
                
                # Validate new token and extract user info
                token_claims = await validate_jwt_token(new_access_token)
                user_info = extract_user_info(token_claims)
                
                # Store new token for response (will be set by proxy)
                request.state.new_access_token = new_access_token
                return user_info
            
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token refresh failed. Please login again."
                )
        
        # Re-raise original exception if not expired or no refresh token
        raise e
```

### 2.7 Create `services/proxy.py`

```python
"""Request proxying service for forwarding to internal services."""

import httpx
from fastapi import Request, Response, HTTPException
from typing import Dict
from settings import get_settings

settings = get_settings()

# Service URL mapping
SERVICE_ROUTES = {
    "/api/backend": settings.backend_service_url,
    "/api/curator": settings.curator_service_url,
    "/api/retriever": settings.retriever_service_url,
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
    
    # Validate content-type for methods that send bodies
    if request.method in ["POST", "PUT", "PATCH"]:
        content_type = request.headers.get("content-type", "")
        if not content_type.startswith(("application/json", "application/x-www-form-urlencoded", "multipart/form-data")):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Unsupported media type"
            )
    
    # Prepare headers - only forward safe headers (prevents header injection)
    headers = {
        k: v for k, v in request.headers.items() 
        if k.lower() in SAFE_HEADERS
    }
    
    # Add user context headers (these are trusted as they come from our validation)
    headers["X-User-Id"] = user_info["user_id"]
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
                content=await request.body(),
                params=request.query_params,
                timeout=30.0
            )
            
            # Create response with same status and content
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
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
```

### 2.8 Create `auth.py`

```python
"""Auth service main entry point."""

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import urlencode
import os
import secrets
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from settings import get_settings
from utils.oauth import exchange_code_for_tokens, validate_jwt_token, extract_user_info
from utils.middleware import validate_request_token
from services.proxy import proxy_request
from utils.logger import setup_logger

settings = get_settings()
log_level = os.getenv("LOG_LEVEL", "INFO")
logger = setup_logger("auth", level=log_level)

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

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory state storage (for development - use Redis in production)
_oauth_states = {}


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
    
    # Store state temporarily (in production, use Redis with TTL)
    _oauth_states[state] = {
        "ip": request.client.host,
        "user_agent": request.headers.get("user-agent")
    }
    
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
        stored_state = _oauth_states.get(state)
        if not stored_state:
            logger.warning(f"Invalid or expired state parameter: state={state}, ip={request.client.host}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication request"
            )
        
        # Clean up used state
        del _oauth_states[state]
        
        # Exchange code for tokens
        tokens = await exchange_code_for_tokens(code)
        
        # Validate ID token to get user info
        id_token_claims = await validate_jwt_token(tokens["id_token"])
        user_email = id_token_claims.get("email")
        user_role = id_token_claims.get("custom:role", "user")
        
        logger.info(
            f"Successful authentication: user={user_email}, role={user_role}, "
            f"ip={request.client.host}, user_agent={request.headers.get('user-agent')}"
        )
        
        # Create response redirecting to frontend
        response = RedirectResponse(url=f"{settings.frontend_url}/home")
        
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
        error_url = f"{settings.frontend_url}/?error=auth_failed"
        return RedirectResponse(url=error_url)


@app.post("/api/auth/logout")
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
    
    response = RedirectResponse(
        url=f"https://{settings.cognito_domain}/logout?"
            f"client_id={settings.cognito_app_client_id}&"
            f"logout_uri={settings.frontend_url}"
    )
    
    # Clear cookies
    response.delete_cookie(key="access_token", domain=settings.validated_cookie_domain)
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
    
    # Log admin/superadmin access for security monitoring
    if user_info['role'] in ['admin', 'superadmin']:
        logger.warning(
            f"Privileged access: user={user_info['email']}, role={user_info['role']}, "
            f"endpoint=/{path}, ip={request.client.host}"
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
```

### 2.9 Create `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY auth.py settings.py ./
COPY services/ ./services/
COPY utils/ ./utils/

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "auth:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 2.10 Create Comprehensive Test Suite

**Critical**: As a security-critical service, the auth service requires robust testing that can be run anytime modifications are made.

#### 2.10.1 Create Test Directory Structure

```bash
cd auth
mkdir -p tests
touch tests/__init__.py tests/conftest.py
touch tests/test_oauth.py tests/test_middleware.py tests/test_proxy.py tests/test_endpoints.py
```

**Directory structure:**
```
auth/
├── tests/
│   ├── __init__.py
│   ├── conftest.py           # Test fixtures and configuration
│   ├── test_oauth.py          # OAuth and JWT validation tests
│   ├── test_middleware.py     # Token validation middleware tests
│   ├── test_proxy.py          # Request proxying tests
│   └── test_endpoints.py      # API endpoint tests
```

#### 2.10.2 Update `requirements.txt`

Add testing dependencies:

```txt
# Existing dependencies
fastapi==0.104.1
uvicorn[standard]==0.24.0
python-jose[cryptography]==3.3.0
httpx==0.25.1
python-dotenv==1.0.0
pydantic==2.5.0
pydantic-settings==2.1.0
slowapi==0.1.9

# Testing dependencies
pytest==7.4.3
pytest-asyncio==0.21.1
pytest-mock==3.12.0
pytest-cov==4.1.0
```

#### 2.10.3 Create `tests/conftest.py`

```python
"""Pytest configuration and shared fixtures."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch
import os

# Set test environment variables
os.environ.update({
    "AWS_REGION": "us-east-1",
    "COGNITO_USER_POOL_ID": "us-east-1_TEST",
    "COGNITO_APP_CLIENT_ID": "test_client_id",
    "COGNITO_APP_CLIENT_SECRET": "test_client_secret",
    "COGNITO_DOMAIN": "test.auth.us-east-1.amazoncognito.com",
    "COGNITO_JWKS_URL": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TEST/.well-known/jwks.json",
    "COGNITO_TOKEN_ENDPOINT": "https://test.auth.us-east-1.amazoncognito.com/oauth2/token",
    "BACKEND_SERVICE_URL": "http://backend:8000",
    "CURATOR_SERVICE_URL": "http://curator:8000",
    "RETRIEVER_SERVICE_URL": "http://retriever:8000",
    "FRONTEND_URL": "http://localhost:3000",
    "COOKIE_DOMAIN": "localhost",
    "COOKIE_SECURE": "false",
})

from auth import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def mock_jwks():
    """Mock JWKS response."""
    return {
        "keys": [
            {
                "kid": "test-key-id",
                "kty": "RSA",
                "alg": "RS256",
                "use": "sig",
                "n": "test-modulus",
                "e": "AQAB"
            }
        ]
    }


@pytest.fixture
def valid_token_claims():
    """Valid JWT token claims."""
    import time
    return {
        "sub": "test-user-123",
        "email": "testuser@example.com",
        "custom:role": "user",
        "exp": int(time.time()) + 3600,  # Expires in 1 hour
        "aud": "test_client_id",
        "iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TEST"
    }


@pytest.fixture
def expired_token_claims():
    """Expired JWT token claims."""
    import time
    return {
        "sub": "test-user-123",
        "email": "testuser@example.com",
        "custom:role": "user",
        "exp": int(time.time()) - 3600,  # Expired 1 hour ago
        "aud": "test_client_id",
        "iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TEST"
    }


@pytest.fixture
def mock_cognito_tokens():
    """Mock Cognito token response."""
    return {
        "access_token": "mock-access-token",
        "id_token": "mock-id-token",
        "refresh_token": "mock-refresh-token",
        "expires_in": 3600,
        "token_type": "Bearer"
    }
```

#### 2.10.4 Create `tests/test_oauth.py`

```python
"""Tests for OAuth and JWT validation utilities."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException
from utils.oauth import (
    get_jwks,
    validate_jwt_token,
    exchange_code_for_tokens,
    refresh_access_token,
    extract_user_info
)


class TestGetJWKS:
    """Test JWKS fetching and caching."""
    
    @pytest.mark.asyncio
    async def test_get_jwks_success(self, mock_jwks):
        """Test successful JWKS fetch."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = AsyncMock()
            mock_response.json.return_value = mock_jwks
            mock_response.raise_for_status = MagicMock()
            
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
            
            result = await get_jwks()
            assert result == mock_jwks
    
    @pytest.mark.asyncio
    async def test_get_jwks_caching(self, mock_jwks):
        """Test that JWKS is cached after first fetch."""
        # Clear cache
        import utils.oauth as oauth_module
        oauth_module._jwks_cache = None
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = AsyncMock()
            mock_response.json.return_value = mock_jwks
            mock_response.raise_for_status = MagicMock()
            
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
            
            # First call - should fetch
            result1 = await get_jwks()
            assert result1 == mock_jwks
            
            # Second call - should use cache (no new HTTP call)
            result2 = await get_jwks()
            assert result2 == mock_jwks
            assert mock_client.call_count == 1  # Only called once


class TestValidateJWTToken:
    """Test JWT token validation."""
    
    @pytest.mark.asyncio
    async def test_validate_valid_token(self, valid_token_claims, mock_jwks):
        """Test validation of a valid token."""
        mock_token = "mock.jwt.token"
        
        with patch('utils.oauth.get_jwks', return_value=mock_jwks), \
             patch('jose.jwt.get_unverified_headers', return_value={"kid": "test-key-id"}), \
             patch('jose.jwt.decode', return_value=valid_token_claims):
            
            result = await validate_jwt_token(mock_token)
            assert result == valid_token_claims
    
    @pytest.mark.asyncio
    async def test_validate_expired_token(self, expired_token_claims, mock_jwks):
        """Test validation fails for expired token."""
        mock_token = "expired.jwt.token"
        
        with patch('utils.oauth.get_jwks', return_value=mock_jwks), \
             patch('jose.jwt.get_unverified_headers', return_value={"kid": "test-key-id"}), \
             patch('jose.jwt.decode', return_value=expired_token_claims):
            
            with pytest.raises(HTTPException) as exc_info:
                await validate_jwt_token(mock_token)
            
            assert exc_info.value.status_code == 401
            assert "expired" in exc_info.value.detail.lower()
    
    @pytest.mark.asyncio
    async def test_validate_token_invalid_kid(self, mock_jwks):
        """Test validation fails when key ID not found."""
        mock_token = "mock.jwt.token"
        
        with patch('utils.oauth.get_jwks', return_value=mock_jwks), \
             patch('jose.jwt.get_unverified_headers', return_value={"kid": "wrong-key-id"}):
            
            with pytest.raises(HTTPException) as exc_info:
                await validate_jwt_token(mock_token)
            
            assert exc_info.value.status_code == 401


class TestExchangeCodeForTokens:
    """Test authorization code exchange."""
    
    @pytest.mark.asyncio
    async def test_exchange_code_success(self, mock_cognito_tokens):
        """Test successful code exchange."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_cognito_tokens
            
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            
            result = await exchange_code_for_tokens("test-auth-code")
            assert result == mock_cognito_tokens
    
    @pytest.mark.asyncio
    async def test_exchange_code_failure(self):
        """Test failed code exchange."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = AsyncMock()
            mock_response.status_code = 400
            mock_response.text = "Invalid authorization code"
            
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            
            with pytest.raises(HTTPException) as exc_info:
                await exchange_code_for_tokens("invalid-code")
            
            assert exc_info.value.status_code == 400


class TestRefreshAccessToken:
    """Test token refresh."""
    
    @pytest.mark.asyncio
    async def test_refresh_token_success(self):
        """Test successful token refresh."""
        new_tokens = {"access_token": "new-access-token"}
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.json.return_value = new_tokens
            
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            
            result = await refresh_access_token("valid-refresh-token")
            assert result == new_tokens
    
    @pytest.mark.asyncio
    async def test_refresh_token_expired(self):
        """Test refresh with expired refresh token."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = AsyncMock()
            mock_response.status_code = 401
            
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            
            with pytest.raises(HTTPException) as exc_info:
                await refresh_access_token("expired-refresh-token")
            
            assert exc_info.value.status_code == 401


class TestExtractUserInfo:
    """Test user info extraction."""
    
    def test_extract_user_info_complete(self):
        """Test extracting complete user info."""
        claims = {
            "sub": "user-123",
            "email": "test@example.com",
            "custom:role": "admin"
        }
        
        result = extract_user_info(claims)
        assert result["user_id"] == "user-123"
        assert result["email"] == "test@example.com"
        assert result["role"] == "admin"
    
    def test_extract_user_info_default_role(self):
        """Test default role when not provided."""
        claims = {
            "sub": "user-123",
            "email": "test@example.com"
        }
        
        result = extract_user_info(claims)
        assert result["role"] == "user"
```

#### 2.10.5 Create `tests/test_middleware.py`

```python
"""Tests for JWT validation middleware."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException, Request
from utils.middleware import validate_request_token


class TestValidateRequestToken:
    """Test request token validation."""
    
    @pytest.mark.asyncio
    async def test_validate_with_valid_token(self, valid_token_claims):
        """Test validation with valid access token."""
        mock_request = MagicMock(spec=Request)
        mock_request.cookies.get.side_effect = lambda key: {
            "access_token": "valid-token",
            "refresh_token": "refresh-token"
        }.get(key)
        
        with patch('utils.middleware.validate_jwt_token', return_value=valid_token_claims):
            result = await validate_request_token(mock_request)
            
            assert result["user_id"] == "test-user-123"
            assert result["email"] == "testuser@example.com"
            assert result["role"] == "user"
    
    @pytest.mark.asyncio
    async def test_validate_no_token(self):
        """Test validation fails when no token provided."""
        mock_request = MagicMock(spec=Request)
        mock_request.cookies.get.return_value = None
        
        with pytest.raises(HTTPException) as exc_info:
            await validate_request_token(mock_request)
        
        assert exc_info.value.status_code == 401
        assert "No access token" in exc_info.value.detail
    
    @pytest.mark.asyncio
    async def test_validate_expired_token_with_refresh(self, valid_token_claims):
        """Test automatic token refresh when access token expired."""
        mock_request = MagicMock(spec=Request)
        mock_request.cookies.get.side_effect = lambda key: {
            "access_token": "expired-token",
            "refresh_token": "valid-refresh-token"
        }.get(key)
        mock_request.state = MagicMock()
        
        # First call raises expired error, second call succeeds after refresh
        with patch('utils.middleware.validate_jwt_token') as mock_validate:
            mock_validate.side_effect = [
                HTTPException(401, "Token has expired"),
                valid_token_claims
            ]
            
            with patch('utils.middleware.refresh_access_token', 
                      return_value={"access_token": "new-token"}):
                result = await validate_request_token(mock_request)
                
                assert result["user_id"] == "test-user-123"
                assert hasattr(mock_request.state, 'new_access_token')
                assert mock_request.state.new_access_token == "new-token"
    
    @pytest.mark.asyncio
    async def test_validate_expired_token_refresh_fails(self):
        """Test when token refresh also fails."""
        mock_request = MagicMock(spec=Request)
        mock_request.cookies.get.side_effect = lambda key: {
            "access_token": "expired-token",
            "refresh_token": "expired-refresh-token"
        }.get(key)
        
        with patch('utils.middleware.validate_jwt_token', 
                  side_effect=HTTPException(401, "Token has expired")):
            with patch('utils.middleware.refresh_access_token', 
                      side_effect=Exception("Refresh failed")):
                
                with pytest.raises(HTTPException) as exc_info:
                    await validate_request_token(mock_request)
                
                assert exc_info.value.status_code == 401
                assert "Please login again" in exc_info.value.detail
```

#### 2.10.6 Create `tests/test_proxy.py`

```python
"""Tests for request proxying."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException, Request
from services.proxy import get_target_service_url, proxy_request


class TestGetTargetServiceURL:
    """Test URL routing logic."""
    
    def test_backend_route(self):
        """Test routing to backend service."""
        url = get_target_service_url("/api/backend/query")
        assert url == "http://backend:8000/query"
    
    def test_curator_route(self):
        """Test routing to curator service."""
        url = get_target_service_url("/api/curator/analyze")
        assert url == "http://curator:8000/analyze"
    
    def test_retriever_route(self):
        """Test routing to retriever service."""
        url = get_target_service_url("/api/retriever/documents")
        assert url == "http://retriever:8000/documents"
    
    def test_unknown_route(self):
        """Test routing fails for unknown service."""
        with pytest.raises(HTTPException) as exc_info:
            get_target_service_url("/api/unknown/endpoint")
        
        assert exc_info.value.status_code == 404


class TestProxyRequest:
    """Test request proxying."""
    
    @pytest.mark.asyncio
    async def test_proxy_success(self):
        """Test successful request proxy."""
        mock_request = MagicMock(spec=Request)
        mock_request.method = "GET"
        mock_request.url.path = "/api/backend/query"
        mock_request.headers = {"Host": "localhost"}
        mock_request.body = AsyncMock(return_value=b"")
        mock_request.query_params = {}
        
        user_info = {
            "user_id": "user-123",
            "email": "test@example.com",
            "role": "user"
        }
        
        mock_response = MagicMock()
        mock_response.content = b'{"result": "success"}'
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client_instance = mock_client.return_value.__aenter__.return_value
            mock_client_instance.request = AsyncMock(return_value=mock_response)
            
            response = await proxy_request(mock_request, user_info)
            
            assert response.status_code == 200
            assert response.body == b'{"result": "success"}'
            
            # Verify user context headers were added
            call_args = mock_client_instance.request.call_args
            headers = call_args.kwargs['headers']
            assert headers["X-User-Id"] == "user-123"
            assert headers["X-User-Email"] == "test@example.com"
            assert headers["X-User-Role"] == "user"
    
    @pytest.mark.asyncio
    async def test_proxy_service_unavailable(self):
        """Test proxy when service is unavailable."""
        mock_request = MagicMock(spec=Request)
        mock_request.method = "GET"
        mock_request.url.path = "/api/backend/query"
        mock_request.headers = {}
        mock_request.body = AsyncMock(return_value=b"")
        mock_request.query_params = {}
        
        user_info = {"user_id": "user-123", "email": "test@example.com", "role": "user"}
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client_instance = mock_client.return_value.__aenter__.return_value
            mock_client_instance.request = AsyncMock(side_effect=Exception("Connection refused"))
            
            with pytest.raises(HTTPException) as exc_info:
                await proxy_request(mock_request, user_info)
            
            assert exc_info.value.status_code == 503
```

#### 2.10.7 Create `tests/test_endpoints.py`

```python
"""Tests for API endpoints."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestHealthEndpoint:
    """Test health check endpoint."""
    
    def test_health_check(self, client):
        """Test health check returns OK."""
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "auth"}


class TestLoginEndpoint:
    """Test login endpoint."""
    
    def test_login_redirect(self, client):
        """Test login redirects to Cognito."""
        response = client.get("/api/auth/login", follow_redirects=False)
        assert response.status_code == 307
        assert "cognito" in response.headers["location"]
        assert "client_id=test_client_id" in response.headers["location"]


class TestAuthCallbackEndpoint:
    """Test OAuth callback endpoint."""
    
    def test_callback_success(self, client, mock_cognito_tokens, valid_token_claims):
        """Test successful authentication callback."""
        with patch('utils.oauth.exchange_code_for_tokens', return_value=mock_cognito_tokens), \
             patch('utils.oauth.validate_jwt_token', return_value=valid_token_claims):
            
            response = client.get(
                "/api/auth/callback?code=test-auth-code",
                follow_redirects=False
            )
            
            assert response.status_code == 307
            assert response.headers["location"] == "http://localhost:3000/home"
            
            # Verify cookies are set
            assert "access_token" in response.cookies
            assert "refresh_token" in response.cookies
            assert response.cookies["access_token"] == "mock-access-token"
    
    def test_callback_failure(self, client):
        """Test failed authentication callback."""
        with patch('utils.oauth.exchange_code_for_tokens', 
                  side_effect=Exception("Token exchange failed")):
            
            response = client.get(
                "/api/auth/callback?code=invalid-code",
                follow_redirects=False
            )
            
            assert response.status_code == 307
            assert "error=auth_failed" in response.headers["location"]


class TestLogoutEndpoint:
    """Test logout endpoint."""
    
    def test_logout_success(self, client):
        """Test logout clears cookies and redirects."""
        response = client.post("/api/auth/logout", follow_redirects=False)
        
        assert response.status_code == 307
        assert "cognito" in response.headers["location"]
        assert "logout" in response.headers["location"]


class TestAuthMeEndpoint:
    """Test /auth/me endpoint."""
    
    def test_auth_me_with_valid_token(self, client, valid_token_claims):
        """Test /auth/me with valid token."""
        with patch('utils.middleware.validate_jwt_token', return_value=valid_token_claims):
            response = client.get(
                "/api/auth/me",
                cookies={"access_token": "valid-token"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["user_id"] == "test-user-123"
            assert data["email"] == "testuser@example.com"
    
    def test_auth_me_without_token(self, client):
        """Test /auth/me without token."""
        response = client.get("/api/auth/me")
        assert response.status_code == 401


class TestProxyEndpoint:
    """Test proxy endpoint."""
    
    def test_proxy_with_authentication(self, client, valid_token_claims):
        """Test proxying request with valid authentication."""
        mock_backend_response = MagicMock()
        mock_backend_response.content = b'{"data": "test"}'
        mock_backend_response.status_code = 200
        mock_backend_response.headers = {"content-type": "application/json"}
        
        with patch('utils.middleware.validate_jwt_token', return_value=valid_token_claims), \
             patch('httpx.AsyncClient') as mock_client:
            
            mock_client_instance = mock_client.return_value.__aenter__.return_value
            mock_client_instance.request = AsyncMock(return_value=mock_backend_response)
            
            response = client.get(
                "/api/backend/query",
                cookies={"access_token": "valid-token"}
            )
            
            assert response.status_code == 200
            assert response.json() == {"data": "test"}
    
    def test_proxy_without_authentication(self, client):
        """Test proxying fails without authentication."""
        response = client.get("/api/backend/query")
        assert response.status_code == 401
```

#### 2.10.8 Create `pytest.ini`

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
asyncio_mode = auto
addopts =
    -v
    --strict-markers
    --cov=.
    --cov-report=term-missing
    --cov-report=html
    --cov-fail-under=80
```

#### 2.10.9 Run Tests

```bash
cd auth

# Install test dependencies
pip install -r requirements.txt

# Run all tests
pytest

# Run with coverage report
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_oauth.py

# Run tests matching a pattern
pytest -k "test_validate"

# Run with verbose output
pytest -v

# Run and stop on first failure
pytest -x
```

#### 2.10.10 Add Test Running to Makefile (Optional)

Create `auth/Makefile`:

```makefile
.PHONY: test test-unit test-integration coverage lint

test:
	pytest

test-unit:
	pytest tests/test_oauth.py tests/test_middleware.py

test-integration:
	pytest tests/test_endpoints.py tests/test_proxy.py

coverage:
	pytest --cov=. --cov-report=html --cov-report=term

lint:
	flake8 . --exclude=tests,__pycache__,.pytest_cache
	mypy . --exclude tests

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	rm -rf htmlcov .coverage
```

Usage:
```bash
make test          # Run all tests
make test-unit     # Run unit tests only
make coverage      # Generate coverage report
make lint          # Run linters
```

### 2.11 Test Auth Service Locally

```bash
cd auth

# Install dependencies
pip install -r requirements.txt

# Run tests first to verify everything works
pytest

# Set environment variables (use values from root .env file)
export AWS_REGION=us-east-1
export COGNITO_USER_POOL_ID=us-east-1_xxxxx
# ... (set all required variables)

# Or source them from root .env
set -a; source ../.env; set +a

# Run the service
python auth.py
```

Visit `http://localhost:8000` - you should see `{"status": "ok", "service": "auth"}`

**Note**: When running via Docker Compose, environment variables will be automatically provided.

### 2.12 Security Improvements Summary

The auth service implementation includes several critical security enhancements:

#### **CSRF Protection**
- OAuth `state` parameter prevents cross-site request forgery attacks
- State tokens are cryptographically secure (32-byte URL-safe tokens)
- State validation ensures requests originate from legitimate login flows

#### **Rate Limiting**
- Login endpoint: 10 attempts/minute per IP (prevents brute force)
- Callback endpoint: 20 attempts/minute per IP (prevents token enumeration)
- Automatic 429 responses with retry headers for exceeded limits

#### **Header Injection Prevention**
- Allowlist-based header filtering (only safe headers forwarded)
- User context headers (`X-User-*`) set exclusively by auth service
- Cannot be spoofed by malicious clients

#### **Secure Token Handling**
- Timezone-aware datetime comparisons (prevents timezone bugs)
- JWKS cache with 1-hour TTL (handles AWS key rotation)
- Generic error messages (doesn't leak internal details)

#### **Cookie Security**
- Domain validation prevents misconfiguration
- Prevents wildcard domains and localhost+secure conflicts
- httpOnly + Secure + SameSite=Strict flags

#### **Content Validation**
- Request size limits (1 MB max)
- Content-Type validation for POST/PUT/PATCH
- Rejects unsupported media types

#### **Comprehensive Logging**
- All authentication events logged with IP and user agent
- Privileged access (admin/superadmin) specially logged
- Failed attempts logged for security monitoring
- Generic errors to users, detailed logs for admins

**Production Recommendations:**
1. Replace in-memory `_oauth_states` with Redis (with TTL)
2. Set up log aggregation (CloudWatch, ELK, Datadog)
3. Configure alerting on failed login attempts
4. Monitor rate limit violations
5. Review security logs regularly

---

## Phase 3: Internal Service Context Handling

### Objective
Create shared auth middleware in the `common/` folder that all internal services (backend, curator, retriever) can copy and use to extract user context from headers sent by the auth service.

**Security Model**: This implementation relies on Docker network isolation. Internal services are not exposed publicly and can only be reached through the auth service or by other internal services. The auth service validates user authentication and passes user context via headers.

### 3.1 Create Shared Auth Middleware File

Add the auth middleware to your existing `common/` folder.

```bash
cd common
touch auth_middleware.py
```

**Directory structure:**
```
common/
├── make-utils.mk
└── auth_middleware.py    # New shared middleware
```

#### Create `common/auth_middleware.py`

```python
"""Shared authentication middleware for Aurora services.

This module provides FastAPI dependencies and decorators for handling
user authentication context passed from the auth service via headers.

Usage:
    from common.auth_middleware import get_user_context, require_user_context
    
    @app.get("/my-endpoint")
    @require_user_context
    async def my_endpoint(user: Optional[dict] = Depends(get_user_context)):
        # user is guaranteed to be not None
        return {"user": user}
"""

from fastapi import Header, HTTPException, status
from typing import Optional
from functools import wraps


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
    """
    if not x_user_id:
        return None
    
    return {
        "user_id": x_user_id,
        "email": x_user_email,
        "role": x_user_role or "user",
    }


def require_user_context(func):
    """
    Decorator to require user context for an endpoint.
    Use this for endpoints that should ONLY be called by authenticated users.
    
    Usage:
        from common.auth_middleware import get_user_context, require_user_context
        
        @app.get("/my-documents")
        @require_user_context
        async def get_my_documents(user: Optional[dict] = Depends(get_user_context)):
            # user is guaranteed to be not None here
            return get_documents_for_user(user["user_id"])
    """
    @wraps(func)
    async def wrapper(*args, user: Optional[dict] = None, **kwargs):
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication required"
            )
        return await func(*args, user=user, **kwargs)
    return wrapper


def require_role(allowed_roles: list[str]):
    """
    Decorator to require specific roles for an endpoint.
    
    Args:
        allowed_roles: List of roles that are allowed to access the endpoint
    
    Usage:
        from common.auth_middleware import get_user_context, require_role
        
        @app.get("/admin/settings")
        @require_role(["admin", "superadmin"])
        async def get_admin_settings(user: Optional[dict] = Depends(get_user_context)):
            # Only users with admin or superadmin role can access
            return {"settings": "admin data"}
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, user: Optional[dict] = None, **kwargs):
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User authentication required"
                )
            
            if user.get("role") not in allowed_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Requires one of roles: {', '.join(allowed_roles)}"
                )
            
            return await func(*args, user=user, **kwargs)
        
        return wrapper
    return decorator
```

### 3.2 Copy Common Files to Services

Each service (backend, curator, retriever) should copy the `common/` folder into their Docker image.

#### Update Backend Dockerfile

Add this before installing dependencies:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Copy common utilities
COPY ../common ./common

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# ... rest of Dockerfile
```

**Repeat for curator and retriever services.**

**Note**: By copying the entire `common/` folder, you can easily add more shared utilities in the future without changing Dockerfiles.

### 3.3 Use Auth Middleware in Backend Routes

**File: `backend/src/api.py` (or wherever your routes are)**

```python
from fastapi import FastAPI, Depends
from typing import Optional
from common.auth_middleware import get_user_context, require_user_context, require_role

app = FastAPI()


@app.get("/health")
async def health():
    """Public health check - no auth required"""
    return {"status": "healthy"}


@app.get("/query")
@require_user_context
async def query_knowledge_graph(
    query: str,
    user: Optional[dict] = Depends(get_user_context)
):
    """
    User-initiated query endpoint.
    Requires authentication - user context must be present.
    """
    # user is guaranteed to be not None due to @require_user_context
    print(f"Query from user {user['email']} (role: {user['role']})")
    
    # Your existing query logic here
    return {"query": query, "results": []}


@app.get("/admin/settings")
@require_role(["admin", "superadmin"])
async def get_admin_settings(user: Optional[dict] = Depends(get_user_context)):
    """
    Admin-only endpoint.
    Only users with admin or superadmin role can access.
    """
    return {"settings": "admin data"}


@app.post("/document")
@require_user_context
async def create_document(
    document_data: dict,
    user: Optional[dict] = Depends(get_user_context)
):
    """
    Create document endpoint - requires user authentication.
    User can only create documents for themselves unless they're an admin.
    """
    if user["role"] not in ["admin", "superadmin"]:
        document_data["owner_id"] = user["user_id"]
    
    # Your document creation logic
    return {"document": document_data}


@app.post("/process-documents")
async def process_documents(
    document_ids: list[str],
    user: Optional[dict] = Depends(get_user_context)
):
    """
    Process documents endpoint.
    Can be called by users OR by internal services (scheduled jobs, events).
    
    If user context exists, log who initiated it.
    If no user context, it's a system/service-initiated process.
    """
    if user:
        print(f"Processing initiated by user: {user['email']}")
    else:
        print(f"Processing initiated by system/service")
    
    # Your processing logic here
    return {"status": "processing", "document_ids": document_ids}
```

### 3.4 Service-to-Service Communication

Internal services can call each other directly for non-user operations (scheduled jobs, event processing, etc.).

**File: `retriever/utils/service_client.py`**

```python
import httpx
from typing import Optional


async def call_curator_service(
    path: str,
    method: str = "POST",
    data: dict = None,
    user_context: Optional[dict] = None
) -> dict:
    """
    Call curator service from retriever.
    
    Args:
        path: API path on curator service
        method: HTTP method
        data: Request payload
        user_context: Optional user context if this is a user-initiated request
    """
    headers = {}
    
    # Pass user context if available (for audit logging)
    if user_context:
        headers["X-User-Id"] = user_context.get("user_id")
        headers["X-User-Email"] = user_context.get("email")
        headers["X-User-Role"] = user_context.get("role")
    
    async with httpx.AsyncClient() as client:
        response = await client.request(
            method=method,
            url=f"http://curator:8002{path}",
            headers=headers,
            json=data,
            timeout=30.0
        )
        response.raise_for_status()
        return response.json()


# Example: Scheduled job (no user context)
async def scheduled_document_analysis():
    """Run by scheduler - no user involved"""
    documents = await fetch_pending_documents()
    
    result = await call_curator_service(
        path="/analyze-batch",
        method="POST",
        data={"documents": documents}
        # No user_context - this is a system operation
    )
    return result


# Example: User-initiated action (pass user context)
async def user_requested_analysis(document_id: str, user: dict):
    """User clicked 'analyze' button"""
    result = await call_curator_service(
        path="/analyze",
        method="POST",
        data={"document_id": document_id},
        user_context=user  # Pass through for audit logging
    )
    return result
```

### 3.5 Apply to Curator and Retriever Services

Repeat the same process for curator and retriever:

1. **Update Dockerfile** to copy `common/` folder
2. **Import and use** in your route handlers:

```python
from fastapi import FastAPI, Depends
from typing import Optional
from common.auth_middleware import get_user_context, require_user_context, require_role

app = FastAPI()

# Apply decorators as needed for your endpoints
@app.get("/curator/analyze")
@require_user_context
async def analyze_content(user: Optional[dict] = Depends(get_user_context)):
    # User context guaranteed to be present
    return {"analyzed": True, "user": user["email"]}
```

### 3.6 Understanding the Security Model

**What protects internal services:**
- ✅ Docker network isolation (services on internal network only)
- ✅ No public port exposure (only auth + frontend have public ports)
- ✅ Auth service as gateway (all user requests go through authentication)

**What this approach allows:**
- ✅ User-initiated requests have full context (user_id, email, role)
- ✅ Service-to-service calls work without auth overhead
- ✅ Scheduled jobs and event handlers can operate independently
- ✅ Audit logging can track user vs system operations

**Security note:** If an internal service is compromised, the attacker can call other internal services. This is inherent to the architecture and acceptable because:
- All services run at the same security level
- All services are in your control
- The real security boundary is network isolation + public exposure
- Defense-in-depth is provided by application-level authorization (role checks)

---

## Phase 4: Frontend Integration

### Objective
Integrate authentication with your frontend application. 

**Important**: This phase provides a **React example**, but the auth service works with **any frontend framework** (Vue, Angular, Svelte, vanilla JS, mobile apps, etc.). The core requirements for any frontend are:

1. **Redirect to Cognito** for login: `window.location.href = 'http://localhost:8000/api/auth/login'`
2. **Receive httpOnly cookies** automatically after OAuth callback
3. **Include cookies in API requests** via `credentials: 'include'` or equivalent
4. **Handle 401 responses** by redirecting to login

**Skip this phase** if you're not using React, or use it as a reference to adapt to your framework.

---

### 4.1 Frontend Requirements (Framework Agnostic)

Any frontend must:

**For Login:**
```javascript
// Redirect to auth service login endpoint
window.location.href = 'http://localhost:8000/api/auth/login';
// User will go through Cognito, then be redirected back with cookies set
```

**For API Calls:**
```javascript
// Ensure cookies are sent with requests
fetch('http://localhost:8000/api/backend/query', {
  credentials: 'include',  // CRITICAL: Include httpOnly cookies
  method: 'GET',
})
```

**For Logout:**
```javascript
// Redirect to logout endpoint (clears cookies)
window.location.href = 'http://localhost:8000/api/auth/logout';
```

**For Getting Current User:**
```javascript
// Check authentication status
fetch('http://localhost:8000/api/auth/me', {
  credentials: 'include',
})
  .then(res => res.json())
  .then(user => console.log(user)) // { user_id, email, role }
  .catch(() => console.log('Not authenticated'));
```

---

### 4.2 React Implementation Example

The following sections show how to implement auth in React. **Adapt these patterns to your framework.**

#### 4.2.1 Environment Variables

**Important Architecture Note:**

In production, the frontend and API are served from the **same domain** via nginx reverse proxy:
- `https://yourdomain.com/` → Frontend (React app)
- `https://yourdomain.com/api/*` → Auth Service (gateway to all APIs)

This means the frontend can use **relative URLs** - no environment variables needed!

**Development Setup:**

The frontend's `package.json` already has:
```json
"proxy": "http://localhost:8000"
```

This proxies all `/api/*` requests to the auth service during development.

**Frontend Configuration:**

Use relative paths in your API client - works in both dev and production:

```javascript
// frontend/src/services/api.js (or create new client.js)
import axios from 'axios';

const apiClient = axios.create({
  baseURL: '/api',  // Relative URL - no environment variable needed!
  withCredentials: true, // CRITICAL: Include httpOnly cookies
  headers: {
    'Content-Type': 'application/json',
  },
});

// Login/Logout/Auth check use the same base
// Login: window.location.href = '/api/auth/login';
// Logout: window.location.href = '/api/auth/logout';
// Auth check: apiClient.get('/auth/me');
```

**How it works:**

**Development:**
- User accesses: `http://localhost:3000/`
- API calls to `/api/*` → proxied by React dev server → `http://localhost:8000/api/*`

**Production:**
- User accesses: `https://yourdomain.com/`
- API calls to `/api/*` → routed by nginx → `http://auth:8000/api/*` (internal Docker network)

**Port Exposure:**

**Development:** Expose ports for convenience
```yaml
# docker-compose.yml
frontend:
  ports:
    - "3000:3000"  # Access frontend directly
auth:
  ports:
    - "8000:8000"  # Access auth service directly
```

**Production:** Only nginx exposed
```yaml
# docker-compose.prod.yml
nginx:
  ports:
    - "443:443"  # ONLY nginx exposed to internet

frontend:
  # NO ports section - internal only
  expose:
    - "3000"  # Documents internal port for nginx

auth:
  # NO ports section - internal only
  expose:
    - "8000"  # Documents internal port for nginx
```

**Why this approach?**
- ✅ No CORS issues (same-origin requests)
- ✅ No environment variables needed
- ✅ Works identically in dev and production
- ✅ Secure by default (no exposed internal ports in production)
- ✅ SSL/TLS handled by nginx only

#### 4.2.2 Create Auth Context

**File: `frontend/src/contexts/AuthContext.js`**

```javascript
import React, { createContext, useContext, useState, useEffect } from 'react';
import apiClient from '../api/client';

const AuthContext = createContext(undefined);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    checkAuthStatus();
  }, []);

  const checkAuthStatus = async () => {
    try {
      const response = await apiClient.get('/auth/me');
      setUser(response.data);
    } catch (error) {
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  const login = () => {
    // Redirect to auth service login endpoint
    window.location.href = '/api/auth/login';
  };

  const logout = async () => {
    try {
      // Redirect to logout endpoint to clear cookies
      window.location.href = '/api/auth/logout';
    } catch (error) {
      console.error('Logout failed:', error);
    }
  };

  const isAuthenticated = !!user;

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, isAuthenticated }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
```

#### 4.2.3 Create Protected Route Component

**File: `frontend/src/components/ProtectedRoute.js`**

```javascript
import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

export const ProtectedRoute = ({ children, requiredRole }) => {
  const { user, loading, isAuthenticated } = useAuth();

  if (loading) {
    return <div>Loading...</div>;
  }

  if (!isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  // Check role if required
  if (requiredRole && user && !requiredRole.includes(user.role)) {
    return <div>Access Denied: Insufficient permissions</div>;
  }

  return <>{children}</>;
};
```

#### 4.2.4 Configure Axios for Credentials

**File: `frontend/src/api/client.js`**

```javascript
import axios from 'axios';

const apiClient = axios.create({
  baseURL: '/api',  // Relative URL - works in dev and production
  withCredentials: true, // CRITICAL: Include httpOnly cookies in requests
  headers: {
    'Content-Type': 'application/json',
  },
});

// Optional: Add response interceptor for handling 401s
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Token expired or invalid - redirect to login
      window.location.href = '/api/auth/login';
    }
    return Promise.reject(error);
  }
);

export default apiClient;
```

**Update existing `frontend/src/services/api.js`:**

```javascript
import apiClient from '../api/client';

// Update existing API client usage
// Remove the old API_BASE_URL configuration
// Use the new apiClient instead of the old api instance

// Health check
export const testBackendConnection = async () => {
  try {
    const response = await apiClient.get('/backend/health');
    return response.data.status === 'ok';
  } catch (error) {
    console.error('Backend connection failed:', error);
    return false;
  }
};

// User Management - Update paths to include service prefix
export const createUser = async (email, displayName) => {
  const response = await apiClient.post('/backend/users', {
    email,
    display_name: displayName,
  });
  return response.data;
};

export const getAllUsers = async () => {
  const response = await apiClient.get('/backend/users');
  return response.data;
};

// ... rest of your API functions with /backend prefix
```

#### 4.2.5 Create Login Page

**File: `frontend/src/pages/LoginPage.js`**

```javascript
import React from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Navigate } from 'react-router-dom';

export const LoginPage = () => {
  const { login, isAuthenticated } = useAuth();

  // If already authenticated, redirect to home
  if (isAuthenticated) {
    return <Navigate to="/home" replace />;
  }

  return (
    <div style={{ textAlign: 'center', marginTop: '100px' }}>
      <h1>Welcome to Aurora</h1>
      <p>Please log in to continue</p>
      <button 
        onClick={login}
        style={{
          padding: '10px 20px',
          fontSize: '16px',
          cursor: 'pointer',
          backgroundColor: '#007bff',
          color: 'white',
          border: 'none',
          borderRadius: '5px',
        }}
      >
        Login with Cognito
      </button>
    </div>
  );
};
```

#### 4.2.6 Update App.js

**File: `frontend/src/App.js`**

```javascript
import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import { ProtectedRoute } from './components/ProtectedRoute';
import { LoginPage } from './pages/LoginPage';
import Header from './components/Header';
import Sidebar from './components/Sidebar';
import Chatbot from './pages/Chatbot';
import UserProfile from './pages/UserProfile';
import AdminUsers from './pages/AdminUsers';
import AdminKnowledgeGraph from './pages/AdminKnowledgeGraph';
import AdminMonitoring from './pages/AdminMonitoring';
import AdminSystemConfig from './pages/AdminSystemConfig';
import News from './pages/News';

function App() {
  return (
    <AuthProvider>
      <Router>
        <Routes>
          {/* Public routes */}
          <Route path="/" element={<LoginPage />} />
          
          {/* Protected routes - any authenticated user */}
          <Route 
            path="/chatbot" 
            element={
              <ProtectedRoute>
                <div className="app-container">
                  <Header />
                  <Sidebar />
                  <Chatbot />
                </div>
              </ProtectedRoute>
            } 
          />
          
          <Route 
            path="/profile" 
            element={
              <ProtectedRoute>
                <div className="app-container">
                  <Header />
                  <Sidebar />
                  <UserProfile />
                </div>
              </ProtectedRoute>
            } 
          />
          
          <Route 
            path="/news" 
            element={
              <ProtectedRoute>
                <div className="app-container">
                  <Header />
                  <Sidebar />
                  <News />
                </div>
              </ProtectedRoute>
            } 
          />
          
          {/* Admin-only routes */}
          <Route 
            path="/admin/users" 
            element={
              <ProtectedRoute requiredRole={['admin', 'superadmin']}>
                <div className="app-container">
                  <Header />
                  <Sidebar />
                  <AdminUsers />
                </div>
              </ProtectedRoute>
            } 
          />
          
          <Route 
            path="/admin/knowledge-graph" 
            element={
              <ProtectedRoute requiredRole={['admin', 'superadmin']}>
                <div className="app-container">
                  <Header />
                  <Sidebar />
                  <AdminKnowledgeGraph />
                </div>
              </ProtectedRoute>
            } 
          />
          
          <Route 
            path="/admin/monitoring" 
            element={
              <ProtectedRoute requiredRole={['admin', 'superadmin']}>
                <div className="app-container">
                  <Header />
                  <Sidebar />
                  <AdminMonitoring />
                </div>
              </ProtectedRoute>
            } 
          />
          
          <Route 
            path="/admin/system-config" 
            element={
              <ProtectedRoute requiredRole={['admin', 'superadmin']}>
                <div className="app-container">
                  <Header />
                  <Sidebar />
                  <AdminSystemConfig />
                </div>
              </ProtectedRoute>
            } 
          />
        </Routes>
      </Router>
    </AuthProvider>
  );
}

export default App;
```

**Key Changes from Original:**
- Removed `localStorage` user management (replaced with AuthContext)
- Removed `backendStatus` check from App component (can be moved to a component if needed)
- All routes now wrapped in `<ProtectedRoute>` except login
- Admin routes have `requiredRole={['admin', 'superadmin']}`
- Auth state managed centrally via `AuthProvider`

#### 4.2.7 Update API Calls to Use Auth Client

**Example: Making authenticated API calls**

```javascript
import apiClient from '../api/client';

// In any component
const fetchData = async () => {
  try {
    // All calls automatically include credentials (cookies)
    const response = await apiClient.get('/backend/query?query=test');
    console.log(response.data);
  } catch (error) {
    console.error('API call failed:', error);
    // 401 errors automatically redirect to login (via interceptor)
  }
};

// POST example
const createDocument = async (documentData) => {
  try {
    const response = await apiClient.post('/backend/documents', documentData);
    return response.data;
  } catch (error) {
    console.error('Failed to create document:', error);
    throw error;
  }
};
```

**Update existing `frontend/src/services/api.js`:**

Replace the old API client with the new one that includes credentials:

```javascript
import apiClient from '../api/client';

// Health check - update to use /backend prefix
export const testBackendConnection = async () => {
  try {
    const response = await apiClient.get('/backend/health');
    return response.data.status === 'ok';
  } catch (error) {
    console.error('Backend connection failed:', error);
    return false;
  }
};

// User Management - add /backend prefix to all paths
export const createUser = async (email, displayName) => {
  const response = await apiClient.post('/backend/users', {
    email,
    display_name: displayName,
  });
  return response.data;
};

export const getAllUsers = async () => {
  const response = await apiClient.get('/backend/users');
  return response.data;
};

export const getUserById = async (userId) => {
  const response = await apiClient.get(`/backend/users/${userId}`);
  return response.data;
};

export const getUserByEmail = async (email) => {
  const response = await apiClient.get(`/backend/users/email/${email}`);
  return response.data;
};

export const deleteUser = async (userId) => {
  const response = await apiClient.delete(`/backend/users/${userId}`);
  return response.data;
};

// User Preferences
export const getUserPreferences = async (userId) => {
  const response = await apiClient.get(`/backend/users/${userId}/preferences`);
  return response.data;
};

export const updateUserPreferences = async (userId, preferences) => {
  const response = await apiClient.put(`/backend/users/${userId}/preferences`, preferences);
  return response.data;
};

// Knowledge Graph
export const getTopics = async (limit = 1000) => {
  const response = await apiClient.get(`/backend/graph/topics?limit=${limit}`);
  return response.data;
};

export const getOrganisations = async (limit = 1000) => {
  const response = await apiClient.get(`/backend/graph/organisations?limit=${limit}`);
  return response.data;
};

export const getPeople = async (limit = 1000) => {
  const response = await apiClient.get(`/backend/graph/people?limit=${limit}`);
  return response.data;
};

export const getGraphStatistics = async () => {
  const response = await apiClient.get('/backend/graph/statistics');
  return response.data;
};

// Query
export const sendQuery = async (userId, question) => {
  const response = await apiClient.post('/backend/query', {
    user_id: userId,
    question,
  });
  return response.data;
};

export default apiClient;
```

**Important Path Changes:**
- All API paths now need `/backend` prefix (or `/curator`, `/retriever` as appropriate)
- This routes through the auth service which validates tokens and proxies to internal services
- Old: `/users` → New: `/backend/users`
- Old: `/query` → New: `/backend/query`
- Old: `/graph/topics` → New: `/backend/graph/topics`

---

## Phase 5: Docker Compose Integration

### Objective
Update Docker Compose to include auth service and configure networks properly.

### 5.1 Update `docker-compose.yml`

**Development Configuration** (ports exposed for local testing):

```yaml
version: '3.8'

services:
  # Auth Service (PUBLIC in dev - exposed for testing)
  auth:
    build: ./auth
    ports:
      - "8000:8000"  # Exposed in dev for direct access
    environment:
      # AWS Cognito
      - AWS_REGION=${AWS_REGION}
      - COGNITO_USER_POOL_ID=${COGNITO_USER_POOL_ID}
      - COGNITO_APP_CLIENT_ID=${COGNITO_APP_CLIENT_ID}
      - COGNITO_APP_CLIENT_SECRET=${COGNITO_APP_CLIENT_SECRET}
      - COGNITO_DOMAIN=${COGNITO_DOMAIN}
      - COGNITO_JWKS_URL=${COGNITO_JWKS_URL}
      - COGNITO_TOKEN_ENDPOINT=${COGNITO_TOKEN_ENDPOINT}
      # Service URLs (internal Docker network - use container names and internal ports)
      - BACKEND_SERVICE_URL=http://backend:8000
      - CURATOR_SERVICE_URL=http://curator:8000
      - RETRIEVER_SERVICE_URL=http://retriever:8000
      # Application Configuration
      - APPLICATION_URL=${APPLICATION_URL:-http://localhost:3000}
      - COOKIE_DOMAIN=${COOKIE_DOMAIN:-localhost}
      - COOKIE_SECURE=${COOKIE_SECURE:-false}
    networks:
      - internal
    depends_on:
      - backend
      - curator
      - retriever

  # Frontend (PUBLIC in dev - exposed for testing)
  frontend:
    build: ./frontend
    ports:
      - "3000:3000"  # Exposed in dev for direct access
    networks:
      - internal

  # Backend Service (INTERNAL ONLY - no ports exposed)
  backend:
    build: ./backend
    expose:
      - "8000"  # Internal port, not exposed to host
    environment:
      - NEO4J_URI=${NEO4J_URI}
      - NEO4J_USER=${NEO4J_USER}
      - NEO4J_PASSWORD=${NEO4J_PASSWORD}
      # Add other backend env vars as needed
    networks:
      - internal
    depends_on:
      - neo4j

  # Curator Service (INTERNAL ONLY)
  curator:
    build: ./curator
    expose:
      - "8000"  # Internal port
    networks:
      - internal

  # Retriever Service (INTERNAL ONLY)
  retriever:
    build: ./retriever
    expose:
      - "8000"  # Internal port
    networks:
      - internal

  # Digester Service (INTERNAL ONLY)
  digester:
    build: ./digester
    networks:
      - internal
    depends_on:
      - rabbitmq
      - neo4j

  # Neo4j Database (INTERNAL ONLY)
  neo4j:
    image: neo4j:5.13.0
    ports:
      - "7474:7474"  # Exposed in dev for Neo4j Browser
      - "7687:7687"  # Exposed in dev for Bolt protocol
    environment:
      - NEO4J_AUTH=${NEO4J_USER}/${NEO4J_PASSWORD}
    networks:
      - internal
    volumes:
      - neo4j_data:/data

  # RabbitMQ (INTERNAL ONLY)
  rabbitmq:
    image: rabbitmq:3.12-management
    ports:
      - "15672:15672"  # Exposed in dev for management UI
      - "5672:5672"    # Exposed in dev for AMQP
    networks:
      - internal
    volumes:
      - rabbitmq_data:/var/lib/rabbitmq

networks:
  internal:
    driver: bridge

volumes:
  neo4j_data:
  rabbitmq_data:
```

**Production Configuration** (`docker-compose.prod.yml` override):

```yaml
version: '3.8'

services:
  # nginx handles SSL/TLS termination and routing
  nginx:
    image: nginx:alpine
    ports:
      - "443:443"  # ONLY nginx exposed in production
      - "80:80"    # For HTTP to HTTPS redirect
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
    networks:
      - internal
    depends_on:
      - auth
      - frontend

  # Auth service - no ports exposed (internal only)
  auth:
    ports: []  # Override to remove port mapping
    expose:
      - "8000"

  # Frontend - no ports exposed (internal only)
  frontend:
    ports: []  # Override to remove port mapping
    expose:
      - "3000"

  # Neo4j - no ports exposed in production
  neo4j:
    ports: []
    expose:
      - "7687"
      - "7474"

  # RabbitMQ - no ports exposed in production
  rabbitmq:
    ports: []
    expose:
      - "5672"
      - "15672"

networks:
  internal:
    driver: bridge
    internal: true  # Prevent external access to internal network
```

**Deploy in production:**
```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 5.2 Update Root `.env` File

**Note:** The `.env.example` already has most of these variables. This section clarifies their purpose.

**Key Environment Variables:**

```env
# =============================================================================
# AWS Cognito Configuration
# =============================================================================
# AWS Region where your Cognito User Pool is located
AWS_REGION=us-east-1

# Cognito User Pool ID (from AWS Console)
COGNITO_USER_POOL_ID=us-east-1_xxxxx

# App Client credentials (from AWS Console)
COGNITO_APP_CLIENT_ID=7xxxxxxxxxxxxx
COGNITO_APP_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx

# Cognito domain for OAuth (from AWS Console)
COGNITO_DOMAIN=octo-aurora-dev.auth.us-east-1.amazoncognito.com

# Auto-generated URLs based on above values
COGNITO_JWKS_URL=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_xxxxx/.well-known/jwks.json
COGNITO_TOKEN_ENDPOINT=https://octo-aurora-dev.auth.us-east-1.amazoncognito.com/oauth2/token

# =============================================================================
# Application Configuration
# =============================================================================
# Where users access the application (frontend + API are both served from here)
# Development: http://localhost:3000 (React dev server proxies /api to auth:8000)
# Production: https://yourdomain.com (nginx routes / to frontend, /api to auth)
APPLICATION_URL=http://localhost:3000

# Cookie settings
# Development: localhost, false
# Production: yourdomain.com, true
COOKIE_DOMAIN=localhost
COOKIE_SECURE=false

# =============================================================================
# Service URLs (Internal Docker Network)
# =============================================================================
# These are used by the auth service to proxy requests to internal services
# NOTE: Use internal container names and ports, not host-mapped ports
BACKEND_SERVICE_URL=http://backend:8000
CURATOR_SERVICE_URL=http://curator:8000
RETRIEVER_SERVICE_URL=http://retriever:8000

# =============================================================================
# Port Exposure Notes
# =============================================================================
# DEVELOPMENT:
#   - Auth exposed on localhost:8000 (for testing)
#   - Frontend exposed on localhost:3000 (for dev server)
#   - Backend/Curator/Retriever: INTERNAL ONLY (no host ports)
#
# PRODUCTION:
#   - Only nginx exposed on port 443 (HTTPS)
#   - All services internal only
#   - nginx routes:
#       / → frontend:3000
#       /api/* → auth:8000
```

**Note**: Keep your existing environment variables. Just add the new auth-related ones above.

### 5.3 Start Everything

```bash
# Build and start all services
docker-compose up --build

# Or in detached mode
docker-compose up -d --build

# View logs
docker-compose logs -f auth
docker-compose logs -f backend
```

---

## Phase 6: Testing

### Objective
Verify the authentication system works end-to-end.

### 6.1 Test Authentication Flow

1. **Open frontend**: `http://localhost:3000`
2. **Click Login**: Should redirect to Cognito Hosted UI
3. **Enter credentials**: Use one of the test users created in Phase 1
4. **Complete login**: Should redirect back to `http://localhost:3000/home`
5. **Verify cookies**: Open DevTools > Application > Cookies
   - Should see `access_token` and `refresh_token` with HttpOnly flag

### 6.2 Test API Calls

**Using the frontend:**
```javascript
// In browser console
fetch('http://localhost:8000/api/auth/me', { credentials: 'include' })
  .then(r => r.json())
  .then(console.log)
// Should return user info
```

**Using curl:**
```bash
# Get session cookies first (login via browser)
# Then test with cookies

curl -b cookies.txt http://localhost:8000/api/auth/me
# Should return user info
```

### 6.3 Test Authorization

**Test role-based access:**
```bash
# Login as regular user, then try to access admin endpoint
curl -b cookies.txt http://localhost:8000/api/backend/admin/settings
# Should return 403 Forbidden

# Login as admin user, then try again
# Should return 200 OK with settings
```

### 6.4 Test Token Refresh

1. Wait for access token to expire (1 hour) OR manually test:
2. Make API call with expired token but valid refresh token
3. Should automatically refresh and work seamlessly

### 6.5 Test Logout

1. Click logout button in frontend
2. Should clear cookies and redirect to Cognito logout
3. Try to access protected route
4. Should be redirected to login

### 6.6 Test Service-to-Service Communication

**In backend code, call curator:**
```python
import httpx

async def call_curator_service(user_context=None):
    headers = {}
    
    # Optionally pass user context for audit logging
    if user_context:
        headers["X-User-Id"] = user_context.get("user_id")
        headers["X-User-Email"] = user_context.get("email")
        headers["X-User-Role"] = user_context.get("role")
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "http://curator:8002/some-endpoint",
            headers=headers
        )
        return response.json()
```

### 6.7 Automated Tests (Optional but Recommended)

**File: `auth/tests/test_auth.py`**

```python
import pytest
from fastapi.testclient import TestClient
from auth import app

client = TestClient(app)


def test_health_check():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "auth"}


def test_login_redirect():
    response = client.get("/api/auth/login", follow_redirects=False)
    assert response.status_code == 307
    assert "cognito" in response.headers["location"]


def test_auth_me_without_token():
    response = client.get("/api/auth/me")
    assert response.status_code == 401
```

Run tests:
```bash
cd auth
pytest tests/
```

---

## Phase 7: Deployment Preparation

### Objective
Prepare the application for production deployment.

### 7.1 Production Environment Variables

**Create `.env.production`:**

```env
# AWS Cognito (Production)
AWS_REGION=us-east-1
COGNITO_USER_POOL_ID=us-east-1_PROD_xxxxx
COGNITO_APP_CLIENT_ID=prod_client_id
COGNITO_APP_CLIENT_SECRET=prod_client_secret
COGNITO_DOMAIN=your-app-prod.auth.us-east-1.amazoncognito.com
COGNITO_JWKS_URL=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_PROD_xxxxx/.well-known/jwks.json
COGNITO_TOKEN_ENDPOINT=https://your-app-prod.auth.us-east-1.amazoncognito.com/oauth2/token

# Frontend (Production domain)
FRONTEND_URL=https://yourdomain.com
COOKIE_DOMAIN=yourdomain.com
COOKIE_SECURE=true

# Neo4j
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=strong-production-password
```

### 7.2 SSL/TLS Configuration

**Add nginx as SSL termination (optional but recommended):**

Create `nginx/nginx.conf`:
```nginx
events {
    worker_connections 1024;
}

http {
    upstream auth_backend {
        server auth:8000;
    }

    upstream frontend {
        server frontend:80;
    }

    server {
        listen 443 ssl http2;
        server_name yourdomain.com;

        ssl_certificate /etc/nginx/ssl/cert.pem;
        ssl_certificate_key /etc/nginx/ssl/key.pem;

        # Auth service
        location /api/ {
            proxy_pass http://auth_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Frontend
        location / {
            proxy_pass http://frontend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }
    }

    # Redirect HTTP to HTTPS
    server {
        listen 80;
        server_name yourdomain.com;
        return 301 https://$server_name$request_uri;
    }
}
```

Update `docker-compose.yml`:
```yaml
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
    networks:
      - public
    depends_on:
      - auth
      - frontend
```

### 7.3 Update Cognito for Production

1. Go to AWS Cognito console
2. Update App Client callback URLs:
   - Add: `https://yourdomain.com/api/auth/callback`
   - Remove development URLs
3. Update sign-out URLs:
   - Add: `https://yourdomain.com`

### 7.4 Security Checklist

- [ ] Set `COOKIE_SECURE=true`
- [ ] Enable internal Docker network isolation (`internal: true`)
- [ ] Configure SSL/TLS certificates
- [ ] Update Cognito callback URLs to production domain
- [ ] Enable MFA in Cognito (optional but recommended)
- [ ] Set up AWS Secrets Manager for sensitive values (especially Cognito client secret)
- [ ] Configure logging and monitoring
- [ ] Set up rate limiting (use nginx or AWS WAF)
- [ ] Review and test all authorization rules
- [ ] Ensure internal services have NO publicly exposed ports

### 7.5 Monitoring and Logging

**Logging is already configured in the auth service** via `utils/logger.py` and integrated into `auth.py`. The auth service logs:

- **Authentication events**: Successful logins, failed logins, logouts
- **Request proxying**: User, role, method, path for all authenticated requests
- **Response status**: Status codes for debugging
- **Errors**: Token validation failures, service unavailability

**Log level is configurable via environment variable:**

Add to your `.env` file:
```env
LOG_LEVEL=INFO  # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
```

The auth service automatically reads `LOG_LEVEL` from the environment on startup.

**View logs:**
```bash
# In Docker Compose
docker-compose logs -f auth

# Filter for specific events
docker-compose logs auth | grep "Successful authentication"
docker-compose logs auth | grep "ERROR"
```

**Log aggregation for production:**
- Send logs to CloudWatch (AWS), Stackdriver (GCP), or Azure Monitor
- Use ELK Stack (Elasticsearch, Logstash, Kibana) for centralized logging
- Use Datadog, New Relic, or Splunk for comprehensive monitoring

### 7.6 Deploy

**Using Docker Compose:**
```bash
# Production deployment
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**Or using a cloud provider:**
- AWS ECS/EKS
- Google Cloud Run/GKE
- Azure Container Instances/AKS
- DigitalOcean App Platform

---

## Reference: Code Templates

### Template: Adding Authorization to New Endpoint

```python
from fastapi import Depends
from typing import Optional
from common.auth_middleware import get_user_context, require_user_context, require_role

# User-only endpoint - requires authentication
@app.get("/api/data")
@require_user_context
async def get_data(user: Optional[dict] = Depends(get_user_context)):
    # user is guaranteed to exist due to decorator
    return {"data": "accessible to all authenticated users"}

# Admin-only endpoint
@app.get("/api/admin/config")
@require_role(["admin", "superadmin"])
async def get_config(user: Optional[dict] = Depends(get_user_context)):
    return {"config": "only admins see this"}

# Resource ownership check
@app.get("/api/documents/{doc_id}")
@require_user_context
async def get_document(doc_id: str, user: Optional[dict] = Depends(get_user_context)):
    doc = get_document_from_db(doc_id)
    
    # Check if user owns the document or is admin
    if doc.owner_id != user["user_id"] and user["role"] not in ["admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return doc

# Endpoint callable by users OR services
@app.post("/api/process")
async def process_data(data: dict, user: Optional[dict] = Depends(get_user_context)):
    # User context may or may not be present
    if user:
        print(f"User-initiated: {user['email']}")
    else:
        print(f"Service-initiated")
    
    # Process the data regardless
    return {"status": "processed"}
```

### Template: Making Service-to-Service Calls

```python
import httpx
from typing import Optional

async def call_internal_service(
    service_url: str,
    path: str,
    method: str = "GET",
    data: dict = None,
    user_context: Optional[dict] = None
):
    """
    Generic function to call internal services.
    
    Args:
        service_url: URL of the internal service
        path: API path
        method: HTTP method
        data: Request payload
        user_context: Optional user context for audit logging
    """
    headers = {}
    
    # Pass through user context if available (for audit logging)
    if user_context:
        headers["X-User-Id"] = user_context.get("user_id")
        headers["X-User-Email"] = user_context.get("email")
        headers["X-User-Role"] = user_context.get("role")
    
    async with httpx.AsyncClient() as client:
        response = await client.request(
            method=method,
            url=f"{service_url}{path}",
            headers=headers,
            json=data,
            timeout=30.0
        )
        response.raise_for_status()
        return response.json()

# Usage - User-initiated request (pass context)
result = await call_internal_service(
    service_url="http://curator:8002",
    path="/analyze",
    method="POST",
    data={"text": "analyze this"},
    user_context={"user_id": "123", "email": "user@example.com", "role": "user"}
)

# Usage - System/service-initiated (no context)
result = await call_internal_service(
    service_url="http://curator:8002",
    path="/batch-process",
    method="POST",
    data={"documents": document_ids}
    # No user_context - system operation
)
```

### Template: Frontend API Call

```typescript
import apiClient from './api/client';

// GET request
const fetchData = async () => {
  try {
    const response = await apiClient.get('/backend/query?q=test');
    return response.data;
  } catch (error) {
    console.error('Failed to fetch data:', error);
    throw error;
  }
};

// POST request
const createDocument = async (documentData: any) => {
  try {
    const response = await apiClient.post('/backend/documents', documentData);
    return response.data;
  } catch (error) {
    console.error('Failed to create document:', error);
    throw error;
  }
};

// In a React component
const MyComponent = () => {
  const { user } = useAuth();
  
  useEffect(() => {
    if (user) {
      fetchData().then(data => {
        console.log('Data:', data);
      });
    }
  }, [user]);
  
  return <div>My Component</div>;
};
```

---

## Troubleshooting Guide

### Issue: "Token exchange failed" during login

**Cause**: Cognito authorization code exchange is failing.

**Solution**:
1. Verify `COGNITO_APP_CLIENT_SECRET` is correct
2. Check that callback URL in Cognito matches your auth service URL
3. Ensure `redirect_uri` in auth service matches Cognito configuration
4. Check auth service logs: `docker-compose logs auth`

### Issue: Cookies not being set

**Cause**: Domain/secure cookie settings incorrect.

**Solution**:
1. For localhost: Set `COOKIE_DOMAIN=localhost` and `COOKIE_SECURE=false`
2. For production: Set `COOKIE_DOMAIN=yourdomain.com` and `COOKIE_SECURE=true`
3. Verify browser allows cookies from localhost/your domain
4. Check that frontend and auth service are on same domain

### Issue: "401 Unauthorized" on all API calls

**Cause**: Token validation failing.

**Solution**:
1. Check that access token cookie is present: DevTools > Application > Cookies
2. Verify JWKS URL is correct and accessible
3. Check token hasn't expired (1 hour lifetime)
4. Verify `COGNITO_USER_POOL_ID` and `COGNITO_APP_CLIENT_ID` are correct
5. Try logout and login again

### Issue: Cannot access internal services directly

**Expected behavior**: This is correct! Internal services should only be accessible through auth service.

**Solution**: Always go through auth service:
- ❌ `http://localhost:8001/query` (direct to backend)
- ✅ `http://localhost:8000/api/backend/query` (through auth service)

### Issue: CORS errors in browser

**Cause**: Frontend and auth service on different origins.

**Solution**:
1. Ensure `FRONTEND_URL` in auth service matches your frontend origin
2. Check CORS middleware in `app/main.py` includes correct origin
3. For development, you may need to allow `http://localhost:3000`
4. Ensure `withCredentials: true` in frontend axios config

### Issue: Token refresh not working

**Cause**: Refresh token invalid or expired (7 days).

**Solution**:
1. Check that refresh token cookie exists
2. Verify refresh token hasn't expired (7 days)
3. Check auth service logs for refresh endpoint errors
4. User may need to login again if refresh token expired

### Issue: Admin endpoints accessible by regular users

**Cause**: Authorization not properly implemented.

**Solution**:
1. Ensure `@require_role` decorator is applied to admin endpoints
2. Verify `X-User-Role` header is being set correctly by auth service
3. Check that Cognito user has correct `custom:role` attribute
4. Add logging to see what role is being passed:
   ```python
   print(f"User role: {user['role']}")
   ```

### Issue: Docker network issues - services can't communicate

**Cause**: Services not on same Docker network.

**Solution**:
1. Check `docker-compose.yml` - ensure services share `internal` network
2. Use service names as hostnames: `http://backend:8001` not `http://localhost:8001`
3. Run `docker network ls` to see networks
4. Run `docker network inspect octo-rapid-aurora_internal` to see connected services

### Issue: "Service unavailable" errors

**Cause**: Internal service is down or auth service can't reach it.

**Solution**:
1. Check that target service is running: `docker-compose ps`
2. Check service logs: `docker-compose logs backend`
3. Verify service URLs in auth service config are correct
4. Test service directly from within Docker network:
   ```bash
   docker-compose exec auth curl http://backend:8001/health
   ```

### Getting Help

If you're still stuck:
1. Check all environment variables are set correctly
2. Review logs for all involved services
3. Verify AWS Cognito configuration matches your .env
4. Test each component in isolation (Cognito login, token validation, service calls)
5. Refer back to [AUTH_ARCHITECTURE.md](./AUTH_ARCHITECTURE.md) for design context

---

## Success Criteria

Your implementation is complete when:

- ✅ Users can login via Cognito Hosted UI
- ✅ JWT tokens are stored in httpOnly cookies
- ✅ Frontend can make authenticated API calls to backend services
- ✅ Token refresh works automatically and transparently
- ✅ User context is properly passed from auth service to internal services
- ✅ Role-based authorization works (user, admin, superadmin)
- ✅ Logout clears cookies and redirects properly
- ✅ Services cannot be accessed directly (only through auth service)
- ✅ All tests pass
- ✅ No secrets are committed to version control

## Next Steps After Implementation

1. Set up monitoring and alerting
2. Implement audit logging
3. Add rate limiting
4. Set up user sync to Neo4j graph
5. Implement request tracking for analytics
6. Add fine-grained permissions beyond roles
7. Set up automated testing in CI/CD
8. Plan for SSL/TLS certificate management

---

**Document Version**: 1.0  
**Last Updated**: December 2025  
**Maintainer**: Aurora Team
