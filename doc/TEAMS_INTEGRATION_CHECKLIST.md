# Teams Tab Integration: Complete Execution Checklist

## Overview
This checklist guides you through deploying Aurora as a Microsoft Teams Tab, combining Chat + Feed in a unified interface. The tab runs at `/teams` with Cognito authentication, real-time feed updates via Server-Sent Events, and Teams-native toast notifications.

**Total estimated time: 45 minutes (local setup) + deployment time**

---

## PART 1: LOCAL DEVELOPMENT SETUP (25 minutes)

### Step 1.1: Verify Frontend Dependencies
```bash
cd /Users/bbonner/code/octo/octo-rapid-aurora/frontend

# Check Node version (v16+ required)
node --version
npm --version

# Install/update packages if needed
npm install
```

**Expected output**: `npm notice` with no errors

---

### Step 1.2: Start Frontend Development Server
```bash
cd /Users/bbonner/code/octo/octo-rapid-aurora/frontend

# Start React dev server on http://localhost:3000
npm start
```

**Expected output**:
```
Compiled successfully!

You can now view aurora-frontend in the browser.

  Local:            http://localhost:3000
  On Your Network:  http://YOUR_IP:3000
```

**Test locally**: 
- Open http://localhost:3000 in browser
- You should be redirected to Cognito login (or already logged in)
- After login, you should see the Chat page

---

### Step 1.3: Verify Backend is Running
```bash
# Check if backend is accessible (should return 200)
curl http://localhost:8000/health
```

**Expected**: `{"status":"ok"}`

---

### Step 1.4: Test Teams Tab Route
```bash
# Open in browser
open http://localhost:3000/teams
# or
curl -b "access_token=..." http://localhost:3000/teams
```

**Expected**: Teams Tab loads with Chat + Feed side-by-side (if already logged in)

---

## PART 2: TEAMS MANIFEST SETUP (2 minutes)

### How Manifest Works (Docker-Ready)

The Teams manifest is **dynamically generated** by the React frontend at runtime. This means:
- ✅ Single Docker image works for localhost, CloudFront, or any domain
- ✅ No static files, no environment-specific configuration
- ✅ URLs (contentUrl, validDomains) auto-correct based on current deployment
- ✅ No file zipping or manual package creation needed

**How it works:**
1. React app loads `/manifest.json` endpoint (served by `/frontend/src/App.js`)
2. Endpoint detects current host and protocol from `window.location`
3. Returns fully configured manifest JSON with correct URLs
4. Teams reads the manifest and loads the tab

**No steps needed here** - manifest generation is built into the app.
See `/doc/TEAMS_DEPLOYMENT_GUIDE.md` for detailed architecture explanation.

---

## PART 3: LOCAL TESTING WITH TEAMS (5 minutes)

### Quick Start: Sideload in Teams

**Using Teams Toolkit (Recommended for Development):**

1. **Install Teams Toolkit in VS Code**
   - Open Extensions (Cmd+Shift+X)
   - Search "Teams Toolkit"
   - Install by Microsoft

2. **Sideload the Aurora Tab**
   - Press Cmd+Shift+P and select "Teams: Open Developer Portal"
   - Or manually: Open Teams Desktop → Apps → Upload a custom app
   - When prompted for manifest, use: `http://localhost:3000/manifest.json`
   - Click "Add" to install

3. **Expected Result**
   - Aurora tab appears in your Teams workspace
   - Chat + Feed interface loads side-by-side
   - Connection status shows "Real-time updates"

---

### Alternative: Manual Sideload via Direct URL

If Teams Toolkit isn't available:

1. Open Teams Desktop
2. Click Apps (bottom left)
3. Click "Upload a custom app"
4. Select "Provide a link instead"
5. Paste: `http://localhost:3000/manifest.json`
6. Click "Add"

**Why this works:**
- The `/manifest.json` endpoint is served by the React app
- It returns a fully configured manifest with the correct URLs
- No file download, no zipping, no icon management needed

---

## PART 4: TESTING IN TEAMS (10 minutes)

### Test 4.1: Tab Loads Correctly
- [ ] Tab opens without errors
- [ ] Chat input form visible
- [ ] Feed section visible on right
- [ ] Connection status indicator shows "Real-time updates" or "Using polling mode"

### Test 4.2: Authentication
- [ ] Already logged in (Cognito session cookie)
- [ ] If not logged in, redirected to Cognito login
- [ ] After login, tab loads

### Test 4.3: Chat Functionality
1. Type a message in chat input: "What is the knowledge graph?"
2. Click Send
3. **Expected**: 
   - Message appears in chat with "You" as author
   - Backend responds with an answer
   - Assistant message appears below

### Test 4.4: Feed Loading
1. Refresh the page
2. **Expected**:
   - Feed items appear in right panel
   - Each item shows author, content, likes, comments

### Test 4.5: Real-time Updates (Manual Test)
1. In another browser tab, navigate to `http://localhost:3000/feed`
2. Make a request to trigger a feed update (or wait for Creator Agent to post)
3. **Expected**:
   - Toast notification appears in top-right of Teams tab
   - New system message auto-injected into Chat
   - Unread badge increments in Feed section header

### Test 4.6: Teams Native Feel
- [ ] Sidebar removed (full-screen Teams tab)
- [ ] Navigation clean and minimal
- [ ] Toast notifications match Teams' design
- [ ] Font and colors match Teams' theme

---

## PART 5: PRODUCTION DEPLOYMENT (5 minutes)

The manifest is **automatically configured** for any deployment environment. No configuration changes needed.

### How It Works in Production

**Manifest generation is automatic:**
- When deployed to production domain (e.g., `https://aurora.company.com`)
- React app still serves `/manifest.json` endpoint
- Endpoint reads `window.location.host` and `window.location.protocol`
- Returns manifest with `contentUrl` and `validDomains` automatically set to production domain
- Teams reads it and everything works

### Deployment Steps

1. **Build and Deploy Frontend**
   ```bash
   cd /Users/bbonner/code/octo/octo-rapid-aurora/frontend
   npm run build
   # Deploy ./build/ to your production infrastructure
   # (CloudFront, container registry, etc.)
   ```

2. **Deploy Backend Changes**
   ```bash
   cd /Users/bbonner/code/octo/octo-rapid-aurora/backend
   # Build and deploy your backend with the new feed routes
   docker build -t aurora-backend:latest .
   # Push to registry and redeploy
   ```

3. **Verify Manifest Endpoint**
   ```bash
   # After deployment, test manifest generation
   curl https://aurora.company.com/manifest.json
   
   # Expected: JSON with contentUrl and validDomains
   # pointing to https://aurora.company.com
   ```

4. **Sideload in Teams**
   - Open Teams
   - Apps → Upload a custom app
   - When prompted, paste: `https://aurora.company.com/manifest.json`
   - Click "Add"

**That's it!** No file changes, no zipping, no environment-specific configurations needed.

---

## PART 6: VERIFICATION CHECKLIST

### Final Verification
- [ ] Local `/teams` route works at http://localhost:3000/teams
- [ ] Chat messages sent and received
- [ ] Feed items load and display
- [ ] Real-time updates trigger notifications
- [ ] SSE connection status indicator shows correct state
- [ ] Production domain in manifest matches CloudFront
- [ ] Production manifest is downloadable
- [ ] Teams tab sideloads without errors
- [ ] No console errors in Teams iframe
- [ ] Cognito authentication persists in iframe
- [ ] Cookies sent with withCredentials: true in API calls

---

## PART 7: TROUBLESHOOTING

### Issue: "Connection Failed to Load Manifest"
**Solution**: Ensure manifest.json is in the correct directory and accessible:
```bash
# For production, verify path
curl -I https://d23ew7gbss3vnh.cloudfront.net/manifest.json
# Should return 200 OK

# For local, verify frontend is running
curl -I http://localhost:3000/manifest.json
```

---

### Issue: "Tab Shows Blank/Loading Forever"
**Cause**: /teams route not found or authentication failed

**Solution**:
```bash
# Check frontend route registration
grep -n "path.*teams" /Users/bbonner/code/octo/octo-rapid-aurora/frontend/src/App.js

# Check browser console for errors (F12 in Teams)
# Verify Cognito session exists:
curl -b "access_token=..." http://localhost:3000/teams
```

---

### Issue: "Cookies Not Sent to Backend"
**Cause**: withCredentials not set or SameSite cookies issue

**Solution**: Already handled:
- ✅ apiClient.js has `withCredentials: true`
- ✅ Auth service has `SameSite=None; Secure`
- ✅ HTTPS enforced in production

**Verify**:
```bash
# Check Network tab in DevTools (F12)
# API requests should include:
# Cookie: access_token=...; id_token=...; refresh_token=...
```

---

### Issue: "Real-time Updates Not Working (No Toast)"
**Cause**: SSE endpoint failing or event bus not initialized

**Solution**:
```bash
# Test SSE endpoint directly
curl -N http://localhost:8000/api/feed/stream \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Cookie: access_token=..." \
  --http2

# Should return: event: connected followed by heartbeat events

# Check backend logs
docker logs aurora-backend | grep SSE
```

---

### Issue: "Connection Failed to Load Manifest"
**Cause**: `/manifest.json` endpoint not responding or React app not running

**Solution**:
```bash
# Verify React app is running
curl http://localhost:3000/manifest.json

# Expected: Valid JSON with contentUrl, validDomains, etc.
# If 404 or connection refused, restart frontend:
cd /frontend && npm start

# Check that /frontend/src/App.js includes the getTeamsManifest() function
grep -n "getTeamsManifest" /Users/bbonner/code/octo/octo-rapid-aurora/frontend/src/App.js
```

---

### Issue: "Manifest Has Wrong Domain/Protocol"
**Cause**: Manifest generated with incorrect host

**Solution**:
```bash
# The manifest auto-detects from window.location
# Test with curl to see what it generates:
curl http://localhost:3000/manifest.json | jq .

# Should show:
# - contentUrl: "http://localhost:3000/teams"
# - validDomains: ["localhost", ...]

# For production, verify:
curl https://your-domain.com/manifest.json | jq .

# Should show:
# - contentUrl: "https://your-domain.com/teams"
# - validDomains: ["your-domain.com", ...]
```

---

## PART 8: PRODUCTION DEPLOYMENT CHECKLIST

Before deploying to production:

### Pre-Deployment
- [ ] All local tests pass
- [ ] No console errors in Teams tab
- [ ] Chat queries respond correctly
- [ ] Feed items load
- [ ] Real-time notifications work
- [ ] Backend SSE endpoint tested
- [ ] Auth cookies SameSite=None verified
- [ ] HTTPS enforced on production domain

### Deployment Steps
1. [ ] Merge code to main branch
2. [ ] Build frontend: `npm run build`
3. [ ] Deploy frontend to production domain (CloudFront, etc.)
4. [ ] Deploy backend with new feed routes
5. [ ] Verify `/manifest.json` endpoint responds with correct domain
6. [ ] Test production manifest loads: `curl https://your-domain.com/manifest.json`
7. [ ] Sideload production manifest in Teams
8. [ ] Verify chat, feed, and notifications work
9. [ ] Monitor logs for errors

### Post-Deployment
- [ ] Production tab loads without errors
- [ ] Real-time updates flowing
- [ ] Team members can install and use
- [ ] No 401/403 auth errors
- [ ] SSE connections stable

---

## REFERENCE: FILE LOCATIONS

```
/frontend/src/
├── pages/
│   └── TeamsTab.tsx              # Main Teams tab component
├── components/
│   └── TeamsNotification.tsx      # Toast notifications
├── services/
│   └── eventBus.ts               # SSE event handling
├── teams/
│   └── teamsSdk.ts               # Teams SDK wrapper
└── App.js                         # /teams route + manifest.json endpoint

/backend/src/routes/
└── feed.py                        # GET /api/feed/stream (SSE) and /api/feed/timeline

/auth/
└── auth.py                        # CORS and SameSite=None cookie support

/doc/
├── TEAMS_INTEGRATION_CHECKLIST.md (this file)
├── TEAMS_DEPLOYMENT_GUIDE.md      # Architecture explanation
├── TEAMS_README.md                # Master index
└── TEAMS_*.md                     # Other integration guides

Note: /public/manifest.json NO LONGER EXISTS
- Manifest is now dynamically generated by React app at /manifest.json endpoint
- No static files, no environment-specific configuration
```

---

## SUCCESS CRITERIA

You're done when:

1. **Local Testing**
   - [ ] `npm start` runs without errors
   - [ ] http://localhost:3000/teams loads Chat + Feed
   - [ ] Chat works (send message, get response)
   - [ ] Feed loads items
   - [ ] Toasts appear on feed updates

2. **Teams Integration**
   - [ ] Manifest.json downloads from `/manifest.json`
   - [ ] App sideloads in Teams without errors
   - [ ] Tab renders at `/teams` route
   - [ ] All features work inside Teams iframe

3. **Production**
   - [ ] Production domain in manifest
   - [ ] Frontend deployed to CloudFront
   - [ ] Backend serving `/api/feed/*` endpoints
   - [ ] Teams sideload works with production manifest

---

## NEXT STEPS IF STUCK

1. Check browser console (F12) for errors
2. Check backend logs: `docker logs aurora-backend`
3. Check frontend console: `npm start` terminal
4. Verify Cognito tokens exist: `curl -b "access_token=..." http://localhost:3000/auth/me`
5. Test SSE manually: `curl -N http://localhost:8000/api/feed/stream`
6. Review troubleshooting section above
7. Check Teams activity logs (Settings → Logs)

---

**Questions?** This checklist is self-contained and requires zero decision-making. Follow linearly; if something fails, consult troubleshooting.
