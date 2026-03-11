# AWS Cognito Auth Gateway - Integration Guide

A production-ready, drop-in authentication gateway service for securing API routes with AWS Cognito OAuth 2.0 and JWT validation. This service acts as a reverse proxy that handles all authentication concerns, allowing your backend services to focus on business logic.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Security Features](#security-features)
4. [Prerequisites](#prerequisites)
5. [AWS Cognito Setup](#aws-cognito-setup)
6. [Service Configuration](#service-configuration)
7. [Integration Steps](#integration-steps)
8. [Frontend Integration](#frontend-integration)
9. [Backend Integration](#backend-integration)
10. [Deployment](#deployment)
11. [Security Best Practices](#security-best-practices)
12. [Monitoring and Logging](#monitoring-and-logging)
13. [Troubleshooting](#troubleshooting)
14. [API Reference](#api-reference)

---

## Overview

This authentication gateway service provides:

- **OAuth 2.0 authentication** with AWS Cognito
- **JWT token validation** on every API request
- **Automatic token refresh** for seamless user experience
- **Request proxying** to internal services with user context
- **CSRF protection** via OAuth state parameters
- **Rate limiting** to prevent abuse
- **Security logging** for audit trails

### What This Service Does

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend Application (React, Vue, Angular, etc.)            │
└──────────────┬───────────────────────────────────────────────┘
               │
               │ All API requests go through auth gateway
               ▼
┌──────────────────────────────────────────────────────────────┐
│              Auth Gateway Service (This Service)              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  1. Validates JWT tokens                               │  │
│  │  2. Automatically refreshes expired tokens             │  │
│  │  3. Extracts user info (email, role, user_id)         │  │
│  │  4. Adds X-User-* headers                              │  │
│  │  5. Proxies request to internal service                │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────┬───────────────────────────────────────────────┘
               │
               │ Requests include user context headers
               ▼
┌──────────────────────────────────────────────────────────────┐
│  Internal Services (Not publicly accessible)                 │
│  - No authentication logic needed                            │
│  - Trust X-User-* headers from auth gateway                  │
│  - Focus on business logic                                   │
└──────────────────────────────────────────────────────────────┘
```

### What Your Backend Services Don't Need

- ✅ No OAuth flow implementation
- ✅ No JWT validation logic
- ✅ No token refresh handling
- ✅ No JWKS key management
- ✅ No session management
- ✅ No CSRF protection implementation

Your services simply read `X-User-Email`, `X-User-Role`, and `X-User-Id` headers that are guaranteed to be valid.

---

## Architecture

### High-Level Flow

```
┌─────────────┐
│   Browser   │
└──────┬──────┘
       │
       │ 1. Login request
       ▼
┌──────────────────────────────────────────────────┐
│            Auth Gateway Service                   │
│  ┌────────────────┐  ┌─────────────────────┐    │
│  │  FastAPI App   │  │  JWT Validation     │    │
│  │  - /login      │  │  - Verify signature │    │
│  │  - /callback   │  │  - Check expiry     │    │
│  │  - /logout     │  │  - Extract claims   │    │
│  │  - /me         │  └─────────────────────┘    │
│  └────────────────┘                              │
│  ┌────────────────────────────────────────────┐  │
│  │  Request Proxy                             │  │
│  │  - Validates token                         │  │
│  │  - Routes to correct service               │  │
│  │  - Injects X-User-* headers                │  │
│  └────────────────────────────────────────────┘  │
└──────────┬───────────────────────────────────────┘
           │
           │ 2. OAuth flow
           ▼
   ┌──────────────┐
   │ AWS Cognito  │
   │  User Pool   │
   └──────────────┘
           │
           │ 3. Returns tokens (access, id, refresh)
           ▼
   ┌──────────────┐
   │    Redis     │
   │  (OAuth      │
   │   states)    │
   └──────────────┘
           │
           │ 4. Proxied requests with user context
           ▼
   ┌──────────────────────────────────────┐
   │  Your Backend Services               │
   │  - Service A (users API)             │
   │  - Service B (data API)              │
   │  - Service C (admin API)             │
   └──────────────────────────────────────┘
```

### Component Responsibilities

#### Auth Gateway Service
- Manages OAuth 2.0 flow with Cognito
- Validates JWT tokens on every request
- Stores OAuth state in Redis (CSRF protection)
- Automatically refreshes expired tokens
- Proxies authenticated requests to backend services
- Rate limits authentication endpoints
- Logs all security events

#### AWS Cognito
- User pool for storing users
- Hosted UI for login/signup
- Issues JWT tokens (access, ID, refresh)
- Manages user sessions
- Provides JWKS endpoint for public keys

#### Redis
- Stores OAuth state parameters (5-minute TTL)
- Prevents CSRF attacks
- Optional: Can store session data

#### Your Backend Services
- Receive requests with guaranteed user context
- Read `X-User-Email`, `X-User-Role`, `X-User-Id` headers
- Focus on business logic
- Never exposed to public internet

---

## Security Features

### 1. CSRF Protection

**Problem**: Attackers can trick users into making authenticated requests

**Solution**: OAuth state parameter
- Cryptographically secure 32-byte token generated on login
- Stored in Redis with 5-minute TTL
- Validated on OAuth callback
- One-time use (deleted after validation)
- Includes IP address and user agent for additional validation

### 2. JWT Validation

**Every request is validated:**
1. Token signature verified using Cognito's public keys (JWKS)
2. Token expiration checked
3. Audience (`aud`) claim verified
4. Issuer (`iss`) claim verified
5. Access token hash (`at_hash`) verified for ID tokens

**Public keys are cached** for 1 hour to improve performance while allowing for AWS key rotation.

### 3. Cookie Security

**httpOnly**: Prevents JavaScript from accessing tokens (XSS protection)
```
document.cookie // Won't contain tokens
```

**Secure**: Cookies only sent over HTTPS (production)
```
Cookie: Secure; // Only transmitted over HTTPS
```

**SameSite=Strict**: Prevents CSRF attacks
```
Cookie: SameSite=Strict; // Never sent on cross-site requests
```

**Domain Validation**: Prevents subdomain attacks and misconfigurations
```python
# Rejects overly broad wildcard domains
if domain.startswith('.'):
    raise ValueError("Domain too broad")
```

### 4. Rate Limiting

Prevents brute force attacks:
- **Login endpoint**: 10 requests/minute per IP
- **Callback endpoint**: 20 requests/minute per IP
- **Automatic 429 response** on violations

### 5. Group-Based Access Control

**Problem**: Need to restrict access to specific users

**Solution**: Cognito group membership validation
- Validates user is in required Cognito group on login
- Re-validates on every API request
- Configurable via `REQUIRED_COGNITO_GROUP` environment variable (default: `aurora-users`)
- Returns HTTP 403 Forbidden if user not in group
- Logs all access denials with user email and groups

**Setup**:
1. Create a Cognito group (e.g., `aurora-users`) in AWS Console
2. Add authorized users to the group
3. Configure `REQUIRED_COGNITO_GROUP=aurora-users` in environment
4. Users not in the group will be denied access on login and all subsequent requests

### 6. Header Injection Prevention

**Allowlist approach**: Only safe headers forwarded
```python
SAFE_HEADERS = {
    'content-type', 'content-length', 'accept', 
    'accept-encoding', 'accept-language', 
    'user-agent', 'referer'
}
```

**User context headers** are added by auth service only (cannot be spoofed):
```
X-User-Id: 123e4567-e89b-12d3-a456-426614174000
X-User-Email: user@example.com
X-User-Role: admin
```

### 7. Automatic Token Refresh

Access tokens expire after 1 hour. The service automatically:
1. Detects expired access token
2. Uses refresh token to get new access token from Cognito
3. Updates cookie with new token
4. Continues original request
5. User experiences no interruption

### 8. Request Size Limits

Maximum request size: **1 MB**

Prevents denial-of-service attacks via large payloads.

---

## Prerequisites

### Required

1. **AWS Account** with Cognito enabled
2. **Python 3.11+** (for local development)
3. **Docker** (for containerized deployment)
4. **Redis** (for OAuth state storage)

### Optional

- **Docker Compose** (for orchestrating multiple services)
- **Load Balancer** (for production deployments)
- **SSL Certificate** (for HTTPS in production)

---

## AWS Cognito Setup

### Step 1: Create User Pool

**Note an octo user pool is already made. If we want the same users across our applications we can use the same pool. We can also user the same pool and limit access to application but this service will need to be updated to accomodate.**

1. Go to AWS Console → Cognito → User Pools
2. Click "Create user pool"
3. **Sign-in experience**:
   - Sign-in options: Email
   - Enable "Allow users to sign themselves up"
4. **Security requirements**:
   - Password policy: Set according to your requirements
   - MFA: Optional (recommended for admin users)
5. **Sign-up experience**:
   - Required attributes: Email
   - Optional attributes: Name (optional)
6. **Message delivery**:
   - Email provider: Cognito (or SES for production)
7. **User pool name**: Choose a name (e.g., `my-app-users`)
8. Click "Create user pool"

### Step 2: Create App Client

1. In your user pool, go to "App integration" tab
2. Click "Create app client"
3. **App client configuration**:
   - App client name: `my-app-client`
   - App type: "Public client"
   - Authentication flows: Check "ALLOW_REFRESH_TOKEN_AUTH"
4. **Hosted UI settings**:
   - Callback URLs: 
     - Local: `http://localhost:8000/api/auth/callback`
     - Production: `https://yourdomain.com/api/auth/callback`
   - Sign out URLs:
     - Local: `http://localhost:3000`
     - Production: `https://yourdomain.com`
   - Identity providers: Check "Cognito user pool"
   - OAuth 2.0 grant types: Check "Authorization code grant"
   - OpenID Connect scopes: Check "openid", "email", "profile"
5. Click "Create app client"

### Step 3: Configure Custom Domain (Optional)

For a branded login experience:
1. Go to "App integration" → "Domain"
2. Choose "Cognito domain" or "Custom domain"
3. Enter domain prefix (e.g., `my-app-auth`)
4. Save changes

### Step 4: Add Custom Attributes (Optional)

For role-based access control:
1. Go to "User pool properties" → "Custom attributes"
2. Add custom attribute:
   - Name: `role`
   - Type: String
   - Mutable: Yes
3. Save changes

### Step 5: Gather Required Values

You'll need these values for configuration:

```bash
# AWS Region (e.g., us-east-1)
AWS_REGION=

# User Pool ID (found in "User pool overview")
COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX

# App Client ID (found in "App clients")
COGNITO_APP_CLIENT_ID=

# App Client Secret (found in "App clients" → Show client secret)
COGNITO_APP_CLIENT_SECRET=

# Domain (from "App integration" → "Domain")
COGNITO_DOMAIN=your-domain.auth.us-east-1.amazoncognito.com

# JWKS URL (constructed from User Pool ID)
COGNITO_JWKS_URL=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_XXXXXXXXX/.well-known/jwks.json

# Token Endpoint (constructed from domain)
COGNITO_TOKEN_ENDPOINT=https://your-domain.auth.us-east-1.amazoncognito.com/oauth2/token
```

---

## Service Configuration

### Environment Variables

Create a `.env` file with the following variables:

```bash
# ============================================
# AWS Cognito Configuration
# ============================================
AWS_REGION=us-east-1
COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
COGNITO_APP_CLIENT_ID=your-app-client-id
COGNITO_APP_CLIENT_SECRET=your-app-client-secret
COGNITO_DOMAIN=your-domain.auth.us-east-1.amazoncognito.com
COGNITO_JWKS_URL=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_XXXXXXXXX/.well-known/jwks.json
COGNITO_TOKEN_ENDPOINT=https://your-domain.auth.us-east-1.amazoncognito.com/oauth2/token

# ============================================
# Internal Service URLs
# ============================================
# Map your backend services to these variables
# Use Docker network names or internal IPs
# Pattern: SERVICENAME_SERVICE_URL=http://service-name:port

BACKEND_SERVICE_URL=http://api-service:8000
CURATOR_SERVICE_URL=http://curator-service:8000
RETRIEVER_SERVICE_URL=http://retriever-service:8000

# ============================================
# Application Configuration
# ============================================
# URL where your frontend is hosted
APPLICATION_URL=http://localhost:3000

# Cookie domain (must match your application domain)
# Use 'localhost' for local development
# Use 'yourdomain.com' for production (no subdomain prefix)
COOKIE_DOMAIN=localhost

# Cookie security (false for HTTP, true for HTTPS)
COOKIE_SECURE=false

# ============================================
# Redis Configuration
# ============================================
REDIS_HOST=redis
REDIS_PORT=6379

# ============================================
# Optional Configuration
# ============================================
LOG_LEVEL=INFO
```

### Customizing Service Routes

By default, the service proxies to three backend services:
- `/api/backend/*` → `BACKEND_SERVICE_URL`
- `/api/curator/*` → `CURATOR_SERVICE_URL`
- `/api/retriever/*` → `RETRIEVER_SERVICE_URL`

**To customize for your application**, edit `services/proxy.py`:

```python
# Service URL mapping
SERVICE_ROUTES = {
    "/api/users": settings.users_service_url,
    "/api/posts": settings.posts_service_url,
    "/api/admin": settings.admin_service_url,
}
```

And add corresponding environment variables in `settings.py`:

```python
class Settings(BaseSettings):
    # ... existing Cognito config ...
    
    # Your service URLs
    users_service_url: str
    posts_service_url: str
    admin_service_url: str
```

---

## Integration Steps

### Step 1: Clone or Copy the Service

```bash
# Option A: Copy the auth service directory to your project
cp -r path/to/auth-service ./auth

# Option B: Use as a Git submodule
git submodule add <repo-url> auth
```

### Step 2: Update Configuration

1. Copy the `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Fill in your AWS Cognito values (from setup above)

3. Configure your service URLs in `services/proxy.py`

4. Update `settings.py` with your service URL variables

### Step 3: Set Up Redis

**Option A: Docker Compose (Recommended)**

Add Redis to your `docker-compose.yml`:

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes

volumes:
  redis_data:
```

**Option B: Standalone Redis**

```bash
# macOS
brew install redis
redis-server

# Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis

# Docker
docker run -d -p 6379:6379 redis:7-alpine
```

### Step 4: Add Auth Service to Docker Compose

Add the auth service to your `docker-compose.yml`:

```yaml
services:
  auth:
    build:
      context: .
      dockerfile: auth/Dockerfile
    ports:
      - "8000:8000"
    environment:
      - AWS_REGION=${AWS_REGION}
      - COGNITO_USER_POOL_ID=${COGNITO_USER_POOL_ID}
      - COGNITO_APP_CLIENT_ID=${COGNITO_APP_CLIENT_ID}
      - COGNITO_APP_CLIENT_SECRET=${COGNITO_APP_CLIENT_SECRET}
      - COGNITO_DOMAIN=${COGNITO_DOMAIN}
      - COGNITO_JWKS_URL=${COGNITO_JWKS_URL}
      - COGNITO_TOKEN_ENDPOINT=${COGNITO_TOKEN_ENDPOINT}
      - BACKEND_SERVICE_URL=${BACKEND_SERVICE_URL}
      - CURATOR_SERVICE_URL=${CURATOR_SERVICE_URL}
      - RETRIEVER_SERVICE_URL=${RETRIEVER_SERVICE_URL}
      - APPLICATION_URL=${APPLICATION_URL}
      - COOKIE_DOMAIN=${COOKIE_DOMAIN}
      - COOKIE_SECURE=${COOKIE_SECURE}
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - LOG_LEVEL=${LOG_LEVEL}
    depends_on:
      - redis
    networks:
      - app_network

  redis:
    image: redis:7-alpine
    networks:
      - app_network

  # Your existing services
  backend:
    # ... your service config ...
    networks:
      - app_network
    # Important: Don't expose to public internet!
    # Only auth service should be publicly accessible

networks:
  app_network:
    driver: bridge
```

### Step 5: Update Nginx/Load Balancer Configuration

**Example Nginx configuration:**

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    # All /api/* requests go to auth gateway
    location /api/ {
        proxy_pass http://auth:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Frontend application
    location / {
        proxy_pass http://frontend:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Step 6: Test the Setup

```bash
# Start all services
docker-compose up -d

# Check auth service health
curl http://localhost:8000/
# Expected: {"status": "ok", "service": "auth"}

# Check logs
docker-compose logs auth

# Test login flow (should redirect to Cognito)
curl -v http://localhost:8000/api/auth/login
```

---

## Frontend Integration

### React Example

```typescript
// services/auth.ts
const API_BASE = 'http://localhost:8000';

export const authService = {
  // Redirect to login
  login() {
    window.location.href = `${API_BASE}/api/auth/login`;
  },

  // Logout
  async logout() {
    window.location.href = `${API_BASE}/api/auth/logout`;
  },

  // Get current user
  async getCurrentUser() {
    const response = await fetch(`${API_BASE}/api/auth/me`, {
      credentials: 'include', // Important: Send cookies
    });
    
    if (!response.ok) {
      if (response.status === 401) {
        throw new Error('Not authenticated');
      }
      throw new Error('Failed to fetch user');
    }
    
    return response.json();
  },

  // Make authenticated API request
  async apiRequest(endpoint: string, options: RequestInit = {}) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      credentials: 'include', // Important: Send cookies
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });
    
    if (!response.ok) {
      if (response.status === 401) {
        // Redirect to login
        this.login();
        throw new Error('Not authenticated');
      }
      throw new Error(`API error: ${response.statusText}`);
    }
    
    return response.json();
  },
};

// App.tsx
import { useEffect, useState } from 'react';
import { authService } from './services/auth';

function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check if user is logged in
    authService.getCurrentUser()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const handleLogin = () => {
    authService.login();
  };

  const handleLogout = () => {
    authService.logout();
  };

  if (loading) {
    return <div>Loading...</div>;
  }

  if (!user) {
    return (
      <div>
        <h1>Welcome</h1>
        <button onClick={handleLogin}>Login</button>
      </div>
    );
  }

  return (
    <div>
      <h1>Welcome, {user.email}</h1>
      <p>Role: {user.role}</p>
      <button onClick={handleLogout}>Logout</button>
    </div>
  );
}

export default App;
```

### Vue.js Example

```vue
<!-- services/auth.js -->
<script setup>
const API_BASE = 'http://localhost:8000';

export const authService = {
  login() {
    window.location.href = `${API_BASE}/api/auth/login`;
  },

  logout() {
    window.location.href = `${API_BASE}/api/auth/logout`;
  },

  async getCurrentUser() {
    const response = await fetch(`${API_BASE}/api/auth/me`, {
      credentials: 'include',
    });
    
    if (!response.ok) throw new Error('Not authenticated');
    return response.json();
  },

  async apiRequest(endpoint, options = {}) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });
    
    if (!response.ok) {
      if (response.status === 401) {
        this.login();
        throw new Error('Not authenticated');
      }
      throw new Error(`API error: ${response.statusText}`);
    }
    
    return response.json();
  },
};
</script>

<!-- App.vue -->
<script setup>
import { ref, onMounted } from 'vue';
import { authService } from './services/auth';

const user = ref(null);
const loading = ref(true);

onMounted(async () => {
  try {
    user.value = await authService.getCurrentUser();
  } catch (error) {
    user.value = null;
  } finally {
    loading.value = false;
  }
});

const handleLogin = () => authService.login();
const handleLogout = () => authService.logout();
</script>

<template>
  <div v-if="loading">Loading...</div>
  <div v-else-if="!user">
    <h1>Welcome</h1>
    <button @click="handleLogin">Login</button>
  </div>
  <div v-else>
    <h1>Welcome, {{ user.email }}</h1>
    <p>Role: {{ user.role }}</p>
    <button @click="handleLogout">Logout</button>
  </div>
</template>
```

### Important Frontend Notes

1. **Always use `credentials: 'include'`** in fetch requests to send cookies
2. **Handle 401 responses** by redirecting to login
3. **No need to manage tokens** - cookies are handled automatically
4. **CORS configuration** is handled by auth service

---

## Backend Integration

### Reading User Context

Your backend services receive these headers on every authenticated request:

```
X-User-Id: 123e4567-e89b-12d3-a456-426614174000
X-User-Email: user@example.com
X-User-Role: admin
```

### Python/FastAPI Example

```python
from fastapi import FastAPI, Header, HTTPException

app = FastAPI()

@app.get("/api/backend/data")
async def get_data(
    x_user_id: str = Header(...),
    x_user_email: str = Header(...),
    x_user_role: str = Header(...)
):
    # Headers are guaranteed to be valid (set by auth gateway)
    print(f"User: {x_user_email}, Role: {x_user_role}")
    
    # Role-based access control
    if x_user_role not in ["admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Use user context in your business logic
    return {"data": "sensitive data", "requested_by": x_user_email}
```

### Node.js/Express Example

```javascript
const express = require('express');
const app = express();

app.get('/api/backend/data', (req, res) => {
  // Read user context from headers
  const userId = req.headers['x-user-id'];
  const userEmail = req.headers['x-user-email'];
  const userRole = req.headers['x-user-role'];

  console.log(`User: ${userEmail}, Role: ${userRole}`);

  // Role-based access control
  if (!['admin', 'superadmin'].includes(userRole)) {
    return res.status(403).json({ error: 'Insufficient permissions' });
  }

  // Use user context in your business logic
  res.json({ data: 'sensitive data', requested_by: userEmail });
});

app.listen(8000);
```

### Go Example

```go
package main

import (
    "encoding/json"
    "net/http"
)

func dataHandler(w http.ResponseWriter, r *http.Request) {
    // Read user context from headers
    userID := r.Header.Get("X-User-Id")
    userEmail := r.Header.Get("X-User-Email")
    userRole := r.Header.Get("X-User-Role")

    log.Printf("User: %s, Role: %s", userEmail, userRole)

    // Role-based access control
    if userRole != "admin" && userRole != "superadmin" {
        http.Error(w, "Insufficient permissions", http.StatusForbidden)
        return
    }

    // Use user context in your business logic
    response := map[string]string{
        "data":         "sensitive data",
        "requested_by": userEmail,
    }

    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(response)
}

func main() {
    http.HandleFunc("/api/backend/data", dataHandler)
    http.ListenAndServe(":8000", nil)
}
```

### Important Backend Notes

1. **Trust the headers** - They're added by the auth gateway and cannot be spoofed
2. **Don't expose services publicly** - Only the auth gateway should be accessible from the internet
3. **Use network isolation** - Run backend services in a private Docker network or VPC
4. **Implement role-based access control** using `X-User-Role` header
5. **Log user actions** using `X-User-Email` for audit trails

---

## Deployment

### Production Deployment Checklist

- [ ] **HTTPS Only**: Set `COOKIE_SECURE=true`
- [ ] **Redis Persistence**: Enable AOF or RDB
- [ ] **Secrets Management**: Use AWS Secrets Manager, HashiCorp Vault, or similar
- [ ] **Network Isolation**: Backend services not publicly accessible
- [ ] **Load Balancer**: Use ALB, NGINX, or Traefik
- [ ] **Monitoring**: Set up CloudWatch, Datadog, or Prometheus
- [ ] **Logging**: Aggregate logs (ELK, CloudWatch, etc.)
- [ ] **Alerting**: Failed logins, token errors, rate limits
- [ ] **Backup**: Redis data backups
- [ ] **SSL Certificates**: Use Let's Encrypt or AWS ACM
- [ ] **Domain Configuration**: Ensure cookie domain matches application domain
- [ ] **MFA**: Enable for admin users in Cognito
- [ ] **Rate Limiting**: Configure appropriate limits for your traffic

### Docker Compose Production Example

```yaml
version: '3.8'

services:
  auth:
    build:
      context: .
      dockerfile: auth/Dockerfile
    restart: always
    ports:
      - "8000:8000"
    environment:
      - AWS_REGION=${AWS_REGION}
      - COGNITO_USER_POOL_ID=${COGNITO_USER_POOL_ID}
      - COGNITO_APP_CLIENT_ID=${COGNITO_APP_CLIENT_ID}
      - COGNITO_APP_CLIENT_SECRET=${COGNITO_APP_CLIENT_SECRET}
      - COGNITO_DOMAIN=${COGNITO_DOMAIN}
      - COGNITO_JWKS_URL=${COGNITO_JWKS_URL}
      - COGNITO_TOKEN_ENDPOINT=${COGNITO_TOKEN_ENDPOINT}
      - BACKEND_SERVICE_URL=http://backend:8000
      - APPLICATION_URL=https://yourdomain.com
      - COOKIE_DOMAIN=yourdomain.com
      - COOKIE_SECURE=true
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - LOG_LEVEL=INFO
    depends_on:
      - redis
    networks:
      - app_network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/"]
      interval: 30s
      timeout: 10s
      retries: 3

  redis:
    image: redis:7-alpine
    restart: always
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    networks:
      - app_network
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 30s
      timeout: 10s
      retries: 3

  backend:
    # Your backend service
    restart: always
    networks:
      - app_network
    # Don't expose ports to host - only accessible via auth gateway

networks:
  app_network:
    driver: bridge

volumes:
  redis_data:
```

### Kubernetes Deployment Example

```yaml
# auth-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: auth-service
spec:
  replicas: 3
  selector:
    matchLabels:
      app: auth-service
  template:
    metadata:
      labels:
        app: auth-service
    spec:
      containers:
      - name: auth
        image: your-registry/auth-service:latest
        ports:
        - containerPort: 8000
        env:
        - name: AWS_REGION
          valueFrom:
            secretKeyRef:
              name: cognito-secrets
              key: aws-region
        - name: COGNITO_USER_POOL_ID
          valueFrom:
            secretKeyRef:
              name: cognito-secrets
              key: user-pool-id
        # ... other environment variables
        livenessProbe:
          httpGet:
            path: /
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5

---
apiVersion: v1
kind: Service
metadata:
  name: auth-service
spec:
  selector:
    app: auth-service
  ports:
  - protocol: TCP
    port: 8000
    targetPort: 8000
  type: ClusterIP

---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: auth-ingress
  annotations:
    kubernetes.io/ingress.class: nginx
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
  - hosts:
    - yourdomain.com
    secretName: auth-tls
  rules:
  - host: yourdomain.com
    http:
      paths:
      - path: /api
        pathType: Prefix
        backend:
          service:
            name: auth-service
            port:
              number: 8000
```

---

## Security Best Practices

### 1. Use HTTPS in Production

```bash
# Always set in production
COOKIE_SECURE=true
```

Without HTTPS, cookies can be intercepted.

### 2. Secure AWS Cognito Client Secret

**DON'T**: Store in environment variables or code
```bash
# Bad
COGNITO_APP_CLIENT_SECRET=abc123xyz
```

**DO**: Use secrets management
```bash
# Good - AWS Secrets Manager
aws secretsmanager get-secret-value --secret-id cognito-client-secret

# Good - HashiCorp Vault
vault kv get secret/cognito/client-secret

# Good - Kubernetes Secrets
kubectl create secret generic cognito-secrets \
  --from-literal=client-secret=abc123xyz
```

### 3. Network Isolation

**Backend services should NEVER be publicly accessible.**

```yaml
# Good - Backend only accessible via auth gateway
services:
  auth:
    ports:
      - "8000:8000"  # Public
    networks:
      - app_network

  backend:
    # No ports exposed to host
    networks:
      - app_network

networks:
  app_network:
    driver: bridge
```

### 4. Enable MFA for Admin Users

In AWS Cognito:
1. Go to your user pool
2. Sign-in experience → Multi-factor authentication
3. Required for: Select user groups (e.g., admin, superadmin)
4. MFA methods: SMS or TOTP

### 5. Monitor Failed Login Attempts

Set up alerts for:
- More than 5 failed logins from same IP in 5 minutes
- Rate limit violations
- Invalid state parameters (potential CSRF attempts)

### 6. Regular Security Audits

- Review Cognito user pool logs
- Check for inactive users
- Rotate client secrets annually
- Update dependencies regularly

### 7. Implement Role-Based Access Control (RBAC)

```python
# Example: Decorator for role checking
from functools import wraps
from fastapi import HTTPException, Header

def require_role(*allowed_roles):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, x_user_role: str = Header(...), **kwargs):
            if x_user_role not in allowed_roles:
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# Usage
@app.get("/api/admin/users")
@require_role("admin", "superadmin")
async def list_users():
    return {"users": [...]}
```

---

## Monitoring and Logging

### Key Metrics to Monitor

1. **Authentication Rate**
   - Successful logins per minute
   - Failed logins per minute
   - Token refresh rate

2. **Error Rates**
   - 401 (Unauthorized) responses
   - 403 (Forbidden) responses
   - 429 (Rate limit) responses
   - 503 (Service unavailable) responses

3. **Latency**
   - OAuth callback time
   - Token validation time
   - Proxy request time

4. **Token Lifecycle**
   - Average token age at refresh
   - Refresh token usage rate
   - Token expiration events

### Logging Examples

The service logs all security events:

```
# Successful login
2024-01-15 10:30:45 - auth - INFO - Successful authentication: user=user@example.com, role=user, ip=192.168.1.100

# Failed login
2024-01-15 10:31:12 - auth - WARNING - Invalid or expired state parameter: state=abc123, ip=192.168.1.100

# Token refresh
2024-01-15 11:30:45 - auth - INFO - Token refreshed for user: user@example.com

# Authenticated request (includes role information)
2024-01-15 12:00:00 - auth - INFO - Proxying request: user=admin@example.com, role=admin, method=GET, path=/api/admin/users, ip=192.168.1.100

# Logout
2024-01-15 15:00:00 - auth - INFO - User logout: user=user@example.com, ip=192.168.1.100
```

### CloudWatch Integration (AWS)

```python
# Add to utils/logger.py
import boto3
from datetime import datetime

cloudwatch = boto3.client('logs', region_name='us-east-1')

def log_to_cloudwatch(log_group, log_stream, message):
    cloudwatch.put_log_events(
        logGroupName=log_group,
        logStreamName=log_stream,
        logEvents=[{
            'timestamp': int(datetime.now().timestamp() * 1000),
            'message': message
        }]
    )
```

### Prometheus Metrics

```python
# Add to auth.py
from prometheus_client import Counter, Histogram, generate_latest

# Define metrics
login_counter = Counter('auth_logins_total', 'Total login attempts', ['status'])
token_refresh_counter = Counter('auth_token_refreshes_total', 'Total token refreshes')
request_latency = Histogram('auth_request_duration_seconds', 'Request latency')

# Use in endpoints
@app.get("/api/auth/callback")
async def auth_callback(code: str, state: str):
    try:
        # ... authentication logic ...
        login_counter.labels(status='success').inc()
    except Exception:
        login_counter.labels(status='failure').inc()
        raise

# Metrics endpoint
@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")
```

---

## Troubleshooting

### Problem: "No access token provided"

**Symptoms**: 401 error on API requests

**Causes**:
1. Frontend not sending cookies (`credentials: 'include'` missing)
2. Cookie domain mismatch
3. CORS not configured properly

**Solutions**:
```javascript
// 1. Ensure credentials are included
fetch('/api/backend/data', {
  credentials: 'include'  // Add this
});

// 2. Check cookie domain matches
// If app is on app.example.com, set COOKIE_DOMAIN=example.com

// 3. Verify CORS allows credentials
// Auth service CORS config:
allow_credentials=True
allow_origins=[settings.application_url]
```

### Problem: "Invalid or expired authentication request"

**Symptoms**: Error after OAuth callback

**Causes**:
1. OAuth state expired (5-minute timeout)
2. Redis not running
3. State parameter tampered with (CSRF attempt)

**Solutions**:
```bash
# 1. Check Redis is running
docker-compose ps redis
redis-cli ping

# 2. Check Redis connectivity from auth service
docker-compose exec auth python -c "import redis; r = redis.Redis(host='redis'); print(r.ping())"

# 3. Check logs for details
docker-compose logs auth | grep "state="
```

### Problem: Token refresh fails

**Symptoms**: Users logged out unexpectedly

**Causes**:
1. Refresh token expired (7 days)
2. Refresh token revoked in Cognito
3. User signed out from Cognito

**Solutions**:
```bash
# Check Cognito user pool settings
# Ensure refresh token expiration is set appropriately

# Check logs
docker-compose logs auth | grep "Token refresh failed"

# User needs to re-authenticate
# This is expected after 7 days or logout
```

### Problem: Service unavailable (503)

**Symptoms**: API requests fail with 503

**Causes**:
1. Backend service not running
2. Incorrect service URL
3. Network connectivity issues

**Solutions**:
```bash
# 1. Check all services are running
docker-compose ps

# 2. Verify service URLs
docker-compose exec auth printenv | grep SERVICE_URL

# 3. Test connectivity from auth service
docker-compose exec auth curl http://backend:8000/

# 4. Check Docker network
docker network inspect <network_name>
```

### Problem: Rate limit errors (429)

**Symptoms**: "Rate limit exceeded" errors

**Causes**:
1. Too many requests from same IP
2. Potential bot or attack
3. Load testing without adjusting limits

**Solutions**:
```python
# Adjust rate limits in auth.py
@app.get("/api/auth/login")
@limiter.limit("20/minute")  # Increase from 10
async def login(request: Request):
    # ...

# Or disable for testing
# Comment out @limiter.limit() decorators
```

### Problem: JWKS fetch failures

**Symptoms**: "Unable to find appropriate key" errors

**Causes**:
1. JWKS URL incorrect
2. Network connectivity to AWS
3. AWS Cognito outage

**Solutions**:
```bash
# 1. Verify JWKS URL
curl "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_XXXXXXXXX/.well-known/jwks.json"

# 2. Check from auth container
docker-compose exec auth curl "$COGNITO_JWKS_URL"

# 3. Check AWS service health
# Visit https://status.aws.amazon.com/
```

---

## API Reference

### Public Endpoints

#### `GET /`
Health check endpoint.

**Response**:
```json
{
  "status": "ok",
  "service": "auth"
}
```

#### `GET /api/auth/login`
Initiates OAuth login flow. Redirects to Cognito Hosted UI.

**Rate Limit**: 10 requests/minute per IP

**Response**: 302 Redirect to Cognito

#### `GET /api/auth/callback`
OAuth callback endpoint. Handles authorization code exchange.

**Query Parameters**:
- `code` (string): Authorization code from Cognito
- `state` (string): CSRF protection token

**Rate Limit**: 20 requests/minute per IP

**Response**: 302 Redirect to application homepage with cookies set

**Cookies Set**:
- `access_token`: JWT access token (1 hour TTL)
- `id_token`: JWT ID token with user claims (1 hour TTL)
- `refresh_token`: Refresh token (7 days TTL)

#### `GET /api/auth/logout`
Logs out user and clears cookies.

**Response**: 302 Redirect to Cognito logout, then back to application

**Cookies Cleared**: All authentication cookies

### Protected Endpoints

All protected endpoints require valid `access_token` cookie.

#### `GET /api/auth/me`
Returns current user information.

**Response**:
```json
{
  "user_id": "123e4567-e89b-12d3-a456-426614174000",
  "email": "user@example.com",
  "role": "user"
}
```

**Errors**:
- `401`: No access token or invalid token
- `403`: Token valid but user lacks permissions (if implemented)

#### `* /api/{service}/*`
Proxy endpoint for backend services.

**Supported Methods**: GET, POST, PUT, DELETE, PATCH

**Supported Services**:
- `/api/backend/*` → `BACKEND_SERVICE_URL`
- `/api/curator/*` → `CURATOR_SERVICE_URL`
- `/api/retriever/*` → `RETRIEVER_SERVICE_URL`

**Headers Added**:
- `X-User-Id`: User's unique identifier
- `X-User-Email`: User's email address
- `X-User-Role`: User's role (from Cognito custom attribute)

**Errors**:
- `401`: Invalid or expired access token
- `403`: Insufficient permissions
- `404`: Service not found
- `415`: Unsupported media type
- `503`: Backend service unavailable

---

## Additional Resources

### AWS Cognito Documentation
- [User Pools](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-identity-pools.html)
- [Hosted UI](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-app-integration.html)
- [JWT Tokens](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-with-identity-providers.html)

### Security Standards
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [OAuth 2.0 Security Best Practices](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-security-topics)
- [JWT Best Practices](https://datatracker.ietf.org/doc/html/rfc8725)

### Dependencies
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [python-jose](https://python-jose.readthedocs.io/)
- [Redis Documentation](https://redis.io/documentation)

---

## Support and Contributing

### Getting Help

1. Check this guide's [Troubleshooting](#troubleshooting) section
2. Review service logs: `docker-compose logs auth`
3. Check AWS Cognito console for user pool errors
4. Verify environment variables are correctly set

### Customization

This service is designed to be customized for your application:

1. **Service Routes**: Edit `services/proxy.py` to add/remove backend services
2. **Rate Limits**: Adjust in `auth.py` (`@limiter.limit()` decorators)
3. **Cookie Settings**: Modify in `auth.py` (cookie `max_age`, `samesite`, etc.)
4. **Token TTL**: Configured in AWS Cognito User Pool settings
5. **Logging**: Customize `utils/logger.py` for your logging infrastructure

### Contributing

When modifying this service:

1. **Run tests**: `make test`
2. **Check coverage**: `make coverage`
3. **Update documentation**: Keep this guide and README.md in sync
4. **Security review**: Consider security implications of changes

---

## License

This service is provided as-is for integration into your applications. Modify as needed for your use case.

---

## Quick Start Checklist

Use this checklist to integrate the service:

- [ ] Create AWS Cognito User Pool
- [ ] Create App Client with OAuth settings
- [ ] Configure callback URLs in Cognito
- [ ] Copy auth service to your project
- [ ] Create `.env` file with Cognito credentials
- [ ] Update `services/proxy.py` with your service routes
- [ ] Update `settings.py` with your service URL variables
- [ ] Set up Redis (Docker Compose or standalone)
- [ ] Add auth service to `docker-compose.yml`
- [ ] Configure Nginx/load balancer to route `/api/*` to auth service
- [ ] Update frontend to use `credentials: 'include'` in fetch requests
- [ ] Update backend services to read `X-User-*` headers
- [ ] Test login flow
- [ ] Test API requests
- [ ] Test logout
- [ ] Set up monitoring and logging
- [ ] Review security checklist
- [ ] Deploy to production with HTTPS

---

**That's it!** You now have a production-ready authentication gateway that handles all authentication concerns, allowing your application to focus on business logic.
