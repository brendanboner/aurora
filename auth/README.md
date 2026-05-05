# Aurora Auth Service

FastAPI-based OAuth 2.0 authentication gateway using AWS Cognito. Provides secure token-based authentication and request proxying for the Aurora application's internal services.

## Overview

The auth service acts as the single authentication gateway for all Aurora API endpoints:
- Handles OAuth 2.0 authentication flow with AWS Cognito
- Validates JWT tokens on every API request
- Proxies authenticated requests to backend services with user context
- Manages token lifecycle (validation, refresh, expiration)
- Provides secure session management via httpOnly cookies

## Architecture

```
┌─────────────┐
│   Browser   │
└──────┬──────┘
       │
       │ 1. Login request
       ▼
┌─────────────────────────────────────────────────────────────┐
│                      Auth Service                            │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │   FastAPI    │  │     JWT      │  │  Request Proxy  │   │
│  │   Endpoints  │──│  Validation  │──│   (to services) │   │
│  └──────────────┘  └──────────────┘  └─────────────────┘   │
└───────────┬─────────────────────────────────────────────────┘
            │
            │ 2. OAuth flow
            ▼
    ┌──────────────┐
    │ AWS Cognito  │
    │  User Pool   │
    └──────────────┘
            │
            │ 3. Returns tokens
            ▼
┌─────────────────────────────────────────────────────────────┐
│  Redis (OAuth state storage)                                 │
└─────────────────────────────────────────────────────────────┘
            │
            │ 4. Proxied requests with user context
            ▼
┌─────────────────────────────────────────────────────────────┐
│  Internal Services (Backend, Curator, Retriever)             │
└─────────────────────────────────────────────────────────────┘
```

## Key Features

### Security
- **CSRF Protection**: Cryptographically secure OAuth state parameters stored in Redis
- **Rate Limiting**: Prevents brute force attacks (10 login attempts/min, 20 callbacks/min)
- **Cookie Security**: httpOnly, Secure (HTTPS), SameSite=Strict
- **Header Injection Prevention**: Allowlist-based header filtering
- **JWT Validation**: Full signature and claims validation against Cognito JWKS
- **Group-Based Access Control**: Restricts access to users in required Cognito group (default: `aurora-users`)
- **Automatic Token Refresh**: Seamless access token renewal using refresh tokens
- **Request Size Limits**: 1 MB max request size
- **Security Logging**: All auth events logged with IP and user agent

### Token Management
- **Access Token**: Short-lived (1 hour), used for API authentication
- **ID Token**: Contains user claims (email, role, user_id)
- **Refresh Token**: Long-lived (7 days), used to obtain new access tokens
- **Automatic Refresh**: When access token expires, refresh token is used automatically
- **JWKS Caching**: Public keys cached for 1 hour to improve performance

### Request Proxying
- Validates JWT token on every request
- Injects trusted user context headers (`X-User-Id`, `X-User-Email`, `X-User-Role`)
- Routes requests to appropriate internal services based on path
- Maintains request/response integrity
- 30-second timeout on proxied requests

## Project Structure

```
auth/
├── auth.py                    # Main FastAPI application with endpoints
├── settings.py                # Pydantic settings and configuration
├── Dockerfile                 # Container definition
├── requirements.txt           # Python dependencies
├── pytest.ini                 # Test configuration
├── Makefile                   # Build and test automation
│
├── services/
│   ├── __init__.py
│   └── proxy.py              # Request proxying logic
│
├── utils/
│   ├── __init__.py
│   ├── logger.py             # Logging setup
│   ├── oauth.py              # OAuth & JWT validation
│   ├── middleware.py         # Token validation middleware
│   └── state_storage.py      # Redis-backed OAuth state storage
│
└── tests/
    ├── __init__.py
    ├── conftest.py           # Pytest fixtures
    ├── test_endpoints.py     # API endpoint tests
    ├── test_oauth.py         # OAuth and JWT tests
    ├── test_middleware.py    # Middleware tests
    └── test_proxy.py         # Proxy tests
```

## API Endpoints

### Public Endpoints
- `GET /` - Health check endpoint
- `GET /api/auth/login` - Initiates OAuth flow, redirects to Cognito
- `GET /api/auth/callback` - OAuth callback handler, exchanges code for tokens
- `GET /api/auth/logout` - Clears cookies and logs out from Cognito

### Protected Endpoints
- `GET /api/auth/me` - Returns current user information
- `GET|POST|PUT|DELETE|PATCH /api/backend/*` - Proxy to backend service
- `GET|POST|PUT|DELETE|PATCH /api/curator/*` - Proxy to curator service
- `GET|POST|PUT|DELETE|PATCH /api/retriever/*` - Proxy to retriever service

## Environment Variables

Required configuration (set via Docker Compose or `.env` file):

```bash
# AWS Cognito Configuration
AWS_REGION=us-east-1
COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
COGNITO_APP_CLIENT_ID=your-app-client-id
COGNITO_APP_CLIENT_SECRET=your-app-client-secret
COGNITO_DOMAIN=your-domain.auth.us-east-1.amazoncognito.com
COGNITO_JWKS_URL=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_XXXXXXXXX/.well-known/jwks.json
COGNITO_TOKEN_ENDPOINT=https://your-domain.auth.us-east-1.amazoncognito.com/oauth2/token

# Cognito Group Access Control (optional)
# Users in ANY of these groups can access the application
# Comma-separated list (e.g., "aurora-users,other-group")
# Default: aurora-users
REQUIRED_COGNITO_GROUPS=aurora-users

# Internal Service URLs (Docker network names)
BACKEND_SERVICE_URL=http://backend:8000
CURATOR_SERVICE_URL=http://curator:8000
RETRIEVER_SERVICE_URL=http://retriever:8000

# Application Configuration
APPLICATION_URL=http://localhost:3000
COOKIE_DOMAIN=localhost
COOKIE_SECURE=false

# Redis Configuration
REDIS_HOST=redis
REDIS_PORT=6379

# Optional
LOG_LEVEL=INFO
```

### Configuration Notes

**OAuth Redirect URI**: Automatically constructed based on `APPLICATION_URL`:
- Local: `http://localhost:8000/api/auth/callback`
- Production: `https://yourdomain.com/api/auth/callback`

**Cookie Domain**: Must match your application domain. Use `localhost` for development.

**Cookie Secure**: Set to `false` for local development (HTTP), `true` for production (HTTPS).

## Development

### Running Tests

The Makefile provides automated test commands:

```bash
# Run all tests with coverage
make test

# Run with HTML coverage report
make coverage

# Run specific test suites
make test-unit          # OAuth and middleware tests only
make test-integration   # Endpoints and proxy tests only

# Clean up test artifacts
make clean              # Remove cache and coverage files
make clean-venv         # Remove virtual environment
make clean-all          # Remove everything
```

Each test command:
1. Creates a fresh virtual environment
2. Installs all dependencies
3. Runs the tests
4. Cleans up the virtual environment

### Local Development Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export AWS_REGION=us-east-1
export COGNITO_USER_POOL_ID=...
# ... (set all required variables)

# Or source from parent .env file
set -a; source ../.env; set +a

# Run the service
uvicorn auth:app --reload --port 8000

# Visit http://localhost:8000 to verify
```

### Docker Development

```bash
# Build image
docker build -t aurora-auth .

# Run container (requires .env file in parent directory)
docker run -p 8000:8000 --env-file ../.env aurora-auth
```

## Authentication Flow

### 1. User Login
```
User clicks "Login"
  → Frontend redirects to GET /api/auth/login
  → Auth service generates secure state parameter
  → State stored in Redis (5-minute TTL)
  → Redirects to Cognito Hosted UI
  → User authenticates with Cognito
  → Cognito redirects back to GET /api/auth/callback?code=XXX&state=YYY
  → Auth service validates state parameter
  → Exchanges authorization code for tokens
  → Validates ID token and extracts user info
  → Sets httpOnly cookies with tokens
  → Redirects user to frontend homepage
```

### 2. Making API Requests
```
Frontend makes request to /api/backend/query
  → Request includes cookies automatically
  → Auth service validates access token from cookie
  → If valid: extracts user info and proxies request
  → Adds X-User-Id, X-User-Email, X-User-Role headers
  → Backend service receives request with user context
  → Response returned through auth service to frontend
```

### 3. Token Refresh (Automatic)
```
Access token expires (after 1 hour)
  → Next API request fails token validation
  → Auth service detects expired token
  → Uses refresh token to obtain new access token from Cognito
  → Updates access_token cookie
  → Continues original request with new token
  → User experiences no interruption
```

### 4. User Logout
```
User clicks "Logout"
  → Frontend calls GET /api/auth/logout
  → Auth service clears all cookies
  → Redirects to Cognito logout URL
  → Cognito invalidates session
  → User redirected back to application
```

## Security Implementation

### CSRF Protection
- OAuth state parameter is cryptographically secure (32 bytes, URL-safe)
- State stored in Redis with 5-minute TTL
- Validated on callback and deleted after one-time use
- IP address and user agent stored with state for additional validation

### Rate Limiting
- **Login endpoint**: 10 requests/minute per IP
- **Callback endpoint**: 20 requests/minute per IP
- Automatic 429 (Too Many Requests) responses for violations
- Based on remote IP address

### JWT Token Validation
1. Fetch public keys from Cognito JWKS endpoint (cached 1 hour)
2. Verify token signature using RS256 algorithm
3. Validate token claims:
   - `aud` (audience) matches app client ID
   - `iss` (issuer) matches Cognito issuer URL
   - `exp` (expiration) is in the future
   - `at_hash` (access token hash) matches access token (for ID tokens)

### Cookie Security
- **httpOnly**: Prevents JavaScript access, mitigates XSS attacks
- **Secure**: HTTPS-only transmission (production)
- **SameSite=Strict**: Prevents CSRF attacks
- **Domain validation**: Prevents misconfiguration and subdomain attacks
- **Max-Age**: Access token 1 hour, refresh token 7 days

### Header Injection Prevention
- Allowlist-based header filtering (only safe headers forwarded)
- User context headers set by auth service only (cannot be spoofed)
- Host header removed (set by httpx)
- Content-Type validation for POST/PUT/PATCH requests

### Security Logging
All security-relevant events are logged:
- Successful and failed authentication attempts
- Token refresh events
- Logout events
- All authenticated requests (including user role)
- Rate limit violations
- Invalid state parameters
- Service unavailability

Each log includes:
- User email (if available)
- IP address
- User agent
- Timestamp

### Group-Based Access Control

The auth service enforces Cognito group membership to restrict application access:

**Configuration:**
```bash
# Set the required Cognito groups (comma-separated, default: aurora-users)
# Users need to be in ANY of these groups to access the application
REQUIRED_COGNITO_GROUPS=aurora-users
```

**How it works:**
1. During login, user's Cognito groups are extracted from the ID token (`cognito:groups` claim)
2. Group membership is validated against the configured `REQUIRED_COGNITO_GROUPS`
3. If user is not in any of the required groups, login is rejected with HTTP 403 Forbidden
4. On every API request, group membership is re-validated from the token
5. Users removed from the group will be denied access on their next request

**Setting up Cognito Groups:**

1. Open AWS Console → Amazon Cognito → User Pools
2. Select your Aurora user pool
3. Navigate to "Users and groups" → "Groups"
4. Click "Create group"
   - Group name: `aurora-users` (or your configured name)
   - Description: "Users with access to Aurora application"
   - Precedence: 0
5. Click "Create group"
6. To add users to the group:
   - Go to "Users and groups" → "Users"
   - Select a user
   - Click "Add user to group"
   - Select `aurora-users`
   - Click "Add"

**Error Messages:**
- **Login rejection**: "Access denied. You must be a member of the 'aurora-users' group to access this application."
- **Subsequent requests**: HTTP 403 Forbidden with similar message

**Logs:**
All group validation failures are logged with:
```
Access denied - user not in required group: user=user@example.com, groups=['other-group'], required=aurora-users
```

## Production Deployment

### Docker Compose Integration

The service is designed to run in Docker Compose with other Aurora services:

```yaml
auth:
  build:
    context: .
    dockerfile: auth/Dockerfile
  ports:
    - "8000:8000"
  environment:
    - AWS_REGION=${AWS_REGION}
    - COGNITO_USER_POOL_ID=${COGNITO_USER_POOL_ID}
    # ... other environment variables
  depends_on:
    - redis
```

### Production Checklist

- [ ] **Use HTTPS**: Set `COOKIE_SECURE=true`
- [ ] **Redis in production**: Ensure Redis persistence and backup
- [ ] **Secrets Management**: Use AWS Secrets Manager or similar for `COGNITO_APP_CLIENT_SECRET`
- [ ] **Network Isolation**: Internal services should not be publicly accessible
- [ ] **Log Aggregation**: Send logs to CloudWatch, ELK, or similar
- [ ] **Monitoring**: Set up alerts for:
  - Failed login attempts
  - Rate limit violations
  - Token validation failures
  - Service unavailability
- [ ] **Enable MFA**: For admin/superadmin users in Cognito
- [ ] **Regular Key Rotation**: AWS Cognito automatically rotates signing keys
- [ ] **Domain Configuration**: Ensure cookie domain matches application domain
- [ ] **Cognito User Pool**: Configure password policies, account recovery, MFA

## Troubleshooting

### "No access token provided"
**Cause**: Cookies not being sent by browser
**Solution**: 
- Verify CORS configuration allows credentials
- Check frontend uses `credentials: 'include'` in fetch requests
- Verify cookie domain matches application domain

### "Invalid or expired authentication request"
**Cause**: OAuth state parameter expired or invalid
**Solution**:
- State expires after 5 minutes - user may have waited too long
- Check Redis is running and accessible
- Possible CSRF attack attempt (check logs for IP address)

### "Token has expired" (not auto-refreshed)
**Cause**: Refresh token is missing or expired
**Solution**:
- Refresh tokens expire after 7 days
- User needs to re-authenticate
- Check if logout was called (clears refresh token)

### "Service temporarily unavailable"
**Cause**: Internal service is unreachable
**Solution**:
- Check if backend/curator/retriever services are running
- Verify Docker network connectivity
- Check service URLs in environment variables
- Review service logs for errors

### JWKS Fetch Failures
**Cause**: Cannot fetch public keys from Cognito
**Solution**:
- Verify `COGNITO_JWKS_URL` is correct
- Check network connectivity to AWS
- Verify AWS region is correct
- Check for AWS service outages

### Rate Limit Errors (429)
**Cause**: Too many requests from same IP
**Solution**:
- Wait one minute before retrying
- Check if IP is correct (could be proxy issue)
- Investigate potential bot or attack

## Testing

### Test Coverage

The test suite includes:
- **OAuth tests**: Code exchange, token validation, JWKS caching, expiration handling
- **Middleware tests**: Token validation, automatic refresh, error scenarios
- **Proxy tests**: Request forwarding, header injection, user context, error handling
- **Endpoint tests**: All public and protected endpoints, rate limiting, cookies

Target: 80%+ code coverage

### Running Specific Tests

```bash
# Run a specific test file
pytest tests/test_oauth.py -v

# Run a specific test function
pytest tests/test_oauth.py::test_validate_jwt_token -v

# Run tests matching a pattern
pytest -k "test_token" -v

# Run with detailed output
pytest -vv --tb=short
```

## Related Documentation

For general-purpose integration guide (using this service in other applications):
- See `INTEGRATION_GUIDE.md` in this directory

For Aurora-specific architecture documentation:
- [AUTH_ARCHITECTURE.md](../doc/AUTH_ARCHITECTURE.md)
- [AUTH_IMPLEMENTATION_PLAN.md](../doc/AUTH_IMPLEMENTATION_PLAN.md)
- [DOCKER_COMPOSE.md](../doc/DOCKER_COMPOSE.md)

## Dependencies

- **FastAPI**: Web framework
- **Uvicorn**: ASGI server
- **python-jose**: JWT validation
- **httpx**: Async HTTP client for OAuth and proxying
- **pydantic/pydantic-settings**: Configuration management
- **slowapi**: Rate limiting
- **redis**: OAuth state storage
- **pytest**: Testing framework

## Support

For issues or questions:
1. Check this README for common issues
2. Review test files for usage examples
3. Check logs for detailed error messages
4. Refer to `INTEGRATION_GUIDE.md` for integration help
