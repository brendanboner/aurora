# Microsoft Teams Tab Integration: Architecture & Design

## Executive Summary

Aurora integrates into Microsoft Teams as a personal static tab (`/teams` route) combining Chat and Feed pages into a single Teams-native interface. Users authenticate via AWS Cognito (unchanged), and real-time feed updates push automatically into the chat via Server-Sent Events (SSE), triggering Teams-style toast notifications.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    TEAMS DESKTOP / WEB                          │
│  (teams.microsoft.com - Hosts the iframe)                        │
└────────────────────────┬────────────────────────────────────────┘
                         │ iframe src=
                         │ https://d23ew7gbss3vnh.cloudfront.net/teams
                         │ (production)
                         ↓
        ┌────────────────────────────────┐
        │   AURORA FRONTEND (React SPA)   │
        │  http://localhost:3000/teams    │ (dev)
        │  https://cloudfront.../teams    │ (prod)
        │                                 │
        ├─────────────────────────────────┤
        │ Components:                     │
        │ • TeamsTab.tsx                  │
        │ • Chat Section                  │
        │ • Feed Section                  │
        │ • Toast Notifications           │
        │ • Teams SDK Wrapper             │
        └────────┬──────────┬──────────┬──┘
                 │          │          │
        ┌────────▼─┐ ┌──────▼───┐    │
        │ Cognito  │ │ Auth Svc  │    │ (withCredentials: true)
        │ Login    │ │ Gateway   │    │ (SameSite=None cookies)
        │          │ │           │    │
        └──────────┘ └────┬──────┘    │
                         │            │
              ┌──────────▼────────────▼────┐
              │  NGINX REVERSE PROXY       │
              │  http://localhost/api/     │
              └──────────┬─────────────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
    ┌────▼────┐     ┌────▼────┐    ┌────▼────┐
    │ Backend  │     │ Content  │    │   Feed  │
    │ Chat API │     │ Creator  │    │  Stream │
    │          │     │ Service  │    │  (SSE)  │
    └─────────┘     └──────────┘    └────┘
         │                │              │
    ┌────▼──────────────────▼──────────────┐
    │  PostgreSQL + Neo4j + RabbitMQ       │
    │  (Chat history, User data, KB)       │
    └──────────────────────────────────────┘
```

---

## Client-Side Architecture

### File Structure
```
/frontend/src/
├── pages/
│   └── TeamsTab.tsx                    # Main Teams tab (Chat + Feed combined)
│       └── Combines Chatbot + SocialFeed functionality
│
├── components/
│   └── TeamsNotification.tsx           # Toast notification system
│       └── useToasts hook + Toast component
│
├── services/
│   ├── eventBus.ts                     # SSE event listener & processor
│   │   ├── connects to /api/feed/stream
│   │   ├── feed_update → auto-inject chat message
│   │   └── triggers toasts
│   └── api/client.js                   # Axios client (unchanged)
│       └── withCredentials: true
│
├── teams/
│   └── teamsSdk.ts                     # Teams SDK wrapper
│       ├── initializeTeamsSDK()
│       ├── getTeamsContext()
│       └── notifyTeamsSuccess()
│
└── App.js                              # Updated routing
    ├── Route /teams → TeamsTab
    └── Toast container on all routes
```

### Data Flow: User Sends Chat Message

```
User types "What is the knowledge graph?" in Chat input
↓
onClick sendMessage()
↓
POST /api/chat/query {query: "..."}
↓
Auth Service → Backend Chat API
↓
Backend processes with RAG pipeline
↓
Returns: {response: "...", sources: [...], relatedTopics: [...]}
↓
TeamsTab.tsx receives response
↓
Adds message to messages[] state
↓
UI re-renders: new assistant message appears
↓
messagesEndRef scrolls to bottom
```

### Data Flow: Feed Update Triggers Notification

```
Backend: Creator Agent posts new content
↓
Feed Service stores post in database
↓
[Future: RabbitMQ publishes feed.update event]
↓
SSE stream: /api/feed/stream detects update
↓
Sends: event: feed_update, data: {id, author, content, ...}
↓
EventBus.onFeedUpdate() triggered
↓
eventBus.handleFeedUpdate():
  1. Converts to chat message: "📰 Author posted: ..."
  2. Injects into chat: eventBus.addChatMessage()
  3. Emits toast: eventBus.emitNotification()
↓
TeamsTab.tsx receives:
  - New message in chat
  - New notification via useEffect hook
↓
Toast renders in top-right
Chat message appears in messages list
Unread badge increments in Feed section
```

---

## Server-Side Architecture

### Authentication & CORS

**Auth Service** (`/auth`)
```
POST /api/auth/callback
  ↓ [Cognito redirects here]
  ├─ Validates Cognito JWT
  ├─ Creates httpOnly cookies (SameSite=None; Secure)
  ├─ Syncs user to backend
  └─ Redirects to /

CORS Headers Added:
  Allow-Origins: 
    - https://teams.microsoft.com
    - https://teams.microsoft.us
    - https://d23ew7gbss3vnh.cloudfront.net
  Allow-Credentials: true
  
Cookie Settings:
  access_token: SameSite=None; Secure; HttpOnly; Max-Age=3600
  id_token: SameSite=None; Secure; HttpOnly; Max-Age=3600
  refresh_token: SameSite=None; Secure; HttpOnly; Max-Age=432000
```

**Why SameSite=None?**
- Teams tab loads in iframe: `teams.microsoft.com` → `d23ew7gbss3vnh.cloudfront.net`
- Cross-site by definition
- SameSite=None allows cookies in cross-site iframe
- Secure=True ensures HTTPS only (prevents MITM)
- HttpOnly prevents JavaScript access (XSS protection)

---

### Backend API Endpoints

#### 1. Chat Query Endpoint (Existing)
```
POST /api/chat/query
  Headers: X-User-Id, X-User-Email, X-User-Role (added by auth service)
  Body: {query: string, conversationId?: string}
  Response: {response: string, sources: [], relatedTopics: []}
```

**Integration**: Used by Chat section to send messages and get responses.

---

#### 2. Chat History Endpoint (Existing)
```
GET /api/chat/history?limit=50&offset=0
  Response: {messages: [{id, type, content, author, timestamp, ...}]}
```

**Integration**: Loads chat history on tab initialization.

---

#### 3. Feed Timeline Endpoint (New)
```
GET /api/feed/timeline?limit=20&offset=0
  Response: {
    items: [{
      id: "post-123",
      author: "Creator Name",
      authorId: "user-456",
      content: "Post content...",
      timestamp: "2024-01-15T10:30:00Z",
      likes: 42,
      comments: 5,
      liked: false
    }],
    total: 156,
    hasMore: true
  }
```

**Implementation Location**: `/backend/src/routes/feed.py`

**Integration**: Loads initial feed items on tab initialization.

---

#### 4. Feed Stream Endpoint (New - SSE)
```
GET /api/feed/stream
  Headers: withCredentials: true (sends cookies)
  
Streams Server-Sent Events:

event: connected
data: {"timestamp": "2024-01-15T10:30:00Z"}

event: heartbeat
data: {}

event: feed_update
data: {
  "id": "post-123",
  "type": "new_post",
  "content": "...",
  "author": "Creator Name",
  "authorId": "user-456",
  "timestamp": "2024-01-15T10:30:00Z",
  "metadata": {}
}

event: error
data: {"error": "Connection lost"}
```

**Implementation**: `/backend/src/routes/feed.py` - `stream_feed()`

**Client Usage**:
```javascript
const eventSource = new EventSource('/api/feed/stream', {
  withCredentials: true
});

eventSource.addEventListener('feed_update', (event) => {
  const data = JSON.parse(event.data);
  // EventBus processes and converts to chat message + toast
});
```

**Behavior**:
- Connects on TeamsTab mount
- Listens for feed_update events
- Auto-injects chat messages
- Triggers toast notifications
- Reconnects on disconnect (exponential backoff)
- Sends heartbeat every 5 seconds to keep alive

---

## Real-Time Architecture: Server-Sent Events (SSE) vs Alternatives

### Why SSE?

| Feature | SSE | WebSocket | Polling |
|---------|-----|-----------|---------|
| Setup Complexity | Low | Medium | Low |
| Browser Support | 99%+ | 99%+ | 100% |
| Firewall/Proxy Friendly | Yes (HTTP GET) | No (needs upgrade) | Yes (HTTP GET) |
| Message Direction | Server→Client | Bidirectional | Client→Server→Client |
| Iframe Compatible | Yes | Requires special config | Yes |
| Connection Overhead | Low | Medium | High |
| Latency | <100ms | <50ms | 3-5s |

**Chosen**: SSE because:
1. Works in iframes without special config
2. Simple unidirectional (server sends updates)
3. No firewall/proxy issues
4. Lower overhead than polling
5. Good enough latency for notifications

---

## Security Model

### Authentication Flow

```
┌─────────────────┐
│ User (Teams)    │
└────────┬────────┘
         │ 1. User not logged in
         ├──────────────────────────────────┐
         │                                  │
         ↓                                  │
    ┌────────────────┐                     │
    │ /teams route   │                     │
    │ ProtectedRoute │                     │
    │ (checks auth)  │                     │
    └────────┬───────┘                     │
             │ 2. No auth cookie              │
             ├─────────────────────────────┐  │
             │                             │  │
             ↓                             ↓  │
    ┌─────────────────┐         ┌──────────────┐
    │ Redirect to     │         │ /api/auth/   │
    │ /api/auth/login │────────→│ login        │
    └─────────────────┘         └────────┬─────┘
                                         │
                                    3. Cognito
                                    OAuth Flow
                                         │
                       ┌─────────────────┴──────────────┐
                       │                                │
                       ↓                                ↓
                    ┌──────────────┐          ┌─────────────────┐
                    │ Cognito      │          │ User enters     │
                    │ Hosted UI    │          │ credentials     │
                    └──────────────┘          └─────────────────┘
                                                      │
                                   4. Cognito issues tokens
                                                      │
                       ┌──────────────────────────────┴─────┐
                       │                                    │
                       ↓                                    ↓
    ┌──────────────────────────────┐      ┌────────────────────────┐
    │ /api/auth/callback           │      │ Auth Service           │
    │ code=... → exchange for JWT  │      │ - Validates JWT        │
    │                              │      │ - Syncs user to backend│
    │                              │      │ - Sets httpOnly cookie │
    └──────────────────────────────┘      └────────────────────────┘
                       │                                    │
                       └────────────────┬───────────────────┘
                                        │
                       5. Redirect to frontend with cookie
                                        │
                       ┌────────────────┴────────────────┐
                       │                                 │
                       ↓                                 ↓
    ┌────────────────────────────┐  ┌──────────────────────────────┐
    │ Browser stores cookie      │  │ /teams route loads           │
    │ access_token (httpOnly)    │  │ ProtectedRoute checks auth   │
    │ id_token (httpOnly)        │  │ Auth found → renders TeamsTab│
    │ refresh_token (httpOnly)   │  │                              │
    └────────────────────────────┘  └──────────────────────────────┘
```

### API Call Security

```
Client sends request:
  GET /api/chat/history

Browser automatically includes:
  Cookie: access_token=...; id_token=...; refresh_token=...
  Header: X-Requested-With: XMLHttpRequest

Auth Service middleware validates:
  1. access_token exists and not expired
  2. If expired, uses refresh_token to get new one
  3. Extracts user_id, email, role from JWT claims
  4. Adds headers: X-User-Id, X-User-Email, X-User-Role
  5. Proxies request to backend with user context

Backend receives request:
  GET /api/chat/history
  Headers: X-User-Id, X-User-Email, X-User-Role
  
  @require_user_context decorator:
    ✓ Validates X-User-Id header exists
    ✓ Queries database to ensure user still exists
    ✓ Injects user_context into function
  
  Executes query with user context
  Returns only data user is authorized to see
```

### Teams iframe Cookie Handling

**Problem**: Teams tab runs in iframe (`teams.microsoft.com` → `cloudfront.net`)

**Solution**: SameSite=None; Secure
```
Set-Cookie: access_token=...; SameSite=None; Secure; HttpOnly
Set-Cookie: id_token=...; SameSite=None; Secure; HttpOnly
Set-Cookie: refresh_token=...; SameSite=None; Secure; HttpOnly
```

**Browser Behavior**:
- SameSite=None: Allows cross-site cookies in iframe
- Secure: Only sent over HTTPS (production)
- HttpOnly: JavaScript cannot access (XSS protection)

**Localhost Note**: 
For local testing (`http://localhost:3000`), set `USE_HTTPS=false` in auth service to allow insecure cookies.

---

## Teams Integration Points

### 1. Manifest Configuration

**File**: `/frontend/public/manifest.json`

```json
{
  "staticTabs": [
    {
      "entityId": "aurora-chat-feed",
      "name": "Chat & Feed",
      "contentUrl": "https://d23ew7gbss3vnh.cloudfront.net/teams",
      "websiteUrl": "https://d23ew7gbss3vnh.cloudfront.net/teams",
      "scopes": ["personal"],
      "context": ["personalTab"]
    }
  ],
  "validDomains": [
    "d23ew7gbss3vnh.cloudfront.net",
    "localhost",
    "localhost:3000"
  ]
}
```

**What it means**:
- **contentUrl**: Where Teams loads the tab iframe
- **websiteUrl**: Where Teams opens when user clicks "view in browser"
- **validDomains**: Domains Teams SDK can communicate with
- **scopes: ["personal"]**: Tab appears in user's personal tabs
- **context: ["personalTab"]**: Tab is a personal static tab

### 2. Teams SDK Initialization

**File**: `/frontend/src/teams/teamsSdk.ts`

```javascript
// Initialize Teams SDK and get context
await initializeTeamsSDK()

// Returns:
{
  isTeams: true,
  userId: "...",           // Teams user object ID
  tenantId: "...",         // Teams tenant ID
  channelId: "...",        // If in channel context
  groupId: "...",          // If in group context
  teamId: "...",           // Teams team ID
  initialized: true
}
```

**Used for**:
- Detecting if running in Teams (vs standalone)
- Getting Teams context (for future analytics, etc.)
- Calling Teams SDK APIs (notifySuccess, etc.)

### 3. Context Availability

| Context | Available | Usage |
|---------|-----------|-------|
| User ID | ✅ | Not used (use Cognito user_id instead) |
| Team ID | ✅ | Optional: could silo data by team |
| Tenant ID | ✅ | Optional: future org-scoped features |
| Chat/Channel ID | ❌ | Not available for personal tabs |

**Design Decision**: Use Cognito `user_id` as primary auth. Teams context is supplementary.

---

## Deployment Architecture

### Local Development

```
http://localhost:3000/teams
  ↓ (React dev server)
http://localhost:8000/api/...
  ↓ (nginx proxy)
├─ http://localhost:8001 (auth service)
├─ http://localhost:8002 (backend)
└─ http://localhost:8003 (content creator)
```

**Setup**: `docker-compose up` starts all services

---

### Production

```
https://d23ew7gbss3vnh.cloudfront.net/teams
  ↓ (CloudFront CDN)
https://api.example.com/
  ↓ (nginx reverse proxy on K8s / ECS)
├─ auth:8000
├─ backend:8000
└─ content-creator:8000
```

**Changes needed**:
1. Update manifest.json: `contentUrl = https://d23ew7gbss3vnh.cloudfront.net/teams`
2. Ensure backend `/api/feed/*` endpoints deployed
3. Auth service CORS already supports production domain
4. Deploy updated frontend to CloudFront

**Environment Variables**: 
- Frontend: Handled via nginx config / CloudFront origin
- Backend: No changes (endpoints are generic)
- Auth: `DEPLOYMENT_DOMAIN=d23ew7gbss3vnh.cloudfront.net` should already be set

---

## Monitoring & Logging

### What to Monitor

| Metric | Tool | What to Watch |
|--------|------|---------------|
| SSE Connections | Backend logs | `[SSE] User X connected/disconnected` |
| Feed Updates | App logs | New posts streaming to users |
| Auth Failures | Auth logs | 401 errors, cookie issues |
| Chat Latency | Application Insights | Response time > 2s |
| Toast Delivery | Browser console | Toast appears within 1s of event |

### Logs to Check

**Frontend** (npm start output):
```
[TeamsTab] Teams SDK initialized
[EventBus] Connected to SSE stream
[EventBus] Reconnecting in Xms
```

**Backend** (`docker logs aurora-backend`):
```
[SSE] User abc123 connected to feed stream
[SSE] User abc123 idle timeout, closing connection
[SSE] User abc123 disconnected
```

**Auth Service** (`docker logs aurora-auth`):
```
User sync: /api/internal/sync-user
Token validation success/failure
Cookie set: SameSite=None; Secure
```

---

## Scalability Considerations

### Current SSE Implementation Limitations

**Polling-based SSE** (current):
- Polls every 5 seconds for new items
- Works for <10k concurrent users
- No message queue

**Production Scale (future improvement)**:

Replace polling with message queue:
```
Creator Agent posts
  ↓
RabbitMQ: feed.update event published
  ↓
Backend SSE listener subscribes to feed.update
  ↓
Real-time delivery to all connected clients
```

**Benefits**:
- Sub-second latency
- No polling overhead
- True real-time updates

**Implementation**: Update `/backend/src/routes/feed.py` `get_new_feed_items()` to listen to RabbitMQ instead of polling.

---

## Troubleshooting Reference

| Problem | Diagnosis | Solution |
|---------|-----------|----------|
| Tab blank forever | Check browser console | /teams route not found, auth failed |
| No chat response | Test `/api/chat/query` | Backend unreachable, auth cookie missing |
| Toasts not appearing | Check eventBus logs | SSE not connected, feed endpoint failing |
| Cookies not sent | DevTools Network tab | withCredentials not set, CORS issue |
| "Connection Lost" toast | Check backend SSE logs | Max idle timeout, connection dropped |

---

## File Modification Summary

### New Files Created
1. `/frontend/src/teams/teamsSdk.ts` - Teams SDK wrapper
2. `/frontend/src/services/eventBus.ts` - SSE event bus
3. `/frontend/src/components/TeamsNotification.tsx` - Toast component
4. `/frontend/src/components/TeamsNotification.css` - Toast styles
5. `/frontend/src/pages/TeamsTab.tsx` - Main tab component
6. `/frontend/src/pages/TeamsTab.css` - Tab styles
7. `/backend/src/routes/feed.py` - SSE + timeline endpoints
8. `/frontend/public/manifest.json` - Teams manifest (updated)
9. `TEAMS_INTEGRATION_CHECKLIST.md` - Deployment guide

### Modified Files
1. `/frontend/src/App.js` - Added /teams route and toast container
2. `/auth/auth.py` - Updated CORS and cookie settings
3. `/backend/src/api.py` - Registered feed routes

---

## Summary

**Teams Tab Integration** provides a unified Chat + Feed experience inside Microsoft Teams using:

- **Frontend**: React SPA at `/teams` with Teams SDK integration
- **Real-time**: Server-Sent Events (SSE) for feed updates
- **Notifications**: Teams-style toast alerts
- **Auth**: AWS Cognito (unchanged) with iframe-safe cookies
- **Backend**: New `/api/feed/*` endpoints for timeline and streaming

All changes are **backwards compatible** — existing `/` (main app) still works unchanged. Deployment requires only environment variable updates (manifest domain); no code changes needed for production.
