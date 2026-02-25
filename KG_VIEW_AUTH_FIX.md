# KG-View Authentication Fix

## Problem Summary

The kg-view service was deployed without authentication integration, bypassing the auth gateway pattern used by all other Aurora services. This caused:

1. **Unauthenticated API access** - `/api/visualisation/*` endpoints were publicly accessible
2. **CloudFront redirect issues** - The frontend at `/visualisation` likely redirected to home due to missing authentication
3. **Inconsistent architecture** - All other services route through the auth gateway, but kg-view had special nginx bypass rules

## Solution Implemented

Integrated kg-view into Aurora's authentication architecture by routing all `/api/visualisation/*` requests through the auth gateway.

### Changes Made

#### 1. Auth Service Configuration
- **File**: `auth/settings.py`
  - Added `kg_view_backend_url` setting
  
- **File**: `auth/services/proxy.py`
  - Added `/api/visualisation` route to `SERVICE_ROUTES` mapping
  - Now proxies kg-view requests with user context headers (`X-User-Id`, `X-User-Email`, `X-User-Role`)

#### 2. Nginx Configuration (All 3 configs)
- **Files**: `nginx/nginx.cloudfront.conf`, `nginx/nginx.letsencrypt.conf`, `nginx/nginx.hotreload.conf`
  - **Removed** special `/api/visualisation/` location blocks that bypassed auth
  - All `/api/*` requests now route through auth service (including `/api/visualisation/*`)
  - Increased timeouts for kg-view graph queries (120s vs 60s)

#### 3. KG-View Backend
- **File**: `kg_view/backend/main.py`
  - Added `common.auth_middleware` import for `get_user_context`
  - Updated health endpoint to accept optional user context
  - Backend now receives authenticated user info from auth gateway

#### 4. Environment Configuration
- **Files**: `.env.dev`, `prod-deployment/.env.prod`, `.env`
  - Added `KG_VIEW_BACKEND_URL=http://kg-view-backend:8002`

## Deployment Instructions

### Local Development Testing

1. **Rebuild and restart affected services:**
   ```bash
   cd /Users/bbonner/code/octo/octo-rapid-aurora
   docker compose up -d --build auth nginx kg-view-backend
   ```

2. **Test authentication flow:**
   ```bash
   # Test that /api/visualisation requires auth
   curl -v http://localhost/api/visualisation/health
   # Should redirect to login or return 401
   
   # After logging in, test with cookies
   curl -v -b cookies.txt http://localhost/api/visualisation/health
   # Should return: {"status":"healthy","service":"kg-visualizer-api","user":"your@email.com"}
   ```

3. **Test the visualisation frontend:**
   - Navigate to http://localhost/visualisation
   - Should redirect to login if not authenticated
   - After login, should display the knowledge graph visualizer

### Production Deployment

1. **Update production .env file on EC2:**
   ```bash
   # SSH to EC2
   ssh -i ~/.ssh/your-key.pem ec2-user@your-ec2-instance
   
   # Navigate to deployment directory
   cd /path/to/aurora/prod-deployment
   
   # Edit .env and verify KG_VIEW_BACKEND_URL exists
   grep KG_VIEW_BACKEND_URL .env
   # Should show: KG_VIEW_BACKEND_URL=http://kg-view-backend:8002
   
   # If missing, add it after ORACLE_SERVICE_URL
   nano .env
   ```

2. **Build and push new images to ECR:**
   ```bash
   # From your local development machine
   cd /Users/bbonner/code/octo/octo-rapid-aurora
   
   # Login to AWS ECR
   make aws-login
   
   # Build and push auth service
   cd auth && make ship
   
   # Build and push kg-view services
   cd ../kg_view && make ship-backend && make ship-frontend
   
   # Or ship everything at once
   cd .. && make ship-all
   ```

3. **Deploy on EC2:**
   ```bash
   # SSH to EC2
   ssh -i ~/.ssh/your-key.pem ec2-user@your-ec2-instance
   
   # Navigate to deployment directory
   cd /path/to/aurora/prod-deployment
   
   # Pull latest images and restart
   make deploy
   
   # Or manually:
   docker compose -f docker-compose.prod.yml pull auth nginx kg-view-backend kg-view-frontend
   docker compose -f docker-compose.prod.yml up -d --force-recreate auth nginx kg-view-backend kg-view-frontend
   ```

4. **Verify deployment:**
   ```bash
   # Check service logs
   docker compose -f docker-compose.prod.yml logs -f auth kg-view-backend
   
   # Test the endpoint (should require authentication)
   curl -v https://d23ew7gbss3vnh.cloudfront.net/api/visualisation/health
   
   # Access the frontend
   # Navigate to: https://d23ew7gbss3vnh.cloudfront.net/visualisation
   # Should redirect to Cognito login if not authenticated
   ```

## Architecture Flow (After Fix)

### Before (Broken - Bypassed Auth)
```
Browser → CloudFront → nginx → kg-view-backend (NO AUTH!)
          /visualisation/         /api/visualisation/
```

### After (Fixed - Authenticated)
```
Browser → CloudFront → nginx → auth → kg-view-backend ✓
          /visualisation/    /api/visualisation/
                             (validates JWT,
                              adds user headers)
```

## Authentication Details

### Request Flow
1. User accesses `/visualisation` frontend
2. Frontend makes API calls to `/api/visualisation/*`
3. Nginx routes to auth service
4. Auth service validates Cognito JWT from cookie
5. Auth service adds headers: `X-User-Id`, `X-User-Email`, `X-User-Role`
6. Auth service proxies to `http://kg-view-backend:8002/*`
7. kg-view backend receives authenticated request with user context

### User Context in KG-View
The backend can now access user information:
```python
@app.get("/api/graph/stats")
async def get_graph_stats(user: Optional[dict] = Depends(get_user_context)):
    if user:
        # User is authenticated
        logger.info(f"User {user['email']} requested graph stats")
    else:
        # Service-to-service call (no user context)
        logger.info("System requested graph stats")
```

## Rollback (If Needed)

If issues occur, you can temporarily rollback by reverting the nginx configs:

```bash
# On EC2
cd /path/to/aurora/prod-deployment
git checkout HEAD~1 nginx/nginx.cloudfront.conf
docker compose -f docker-compose.prod.yml restart nginx
```

However, this will **revert to the insecure configuration** (no authentication). Not recommended for production.

## Testing Checklist

- [ ] Local dev: `/visualisation` loads without errors
- [ ] Local dev: `/api/visualisation/health` requires authentication
- [ ] Local dev: After login, visualizer displays graph data
- [ ] Production: CloudFront URL redirects to Cognito login
- [ ] Production: After login, `/visualisation` displays correctly
- [ ] Production: API endpoints return user context in responses
- [ ] No nginx errors in logs
- [ ] Auth service logs show kg-view proxy requests

## Common Issues & Solutions

### Issue: "Service not found" error
**Cause**: Auth service can't find kg-view in SERVICE_ROUTES
**Solution**: Verify `KG_VIEW_BACKEND_URL` is set in `.env` and auth service is restarted

### Issue: 502 Bad Gateway
**Cause**: Auth service can't reach kg-view-backend
**Solution**: Check `kg-view-backend` service is running: `docker compose ps kg-view-backend`

### Issue: Still redirects to home page
**Cause**: Frontend routing issue or cookies not set
**Solution**: 
1. Clear browser cookies and cache
2. Check nginx logs: `docker compose logs nginx | grep visualisation`
3. Verify CloudFront isn't caching redirects (invalidate cache)

### Issue: Authentication loop (redirects repeatedly)
**Cause**: Cookie domain mismatch
**Solution**: Verify `DEPLOYMENT_DOMAIN` in `.env` matches CloudFront URL exactly

## Files Changed
- `auth/settings.py` - Added kg_view_backend_url
- `auth/services/proxy.py` - Added /api/visualisation route
- `nginx/nginx.cloudfront.conf` - Removed bypass route
- `nginx/nginx.letsencrypt.conf` - Removed bypass route  
- `nginx/nginx.hotreload.conf` - Removed bypass route
- `kg_view/backend/main.py` - Added auth middleware
- `kg_view/Dockerfile.backend` - Added common directory copy
- `docker-compose.yml` - Added KG_VIEW_BACKEND_URL to auth service
- `prod-deployment/docker-compose.prod.yml` - Added KG_VIEW_BACKEND_URL to auth service
- `prod-deployment/docker-compose.build.yml` - Added KG_VIEW_BACKEND_URL to auth service
- `.env.dev` - Added KG_VIEW_BACKEND_URL
- `prod-deployment/.env.prod` - Added KG_VIEW_BACKEND_URL
- `.env` - Added KG_VIEW_BACKEND_URL

## Verification

### Local Development
✅ Tested: `/api/visualisation/health` now returns 401 Unauthorized without authentication
✅ Services healthy: auth, kg-view-backend, nginx
✅ Authentication flow: Requests route through auth gateway → kg-view-backend

## Security Improvement

**Before**: Knowledge graph was publicly accessible without any authentication
**After**: Knowledge graph requires Cognito authentication, consistent with Aurora security model

All kg-view API endpoints now have user context and can implement role-based access control if needed.
