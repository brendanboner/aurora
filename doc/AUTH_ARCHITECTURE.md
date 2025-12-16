# Authentication Architecture

## Overview
This document outlines the authentication architecture for the octo-rapid-aurora application using AWS Cognito and a dedicated auth service as a gateway.

**Key Architecture Decisions:**
- **Same-Origin Frontend:** Frontend and API served from same domain (no CORS)
- **Relative URLs:** Frontend uses `/api/*` paths (works in dev via proxy, prod via nginx)
- **No Frontend Env Vars:** No API base URLs needed - everything is relative
- **Port Exposure:**
  - Development: Auth (8000) and Frontend (3000) exposed for testing
  - Production: Only nginx (443) exposed - all services internal
- **httpOnly Cookies:** Tokens stored in secure httpOnly cookies (XSS protection)
- **Auth Gateway:** All API requests validated and proxied through auth service

## Architecture Diagram

### Production Architecture (with nginx)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           INTERNET / USERS                               │
│                         (User's Web Browser)                             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTPS (Port 443)
                                    │ ↕ Bidirectional
                                    ▼
                    ┌───────────────────────────────────────┐
                    │          nginx (Reverse Proxy)        │
                    │          Port: 443 (EXPOSED)          │
                    │                                       │
                    │  Routing Rules:                       │
                    │  • GET /           → frontend:3000    │
                    │  • GET /static/*   → frontend:3000    │
                    │  • ALL /api/*      → auth:8000        │
                    │                                       │
                    │  SSL/TLS Termination                  │
                    │  Single entry point                   │
                    └───────────────────────────────────────┘
                             │                    │
                             │                    │
                    ┌────────┘                    └────────┐
                    │                                      │
                    │ (1) Initial page load                │ (2) All API requests
                    ▼                                      ▼
    ┌───────────────────────────┐      ┌───────────────────────────────┐
    │   React Frontend          │      │   Auth Service (FastAPI)      │
    │   Port: 3000 (internal)   │      │   Port: 8000 (internal)       │
    │                           │      │                               │
    │  Serves:                  │      │  Responsibilities:            │
    │  • index.html             │      │  ✓ OAuth callback handler     │
    │  • React bundle.js        │      │  ✓ Token exchange w/ Cognito  │
    │  • CSS, images            │      │  ✓ Set httpOnly cookies       │
    │                           │      │  ✓ Validate JWT tokens        │
    │  Served ONCE on page load │      │  ✓ Verify Cognito signatures  │
    │  Then runs in browser     │      │  ✓ Extract user context       │
    │                           │      │  ✓ Token refresh              │
    │  Browser executes React:  │      │  ✓ Forward to services        │
    │  • Makes API calls to     │      │  ✓ Route based on path        │
    │    /api/* (relative URL)  │      │                               │
    │  • Browser sends these    │      │  Receives requests from:      │
    │    BACK to nginx (↑)      │      │  • User browser (via nginx)   │
    │  • nginx routes to auth   │      │                               │
    │  • Cookies auto-included  │      │  Does NOT:                    │
    │                           │      │  ✗ Check authorization        │
    └───────────────────────────┘      │    (handled by services)      │
                                       └───────────────────────────────┘
                                                       │
                                                       │ OAuth Flow
                                                       ▼
                                       ┌───────────────────────────┐
                                       │     AWS Cognito           │
                                       │  - User Pool              │
                                       │  - Hosted UI (Login)      │
                                       │  - JWT Token Issuance     │
                                       │  - User/Admin/SuperAdmin  │
                                       └───────────────────────────┘
                                                       │
                                                       │ Authenticated
                                                       │ Requests with
                                                       │ X-User-* headers
                                                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    INTERNAL NETWORK (Docker Network)                     │
│                         Service-to-Service Communication                 │
└─────────────────────────────────────────────────────────────────────────┘

        ┌───────────────┬───────────────┬───────────────┬─────────────┐
        │               │               │               │             │
        ▼               ▼               ▼               ▼             ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────┐ ┌──────────┐
│   Backend    │ │   Curator    │ │  Retriever   │ │ Digester │ │  Neo4j   │
│   (FastAPI)  │ │   (FastAPI)  │ │  (Python)    │ │ (Python) │ │   DB     │
│   Port: 8000 │ │   Port: 8000 │ │   Port: 8000 │ │          │ │          │
│ (internal)   │ │ (internal)   │ │ (internal)   │ │          │ │          │
│              │ │              │ │              │ │          │ │          │
│ • Extracts   │ │ • Extracts   │ │ • Extracts   │ │          │ │          │
│   user       │ │   user       │ │   user       │ │          │ │          │
│   headers    │ │   headers    │ │   headers    │ │          │ │          │
│   (if        │ │   (if        │ │   (if        │ │          │ │          │
│   present)   │ │   present)   │ │   present)   │ │          │ │          │
│              │ │              │ │              │ │          │ │          │
│ • Implements │ │ • Implements │ │ • Implements │ │          │ │          │
│   authz      │ │   authz      │ │   authz      │ │          │ │          │
│   logic      │ │   logic      │ │   logic      │ │          │ │          │
│              │ │              │ │              │ │          │ │          │
│ • Can call   │ │ • Can call   │ │ • Can call   │ │          │ │          │
│   other      │ │   other      │ │   other      │ │          │ │          │
│   services   │ │   services   │ │   services   │ │          │ │          │
│   directly   │ │   directly   │ │   directly   │ │          │ │          │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └─────┬────┘ └────┬─────┘
       │                │                │               │           │
       │                │                │               │           │
       └────────────────┴────────────────┴───────────────┴───────────┘
                                    │
                          Service-to-Service calls
                          (pass X-User-* headers for user-initiated requests)
                          (no user headers for system-initiated requests)
                                    │
                                    ▼
                        ┌───────────────────────┐
                        │   RabbitMQ            │
                        │   (Internal only)     │
                        │                       │
                        │  • Message queuing    │
                        │  • Async processing   │
                        └───────────────────────┘
```

**Traffic Flow Explanation:**

1. **Initial Page Load (nginx → frontend)**
   - User visits `https://yourdomain.com/`
   - nginx routes to frontend:3000
   - Frontend serves React app (HTML, JS, CSS)
   - React app loads in user's browser

2. **API Requests (browser → nginx → auth)**
   - React app (running in browser) makes API call: `fetch('/api/backend/query')`
   - Browser sends request back to `https://yourdomain.com/api/backend/query`
   - Request goes through nginx again
   - nginx routes `/api/*` to auth:8000
   - Auth validates JWT, proxies to backend
   - Response flows back: backend → auth → nginx → browser

3. **Key Point:** Frontend is served ONCE, then ALL communication is browser ↔ nginx ↔ auth ↔ services

### Development Architecture (direct access)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           LOCALHOST / DEVELOPER                          │
└─────────────────────────────────────────────────────────────────────────┘
                             │                    │
                             │                    │
                    ┌────────┘                    └────────┐
                    │                                      │
                    │ Port 3000                            │ Port 8000
                    ▼                                      ▼
    ┌───────────────────────────┐      ┌───────────────────────────────┐
    │   React Frontend          │      │   Auth Service (FastAPI)      │
    │   Port: 3000 (EXPOSED)    │      │   Port: 8000 (EXPOSED)        │
    │                           │      │                               │
    │  React dev server         │      │  Direct access for testing    │
    │  Proxies /api/* to        │      │  OAuth flow                   │
    │  localhost:8000           │      │  Token management             │
    │                           │      │                               │
    │  package.json:            │      │  Routes to AWS Cognito        │
    │  "proxy":                 │      │  Routes to internal services  │
    │   "http://localhost:8000" │      │                               │
    └───────────────────────────┘      └───────────────────────────────┘
                                                       │
                                                       ▼
                                       ┌───────────────────────────┐
                                       │     AWS Cognito           │
                                       │  OAuth & JWT tokens       │
                                       └───────────────────────────┘
                                                       │
                                                       ▼
                               Backend, Curator, Retriever
                               (all internal - no exposed ports)
```

**Key Differences:**
- **Production**: nginx (443) → routes to frontend (3000) and auth (8000) internally
- **Development**: Direct access to frontend (3000) and auth (8000) for testing
- **Both**: Internal services never exposed, auth service validates all API requests

## Authentication Flow

### 1. User Login Flow (OAuth 2.0 Authorization Code Flow)
```
User clicks "Login" on Frontend
    │
    │ 1. Redirect to Auth Service login endpoint
    │    Frontend: window.location.href = '/api/auth/login'
    │    (Relative URL works in both dev and production)
    │
    │ 2. Auth Service redirects to Cognito Hosted UI
    │    URL: https://your-app.auth.region.amazoncognito.com/login
    │    Params: client_id, redirect_uri, response_type=code, scope
    │
    ▼
Cognito Hosted UI
    │
    │ 3. User enters credentials
    │ 4. Cognito authenticates user
    │
    │ 5. Redirect to Auth Service with authorization code
    │    URL: https://yourdomain.com/api/auth/callback?code=AUTH_CODE
    │    (In dev: http://localhost:8000/api/auth/callback)
    │
    ▼
Auth Service (/api/auth/callback)
    │
    ├─ 6a. Receive authorization code
    ├─ 6b. Exchange code for tokens with Cognito
    │      POST to Cognito token endpoint
    │      Body: code, client_id, client_secret, grant_type=authorization_code
    │
    ├─ 6c. Receive tokens from Cognito
    │      - Access Token (JWT)
    │      - ID Token (JWT with user claims)
    │      - Refresh Token
    │
    ├─ 6d. Set httpOnly cookies
    │      Set-Cookie: access_token=<jwt>; HttpOnly; Secure; SameSite=Strict
    │      Set-Cookie: refresh_token=<jwt>; HttpOnly; Secure; SameSite=Strict
    │
    │ 7. Redirect user to Frontend homepage
    │    Location: / (relative redirect)
    │    (Dev: http://localhost:3000, Prod: https://yourdomain.com)
    │
    ▼
Frontend (user now has httpOnly cookies)
    │
    ▼
User is authenticated and can make API requests
```

### 2. Authenticated API Request Flow (Production with nginx)
```
User Browser (React app already loaded)
    │
    │ 1. Makes API call: fetch('/api/backend/query')
    │    (Relative URL - browser sends to same domain)
    │    Cookies automatically included by browser
    │
    ▼
nginx (Port 443)
    │
    │ 2. Receives request at https://yourdomain.com/api/backend/query
    │    Routes /api/* to auth:8000 (internal)
    │
    ▼
Auth Service (internal port 8000)
    │
    ├─ 3a. Extract JWT from cookie
    ├─ 3b. Validate JWT signature with Cognito public keys (JWKS)
    ├─ 3c. Verify token expiration
    ├─ 3d. Extract user_id, email, role from token claims
    │
    │ 4. Forward request to backend:8000 with added headers:
    │    X-User-Id: abc-123
    │    X-User-Email: user@example.com
    │    X-User-Role: admin
    │
    ▼
Backend Service (internal port 8000)
    │
    ├─ 5a. Extract user context from headers (X-User-Id, X-User-Role, etc)
    ├─ 5b. Check authorization (does this user/role have access?)
    ├─ 5c. Process request with user context
    │
    │ 6. Response
    │
    ▼
Auth Service
    │
    │ 7. Forward response back
    │
    ▼
nginx
    │
    │ 8. Forward response to browser
    │
    ▼
User Browser (React app receives response)
```

**Key Points:**
- Browser makes request to same domain (no CORS)
- nginx is the entry and exit point for all traffic
- Auth service validates and proxies
- Response flows back through the same path

### 3. Token Refresh Flow (Auth Service Responsibility)
```
Frontend makes API request with expired access token
    │
    │ 1. API Request (GET /api/backend/query)
    │    Cookie: access_token=<expired_jwt>; refresh_token=<valid_jwt>
    │
    ▼
Auth Service
    │
    ├─ 2a. Detect expired access token
    ├─ 2b. Extract refresh token from cookie
    ├─ 2c. Call Cognito token endpoint
    │      POST https://cognito-idp.region.amazonaws.com/
    │      Body: refresh_token, client_id, grant_type=refresh_token
    │
    ▼
AWS Cognito
    │
    ├─ 3a. Validate refresh token
    ├─ 3b. Issue new access token
    │
    ▼
Auth Service
    │
    ├─ 4a. Receive new access token
    ├─ 4b. Set new access token in httpOnly cookie
    │      Set-Cookie: access_token=<new_jwt>; HttpOnly; Secure; SameSite=Strict
    │
    ├─ 4c. Process original request with new token
    │
    │ 5. Response (with updated cookie)
    │
    ▼
Frontend (receives response + fresh cookie, no action needed)
```

### 4. Service-to-Service Communication Flow
```
Scenario 1: User-Initiated Request (pass user context)
Backend Service needs to call Curator Service for user's request
    │
    │ 1. Make internal HTTP request
    │    X-User-Id: abc-123 (pass through user context)
    │    X-User-Email: user@example.com
    │    X-User-Role: user
    │
    ▼
Curator Service (internal:8000)
    │
    ├─ 2a. Extract user context from headers (if present)
    ├─ 2b. Process request with user context (for audit logging)
    │
    │ 3. Response
    │
    ▼
Backend Service


Scenario 2: System-Initiated Request (no user context)
Scheduled job in Retriever needs to call Curator for batch processing
    │
    │ 1. Make internal HTTP request
    │    (No X-User-* headers - system operation)
    │
    ▼
Curator Service (internal:8000)
    │
    ├─ 2a. No user context present
    ├─ 2b. Process as system operation
    │
    │ 3. Response
    │
    ▼
Retriever Service
```

## Security Layers

### Layer 1: Network Isolation
- **Development**: Auth Service (8000) and Frontend (3000) exposed for testing
- **Production**: Only nginx (443) exposed - Auth and Frontend internal only
- **Internal Network**: All backend services on Docker internal network
- **No Direct Access**: External clients cannot reach internal services directly
- **Key Protection**: Network isolation is the primary security boundary

### Layer 2: JWT Validation (Auth Service)
- Validate JWT signature using Cognito public keys (JWKS)
- Check token expiration
- Verify issuer and audience
- Extract and validate user claims (role)
- Only authenticated users can access internal services through the auth gateway

### Layer 3: User Context Propagation
- Auth service extracts user info (user_id, email, role) from validated JWT
- Passes context via HTTP headers to internal services
- Services extract and use context for:
  - Audit logging (who did what)
  - Authorization decisions
  - Resource ownership checks
- User context is optional for service-to-service calls (scheduled jobs, events)

### Layer 4: Role-Based Authorization (Service-Level)
- **Authorization handled by each service** - Not at auth gateway
- Auth service validates identity and extracts user context only
- Each service implements its own authorization logic based on:
  - User role from `X-User-Role` header
  - Resource ownership
  - Business logic requirements
- Services can use decorators/middleware for role checking
- Allows flexible, fine-grained authorization per service

### Layer 5: User Context Trust
- Internal services trust user headers from auth service
- No need for internal services to validate JWT (performance benefit)
- User context used for logging, audit trails, and business logic

## Route Mapping

Auth service provides these endpoints and routes:

```
Auth Service Endpoints:
─────────────────────────────────────────────────────
GET  /api/auth/login              → Redirect to Cognito Hosted UI
GET  /api/auth/callback           → OAuth callback (exchanges code for tokens)
POST /api/auth/logout             → Clear cookies & redirect to Cognito logout
GET  /api/auth/me                 → Get current user info from token

Proxied Internal Service Routes:
─────────────────────────────────────────────────────
/api/backend/*                    → backend:8000/*
/api/curator/*                    → curator:8000/*
/api/retriever/*                  → retriever:8000/*
/api/public/*                     → No auth required (pass through)
```

## AWS Cognito Configuration

### User Pool Setup
- **User Attributes**:
  - email (required)
  - custom:role (user|admin|superadmin)
  
- **App Client**:
  - OAuth 2.0 flows: Authorization code grant
  - Allowed callback URLs: `https://yourdomain.com/api/auth/callback`
  - Allowed sign-out URLs: `https://yourdomain.com/`
  - OAuth scopes: openid, email, profile
  - **Client type**: Confidential (to use client secret)

- **Hosted UI**:
  - Domain: `your-app.auth.region.amazoncognito.com`
  - Custom branding (optional)

### Token Configuration
- **Access Token**: 1 hour expiration
- **Refresh Token**: 7 days expiration
- **ID Token**: Contains user claims (sub, email, custom:role)

**Rationale**: 7-day refresh token provides good balance between security and UX. Users who access the app weekly stay logged in, while compromised tokens have a limited validity window.

## Environment Variables

### Auth Service
```env
AWS_REGION=us-east-1
COGNITO_USER_POOL_ID=us-east-1_xxxxx
COGNITO_APP_CLIENT_ID=xxxxxxxxxxxxx
COGNITO_APP_CLIENT_SECRET=xxxxxxxxxxxxx
COGNITO_DOMAIN=your-app.auth.region.amazoncognito.com
COGNITO_JWKS_URL=https://cognito-idp.region.amazonaws.com/pool_id/.well-known/jwks.json
COGNITO_TOKEN_ENDPOINT=https://your-app.auth.region.amazoncognito.com/oauth2/token
BACKEND_SERVICE_URL=http://backend:8000
CURATOR_SERVICE_URL=http://curator:8000
RETRIEVER_SERVICE_URL=http://retriever:8000
FRONTEND_URL=https://yourdomain.com
COOKIE_DOMAIN=yourdomain.com
COOKIE_SECURE=true
```

### Internal Services (Backend, Curator, Retriever)
```env
# No additional auth-specific environment variables needed
# Services extract user context from request headers
```

### Frontend
```env
# No environment variables needed for API URLs!
# Frontend uses relative URLs (/api/*) which work in both dev and production
# via React proxy (dev) or nginx routing (prod)

# React dev server proxy is configured in package.json:
# "proxy": "http://localhost:8000"
```

**How Frontend Accesses APIs:**
- Development: React proxy forwards `/api/*` → `http://localhost:8000/api/*`
- Production: nginx routes `/api/*` → `http://auth:8000/api/*` (internal network)

## Docker Compose Structure

**Development Configuration:**
```yaml
services:
  # Auth Service - exposed in dev for testing
  auth:
    build: ./auth
    ports:
      - "8000:8000"  # Exposed for local development/testing
    networks:
      - internal

  # Frontend - exposed in dev
  frontend:
    build: ./frontend
    ports:
      - "3000:3000"  # Exposed for local development
    networks:
      - internal

  # Internal services (no public ports in dev or prod)
  backend:
    build: ./backend
    expose:
      - "8000"  # INTERNAL ONLY
    networks:
      - internal

  curator:
    build: ./curator
    expose:
      - "8000"  # INTERNAL ONLY
    networks:
      - internal

  retriever:
    build: ./retriever
    expose:
      - "8000"  # INTERNAL ONLY
    networks:
      - internal

networks:
  internal:
    driver: bridge
```

**Production Configuration (`docker-compose.prod.yml` override):**
```yaml
services:
  # nginx handles SSL/TLS and routing - ONLY service exposed
  nginx:
    image: nginx:alpine
    ports:
      - "443:443"  # ONLY nginx exposed in production
      - "80:80"    # HTTP to HTTPS redirect
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
    networks:
      - internal

  # Remove port exposure from auth and frontend
  auth:
    ports: []  # Override to remove port mapping
    expose:
      - "8000"

  frontend:
    ports: []  # Override to remove port mapping
    expose:
      - "3000"

networks:
  internal:
    driver: bridge
    internal: true  # Prevent external access
```

**Production nginx routing:**
```nginx
server {
    listen 443 ssl;
    server_name yourdomain.com;

    # Frontend (React app)
    location / {
        proxy_pass http://frontend:3000;
    }

    # Auth gateway (all API traffic)
    location /api/ {
        proxy_pass http://auth:8000;
    }
}
```

**Key Security Points:**
- **Development:** Auth (8000) and Frontend (3000) exposed for testing convenience
- **Production:** Only nginx on port 443 exposed, all services internal
- **All API traffic** goes through auth service gateway in both environments
- Internal services never exposed to internet

**Production Traffic Flow:**
```
User → https://yourdomain.com/
  ↓
nginx:443 → frontend:3000 (internal)
  ↓
React App loads in browser

User makes API call → /api/backend/query
  ↓
Browser includes httpOnly cookies automatically
  ↓
nginx:443 routes /api/* → auth:8000 (internal)
  ↓
Auth validates JWT, proxies to backend:8000 (internal)
  ↓
Response flows back through same path
```

## Future Considerations (Not Implemented Yet)

### Request Tracking
- Auth service can log all authenticated requests
- Store: user_id, timestamp, endpoint, method, response_code
- Send to analytics service or database

### User Sync to Neo4j
- After successful authentication, sync user to Neo4j graph
- Store: user_id, email, role, last_login
- Link to user interests and activity nodes

### Enhanced Authorization
- Fine-grained permissions beyond roles
- Resource-level authorization (user can only access their own data)
- Dynamic role assignment

**Example Service-Level Authorization Patterns:**
```python
# Role-based decorator in service
@app.get("/api/backend/admin/settings")
@require_role(["admin", "superadmin"])
def get_admin_settings(user_role: str = Header(alias="X-User-Role")):
    return {"settings": "..."}

# Resource ownership check
@app.get("/api/backend/document/{doc_id}")
def get_document(
    doc_id: str,
    user_id: str = Header(alias="X-User-Id"),
    user_role: str = Header(alias="X-User-Role")
):
    doc = db.get_document(doc_id)
    
    # Only owner or admin can access
    if doc.owner_id != user_id and user_role not in ["admin", "superadmin"]:
        raise HTTPException(403, "Access denied")
    
    return doc
```

### Rate Limiting
- Per-user rate limiting in auth service
- Prevent abuse and DDoS

### Audit Logging
- Comprehensive audit trail of all authenticated actions
- Who did what, when, and from where

## Security Best Practices

1. **Secrets Management**:
   - Use AWS Secrets Manager or HashiCorp Vault for production
   - Store Cognito client secret securely
   - Never commit secrets to repository

2. **Token Security**:
   - Use httpOnly cookies to prevent XSS attacks
   - Use secure flag for HTTPS-only transmission
   - Implement CSRF protection for state-changing operations

3. **Network Security**:
   - Use Docker internal networks to isolate services
   - Only expose auth service and frontend publicly
   - Implement firewall rules at infrastructure level
   - Use HTTPS/TLS for all external communication
   - **Primary Security Boundary**: Network isolation ensures internal services cannot be reached externally

4. **Service Architecture**:
   - Services can call each other directly within internal network
   - User context passed via headers for audit logging
   - Service-to-service calls can be user-initiated or system-initiated
   - No shared secrets needed between services (rely on network isolation)

5. **Monitoring**:
   - Log all authentication attempts (success and failure)
   - Monitor for suspicious patterns (brute force, token abuse)
   - Set up alerts for security events
   - Track user-initiated vs system-initiated operations

6. **Testing**:
   - Mock Cognito for local development and testing
   - Test with expired tokens, invalid tokens, missing tokens
   - Test authorization rules for each role

