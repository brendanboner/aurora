# Aurora Teams Integration - Data Flow Documentation

**Document Version:** 1.0  
**Last Updated:** 2026-03-09  
**Classification:** Internal Use  
**Prepared For:** IT Security & Infrastructure Teams  

---

## Executive Summary

This document provides detailed data flow diagrams and descriptions for the Aurora Teams integration. It covers authentication flows, query processing pipelines, data ingestion, and all data movements within the system. This documentation is essential for security reviews, compliance audits, and understanding data residency.

---

## Table of Contents

1. [Authentication Data Flow](#1-authentication-data-flow)
2. [Query Processing Data Flow](#2-query-processing-data-flow)
3. [Content Ingestion Pipeline](#3-content-ingestion-pipeline)
4. [Teams Interface Data Flow](#4-teams-interface-data-flow)
5. [User Data Management](#5-user-data-management)
6. [External Service Integrations](#6-external-service-integrations)
7. [Data at Rest](#7-data-at-rest)
8. [Data Retention and Deletion](#8-data-retention-and-deletion)

---

## 1. Authentication Data Flow

### 1.1 Initial Login (OAuth 2.0 Flow)

```
┌──────────────┐                                                    ┌─────────────┐
│  User Opens  │                                                    │   AWS       │
│  /teams in   │                                                    │   Cognito   │
│  Browser     │                                                    │  User Pool  │
└──────┬───────┘                                                    └──────┬──────┘
       │                                                                   │
       │ 1. GET https://d23ew7gbss3vnh.cloudfront.net/teams               │
       │    (no auth cookie)                                               │
       ▼                                                                   │
┌────────────────────────────────────────────────────────┐                │
│              Nginx Reverse Proxy                       │                │
│  • Routes to static React build                        │                │
└──────┬─────────────────────────────────────────────────┘                │
       │                                                                   │
       │ 2. Return index.html (React app)                                 │
       ▼                                                                   │
┌────────────────────────────────────────────────────────┐                │
│           Browser loads React app                      │                │
│  • App initializes                                     │                │
│  • Checks for auth cookie                              │                │
│  • No cookie found → triggers login                    │                │
└──────┬─────────────────────────────────────────────────┘                │
       │                                                                   │
       │ 3. POST /api/auth/login                                          │
       │    (initiates OAuth flow)                                         │
       ▼                                                                   │
┌────────────────────────────────────────────────────────┐                │
│              Auth Gateway Service                      │                │
│  • Generates OAuth state (CSRF token)                  │                │
│  • Stores state in Redis (5 min TTL)                   │                │
│  • Constructs Cognito authorize URL                    │                │
└──────┬─────────────────────────────────────────────────┘                │
       │                                                                   │
       │ 4. Redirect to Cognito with parameters:                          │
       │    - client_id                                                    │
       │    - redirect_uri (our callback)                                 │
       │    - state (CSRF token)                                          │
       │    - scope (openid, email, profile)                              │
       │    - response_type=code                                          │
       ├──────────────────────────────────────────────────────────────────>│
       │                                                                   │
       │ 5. Display Cognito hosted UI login page                          │
       │<──────────────────────────────────────────────────────────────────┤
       │                                                                   │
       │ 6. User enters credentials:                                      │
       │    - Email: user@extremenetworks.com                             │
       │    - Password: ********                                          │
       ├──────────────────────────────────────────────────────────────────>│
       │                                                                   │
       │                                                                   │
       │    ┌────────────────────────────────────────────────────────┐    │
       │    │  Cognito validates credentials:                        │    │
       │    │  • Check email/password hash                           │    │
       │    │  • Verify email domain = @extremenetworks.com          │    │
       │    │  • Check account status (active/disabled)              │    │
       │    │  • Apply MFA if enabled                                │    │
       │    └────────────────────────────────────────────────────────┘    │
       │                                                                   │
       │ 7. Redirect back with authorization code:                        │
       │    https://d23ew7gbss3vnh.cloudfront.net/callback?               │
       │    code=AUTHORIZATION_CODE&state=CSRF_TOKEN                      │
       │<──────────────────────────────────────────────────────────────────┤
       │                                                                   │
       │ 8. GET /api/auth/callback?code=XXX&state=YYY                     │
       ▼                                                                   │
┌────────────────────────────────────────────────────────┐                │
│              Auth Gateway Service                      │                │
│                                                        │                │
│  Step 1: Validate state parameter                     │                │
│  • Retrieve state from Redis                          │                │
│  • Compare with received state                        │                │
│  • Delete state from Redis (single use)               │                │
│                                                        │                │
│  Step 2: Exchange code for tokens                     │                │
│  • POST to Cognito token endpoint                     │ ───────────────>│
│  • Send: client_id, code, redirect_uri                │                │
│                                                        │                │
│                                                        │ <───────────────┤
│  • Receive: access_token (JWT)                        │    Returns:    │
│             refresh_token                             │    {           │
│             id_token (JWT)                            │      "access_token": "eyJh...",
│             expires_in: 3600                          │      "refresh_token": "ey...",
│                                                        │      "id_token": "eyJhbGc...",
│  Step 3: Decode and validate JWT                      │      "expires_in": 3600    │
│  • Verify signature (Cognito public key)              │    }           │
│  • Check exp (expiration)                             │                │
│  • Check iss (issuer = Cognito)                       │                │
│  • Extract claims:                                    │                │
│    - sub (user ID)                                    │                │
│    - email (user@extremenetworks.com)                 │                │
│    - cognito:groups (roles)                           │                │
│                                                        │                │
│  Step 4: Create session                               │                │
│  • Store tokens in Redis                              │                │
│  • Generate session ID                                │                │
│  • Set HTTP-only cookies:                             │                │
│    - access_token (HttpOnly, Secure, SameSite=Lax)    │                │
│    - refresh_token (HttpOnly, Secure, SameSite=Strict)│                │
│    - session_id                                       │                │
│                                                        │                │
│  Step 5: Redirect to /teams                           │                │
│  • User now authenticated                             │                │
└──────┬─────────────────────────────────────────────────┘                │
       │                                                                   │
       │ 9. GET /teams (with cookies)                                     │
       │    Cookie: access_token=eyJh...; session_id=abc123               │
       ▼                                                                   │
┌────────────────────────────────────────────────────────┐                │
│              Auth Gateway Service                      │                │
│  • Extract access_token from cookie                    │                │
│  • Validate JWT signature                              │ ───────────────>│
│  • Check expiration                                    │                │
│  • Extract user context                                │ <───────────────┤
│  • User authenticated ✓                                │   JWT valid    │
│  • Serve React app                                     │                │
└────────────────────────────────────────────────────────┘                │
                                                                           │
```

**Data Exchanged:**
- **Sensitive:** User password (only to Cognito, never stored)
- **Confidential:** JWT tokens (short-lived, encrypted in transit)
- **Internal:** Session IDs, state tokens

**Data Storage:**
- **Redis:** OAuth state (5 min), session data (30 days max)
- **Cookies:** JWT tokens (HTTP-only, secure)
- **Not Stored:** Passwords (managed by Cognito)

---

### 1.2 Authenticated API Request

```
┌──────────────┐
│   Browser    │
│  (Teams UI)  │
└──────┬───────┘
       │
       │ 1. POST /api/oracle/query
       │    Cookie: access_token=eyJh...; session_id=abc123
       │    Body: {"question": "What is Wi-Fi 7?"}
       ▼
┌────────────────────────────────────────────────────────┐
│              Nginx Reverse Proxy                       │
│  • Rate limiting check (10 req/s)                      │
│  • Forward to auth gateway                             │
└──────┬─────────────────────────────────────────────────┘
       │
       │ 2. Proxied request
       ▼
┌────────────────────────────────────────────────────────┐                ┌─────────────┐
│              Auth Gateway Service                      │                │   AWS       │
│                                                        │                │   Cognito   │
│  Step 1: Extract token from cookie                    │                │             │
│  • Read access_token from Cookie header                │                │             │
│  • If missing → 401 Unauthorized                       │                │             │
│                                                        │                │             │
│  Step 2: Validate JWT                                  │                │             │
│  • Check signature against Cognito JWKS                │ ───────────────>│             │
│  • Verify expiration (exp claim)                       │   GET jwks.json│             │
│  • Verify issuer (iss claim)                           │                │             │
│  • Verify audience (aud claim)                         │ <───────────────┤             │
│                                                        │   Public keys  │             │
│  Step 3: Handle expired token                          │                │             │
│  • If expired, check refresh_token                     │                │             │
│  • Exchange refresh_token for new access_token         │ ───────────────>│             │
│  • Update cookie with new token                        │   POST /token  │             │
│  • Continue with new token                             │                │             │
│                                                        │ <───────────────┤             │
│  Step 4: Extract user context from JWT claims          │  New tokens    │             │
│  • user_id = sub claim                                 │                │             │
│  • email = email claim                                 │                │             │
│  • role = cognito:groups claim                         │                │             │
│                                                        │                │             │
│  Step 5: Add trusted headers                           │                └─────────────┘
│  • X-User-Id: 123e4567-e89b-12d3-a456-426614174000     │
│  • X-User-Email: user@extremenetworks.com              │
│  • X-User-Role: user                                   │
│                                                        │
│  Step 6: Proxy to backend service                      │
│  • Forward request to http://oracle:8003/query         │
│  • Include trusted headers                             │
│  • Remove Cookie header (not needed internally)        │
└──────┬─────────────────────────────────────────────────┘
       │
       │ 3. Proxied with headers:
       │    X-User-Id: 123e4567...
       │    X-User-Email: user@extremenetworks.com
       │    X-User-Role: user
       │    Body: {"question": "What is Wi-Fi 7?"}
       ▼
┌────────────────────────────────────────────────────────┐
│              Oracle Service (8003)                     │
│  • Reads X-User-* headers (trusts auth gateway)        │
│  • No authentication needed (already validated)        │
│  • Processes query...                                  │
│  • Returns response                                    │
└──────┬─────────────────────────────────────────────────┘
       │
       │ 4. Response: {"answer": "...", "sources": [...]}
       ▼
┌────────────────────────────────────────────────────────┐
│              Auth Gateway Service                      │
│  • Proxies response back to client                     │
│  • No modification needed                              │
└──────┬─────────────────────────────────────────────────┘
       │
       │ 5. Response returned to browser
       ▼
┌──────────────┐
│   Browser    │
│  (Teams UI)  │
└──────────────┘
```

**Security Guarantees:**
- JWT validated on **every** request
- Expired tokens automatically refreshed
- User context trusted by all internal services
- No external service can spoof user identity

---

## 2. Query Processing Data Flow

### 2.1 End-to-End Query Flow

```
┌─────────────┐
│ User Types: │
│ "What is    │
│  Wi-Fi 7?"  │
└──────┬──────┘
       │
       │ POST /api/oracle/query
       │ Body: {"question": "What is Wi-Fi 7?"}
       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Auth Gateway (8000)                           │
│  Data In:  {"question": "What is Wi-Fi 7?"}                     │
│  Data Out: Same + X-User-Id, X-User-Email, X-User-Role headers  │
└──────┬───────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Backend API (8001)                            │
│                                                                  │
│  Step 1: Load user preferences from PostgreSQL                  │
│  ┌────────────────────────────────────────────────────┐         │
│  │ SELECT preferred_topics, preferred_organizations,  │         │
│  │        preferred_people                            │         │
│  │ FROM user_preferences                              │         │
│  │ WHERE user_id = X-User-Id                          │         │
│  └────────────────────────────────────────────────────┘         │
│                                                                  │
│  Result: {                                                       │
│    "preferred_topics": ["Wi-Fi 6E", "Wi-Fi 7", "WPA3"],        │
│    "preferred_organizations": ["Wi-Fi Alliance"],               │
│    "preferred_people": []                                       │
│  }                                                               │
│                                                                  │
│  Step 2: Parse query for filters (via LLM)                      │
│  • Calls Oracle service: /parse_query                           │
│  • Extracts entities from question                              │
│                                                                  │
│  Step 3: Merge explicit filters + preferences                   │
│  • Explicit filters from question take precedence               │
│  • User preferences treated as relevance signals                │
│                                                                  │
│  Data forwarded to Oracle:                                      │
│  {                                                               │
│    "question": "What is Wi-Fi 7?",                              │
│    "user_context": {                                            │
│      "user_id": "123e4567...",                                  │
│      "email": "user@extremenetworks.com",                       │
│      "preferences": {                                           │
│        "topics": ["Wi-Fi 6E", "Wi-Fi 7", "WPA3"],              │
│        "organizations": ["Wi-Fi Alliance"],                     │
│        "people": []                                             │
│      }                                                           │
│    }                                                             │
│  }                                                               │
└──────┬───────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Oracle Service (8003)                         │
│                                                                  │
│  Step 1: Multi-Strategy Retrieval                               │
│  ┌──────────────────────────────────────────────────┐           │
│  │  Strategy A: Vector Search                        │           │
│  │  • Generate embedding for question                │◄──────────┼── Azure OpenAI
│  │  • Embeddings: [0.123, -0.456, 0.789, ...]       │           │   text-embedding-3-large
│  │  • Query Neo4j vector index                       │           │
│  │  • Find top 50 similar documents                  │           │
│  └──────────────────────────────────────────────────┘           │
│                                                                  │
│  ┌──────────────────────────────────────────────────┐           │
│  │  Strategy B: Keyword Search                       │           │
│  │  • Extract keywords: ["Wi-Fi", "7", "802.11be"]  │           │
│  │  • Full-text search on Resource.content           │           │
│  │  • Lucene/Cypher CONTAINS queries                 │           │
│  └──────────────────────────────────────────────────┘           │
│                                                                  │
│  ┌──────────────────────────────────────────────────┐           │
│  │  Strategy C: Graph Traversal                      │           │
│  │  • Find topics matching "Wi-Fi 7"                 │           │
│  │  • Traverse DISCUSSES relationships               │           │
│  │  • Traverse ENCOMPASSES (parent topics)           │           │
│  │  • Include PUBLISHED_BY organizations             │           │
│  └──────────────────────────────────────────────────┘           │
│                                                                  │
│  Neo4j Query Example:                                            │
│  ┌──────────────────────────────────────────────────┐           │
│  │ MATCH (r:Resource)-[:DISCUSSES]->(t:Topic)        │           │
│  │ WHERE t.name CONTAINS "Wi-Fi 7" OR                │           │
│  │       t.aliases CONTAINS "802.11be"               │           │
│  │ WITH r, t                                         │           │
│  │ MATCH (r)-[:PUBLISHED_BY]->(o:Organization)       │           │
│  │ OPTIONAL MATCH (r)-[:MENTIONS]->(p:Person)        │           │
│  │ RETURN r, t, o, collect(p) as authors             │           │
│  │ ORDER BY r.published_date DESC                    │           │
│  │ LIMIT 50                                          │           │
│  └──────────────────────────────────────────────────┘           │
│                          │                                       │
│                          ▼                                       │
│  Step 2: Score and Rank Results                                 │
│  ┌──────────────────────────────────────────────────┐           │
│  │  For each document:                               │           │
│  │                                                   │           │
│  │  Relevance Score (70%):                           │           │
│  │  • Topic match: 40%                               │           │
│  │    - Exact match: +10                             │           │
│  │    - Partial match: +5                            │           │
│  │    - In user preferences: +3                      │           │
│  │  • Organization match: 30%                        │           │
│  │    - In user preferences: +8                      │           │
│  │    - Authoritative source: +5                     │           │
│  │  • People match: 20%                              │           │
│  │    - In user preferences: +6                      │           │
│  │  • Relationship bonus: 10%                        │           │
│  │    - Connected to preferred topics: +3            │           │
│  │                                                   │           │
│  │  Recency Score (30%):                             │           │
│  │  • Published < 30 days: +10                       │           │
│  │  • Published < 90 days: +7                        │           │
│  │  • Published < 1 year: +4                         │           │
│  │  • Older: +1                                      │           │
│  │                                                   │           │
│  │  Final Score = (Relevance * 0.7) + (Recency * 0.3)│          │
│  └──────────────────────────────────────────────────┘           │
│                                                                  │
│  Results after ranking (top 10):                                │
│  [                                                               │
│    {                                                             │
│      "title": "Wi-Fi 7 Technical Overview",                     │
│      "content": "Wi-Fi 7 (802.11be)...",                        │
│      "url": "https://...",                                      │
│      "published_date": "2025-11-15",                            │
│      "organization": "Wi-Fi Alliance",                          │
│      "topics": ["Wi-Fi 7", "802.11be", "MLO"],                 │
│      "score": 9.2                                               │
│    },                                                            │
│    ...                                                           │
│  ]                                                               │
│                                                                  │
│  Step 3: Context Assembly                                       │
│  • Take top 5-10 documents                                      │
│  • Extract relevant snippets (2000 chars each)                  │
│  • Add metadata (titles, dates, authors, URLs)                  │
│  • Add graph context (related topics)                           │
│                                                                  │
│  Context sent to LLM:                                            │
│  ┌──────────────────────────────────────────────────┐           │
│  │ You are an AI assistant answering questions      │           │
│  │ about Wi-Fi technology.                          │           │
│  │                                                   │           │
│  │ Question: "What is Wi-Fi 7?"                     │           │
│  │                                                   │           │
│  │ Documents:                                        │           │
│  │ [Document 1] Title: Wi-Fi 7 Technical Overview   │           │
│  │ Published: 2025-11-15                            │           │
│  │ Source: Wi-Fi Alliance                           │           │
│  │ Content: Wi-Fi 7 is the next generation...      │           │
│  │                                                   │           │
│  │ [Document 2] Title: 802.11be Specification       │           │
│  │ ...                                              │           │
│  │                                                   │           │
│  │ Instructions:                                     │           │
│  │ - Answer based ONLY on provided documents        │           │
│  │ - Cite sources using [Document N] format         │           │
│  │ - If information not in documents, say so        │           │
│  │ - Do not hallucinate or add external knowledge   │           │
│  └──────────────────────────────────────────────────┘           │
│                          │                                       │
│                          ▼                                       │
│  Step 4: Generate Answer via LLM                                │
└──────┬───────────────────────────────────────────────────────────┘
       │
       │ POST https://api.openai.azure.com/openai/deployments/gpt-4o/chat/completions
       │ Body: {
       │   "messages": [{"role": "system", "content": "..."}, ...],
       │   "max_tokens": 1000,
       │   "temperature": 0.3
       │ }
       ▼
┌──────────────────────────────────────────────────────────────────┐
│                      Azure OpenAI API                            │
│  Model: gpt-4o                                                   │
│  Processing time: ~2-3 seconds                                   │
│                                                                  │
│  Response:                                                       │
│  {                                                               │
│    "choices": [{                                                 │
│      "message": {                                                │
│        "content": "Wi-Fi 7, also known as IEEE 802.11be,       │
│                   is the next generation of wireless            │
│                   technology [Document 1]. It introduces        │
│                   Multi-Link Operation (MLO) which allows       │
│                   devices to transmit on multiple bands         │
│                   simultaneously [Document 1, 2]. ..."          │
│      }                                                           │
│    }]                                                            │
│  }                                                               │
└──────┬───────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Oracle Service (8003)                         │
│                                                                  │
│  Step 5: Format Response                                         │
│  • Parse LLM response                                            │
│  • Extract citation markers [Document N]                         │
│  • Map citations to actual source URLs                           │
│  • Format as JSON                                                │
│                                                                  │
│  Final Response:                                                 │
│  {                                                               │
│    "answer": "Wi-Fi 7, also known as IEEE 802.11be, ...",      │
│    "sources": [                                                  │
│      {                                                           │
│        "title": "Wi-Fi 7 Technical Overview",                   │
│        "url": "https://www.wi-fi.org/discover-wi-fi/wi-fi-7",  │
│        "published_date": "2025-11-15",                          │
│        "organization": "Wi-Fi Alliance",                        │
│        "relevance_score": 9.2                                   │
│      },                                                          │
│      ...                                                         │
│    ],                                                            │
│    "related_topics": ["MLO", "Wi-Fi 6E", "QoS"],               │
│    "query_time_ms": 3247                                        │
│  }                                                               │
└──────┬───────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Backend API (8001)                            │
│                                                                  │
│  Step: Log Query Event                                           │
│  ┌────────────────────────────────────────────────────┐         │
│  │ INSERT INTO query_history                          │         │
│  │ (user_id, question, answer_preview, sources_count,│         │
│  │  query_time_ms, created_at)                       │         │
│  │ VALUES (?, ?, ?, ?, ?, NOW())                     │         │
│  └────────────────────────────────────────────────────┘         │
│                                                                  │
│  • Store in PostgreSQL for analytics                             │
│  • No full answer stored (preview only)                          │
│  • Source URLs stored for auditing                               │
└──────┬───────────────────────────────────────────────────────────┘
       │
       │ Response: {answer, sources, related_topics}
       ▼
┌──────────────┐
│   Browser    │
│  (Teams UI)  │
│              │
│  Display:    │
│  • Answer    │
│  • Citations │
│  • Feedback  │
│    buttons   │
└──────────────┘
```

**Data Exchanged:**
- **In:** User question (plain text)
- **Out:** Answer (markdown), source citations (URLs + metadata)
- **Stored:** Query event (PostgreSQL), user preferences (PostgreSQL)
- **Temporary:** Document embeddings (in-memory), LLM context (transient)

**External API Calls:**
1. **Azure OpenAI** (text-embedding-3-large): Embedding generation
2. **Azure OpenAI** (gpt-4o): Answer generation
3. **Neo4j**: Knowledge graph queries
4. **PostgreSQL**: User preferences, query logging

**Performance Metrics:**
- Embedding generation: ~200ms
- Neo4j query: ~100-500ms
- Azure OpenAI completion: ~2-3 seconds
- Total query time: ~3-5 seconds (p50)

---

## 3. Content Ingestion Pipeline

### 3.1 Web Scraping to Knowledge Graph

```
┌─────────────────────────────────────────────────────────────────┐
│                     Retriever Service (8004)                    │
│  Scheduled Task: Every 6 hours                                  │
│                                                                 │
│  Step 1: Scrape Wi-Fi Alliance websites                         │
│  • https://www.wi-fi.org/discover-wi-fi                        │
│  • https://www.wi-fi.org/news-events                           │
│  • https://www.wi-fi.org/certification                         │
│                                                                 │
│  Scraped Data:                                                  │
│  {                                                              │
│    "url": "https://www.wi-fi.org/discover-wi-fi/wi-fi-7",     │
│    "title": "Wi-Fi 7: The Next Generation",                   │
│    "content": "Wi-Fi 7 brings revolutionary features...",     │
│    "published_date": "2025-11-15T10:00:00Z",                  │
│    "author": "Wi-Fi Alliance",                                 │
│    "html_content": "<html>...</html>",                        │
│    "metadata": {                                               │
│      "content_type": "article",                               │
│      "word_count": 1500,                                      │
│      "images": ["https://..."],                               │
│      "links": ["https://..."]                                 │
│    }                                                            │
│  }                                                              │
│                                                                 │
│  Step 2: Clean and normalize content                            │
│  • Remove HTML tags                                             │
│  • Extract main content (remove ads, navigation)                │
│  • Normalize whitespace                                         │
│  • Detect language (English only)                               │
│                                                                 │
│  Step 3: Publish to RabbitMQ                                    │
└──────┬──────────────────────────────────────────────────────────┘
       │
       │ Publish Message
       ▼
┌─────────────────────────────────────────────────────────────────┐
│                  RabbitMQ Queue: scraped_content                │
│                                                                 │
│  Message:                                                       │
│  {                                                              │
│    "message_type": "resource",                                 │
│    "data": {                                                    │
│      "url": "https://www.wi-fi.org/discover-wi-fi/wi-fi-7",   │
│      "title": "Wi-Fi 7: The Next Generation",                 │
│      "content": "Cleaned content...",                          │
│      "published_date": "2025-11-15T10:00:00Z",                │
│      "source": "Wi-Fi Alliance",                               │
│      "metadata": {...}                                         │
│    },                                                           │
│    "timestamp": "2026-03-09T12:00:00Z"                         │
│  }                                                              │
│                                                                 │
│  Queue Properties:                                              │
│  • Durable: Yes (survives broker restart)                       │
│  • Max messages: 10,000                                         │
│  • TTL: 7 days (unprocessed messages expire)                    │
│  • Dead letter queue: scraped_content_dlq                       │
└──────┬──────────────────────────────────────────────────────────┘
       │
       │ Consume Message
       ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Digester Service (8005)                     │
│  Consumer: Processes messages async                             │
│                                                                 │
│  Step 1: Receive message from queue                             │
│  • Acknowledge message (prevents reprocessing)                  │
│  • Validate message structure                                   │
│  • Check for duplicates (by URL)                                │
│                                                                 │
│  Step 2: Extract entities via LLM                               │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ Prompt to Azure OpenAI (gpt-4o):                          │ │
│  │                                                           │ │
│  │ "Analyze this document and extract:                      │ │
│  │  1. Topics (technical concepts, standards)               │ │
│  │  2. Organizations (companies, standardization bodies)    │ │
│  │  3. People (authors, experts mentioned)                  │ │
│  │  4. Events (conferences, product launches)               │ │
│  │  5. Relationships between entities                       │ │
│  │                                                           │ │
│  │  Document:                                                │ │
│  │  Title: Wi-Fi 7: The Next Generation                     │ │
│  │  Content: Wi-Fi 7 brings revolutionary features...       │ │
│  │                                                           │ │
│  │  Return JSON format with entities and relationships."    │ │
│  └───────────────────────────────────────────────────────────┘ │
│                         │                                       │
│                         ▼                                       │
│  LLM Response:                                                  │
│  {                                                              │
│    "topics": [                                                  │
│      {"name": "Wi-Fi 7", "aliases": ["802.11be", "IEEE 802.11be"]},│
│      {"name": "Multi-Link Operation", "aliases": ["MLO"]},     │
│      {"name": "6 GHz spectrum", "aliases": []}                 │
│    ],                                                           │
│    "organizations": [                                           │
│      {"name": "Wi-Fi Alliance", "type": "standards_body"},     │
│      {"name": "IEEE", "type": "standards_body"}                │
│    ],                                                           │
│    "people": [],                                                │
│    "events": [],                                                │
│    "relationships": [                                           │
│      {"type": "ENCOMPASSES", "from": "Wi-Fi 7", "to": "MLO"}, │
│      {"type": "STANDARDIZED_BY", "from": "Wi-Fi 7", "to": "IEEE"}│
│    ]                                                            │
│  }                                                              │
│                                                                 │
│  Step 3: Generate embeddings                                    │
│  • Create embedding for document content                        │
│  • Model: text-embedding-3-large (3072 dimensions)             │
│  • Embedding: [0.123, -0.456, 0.789, ...]                      │
│                                                                 │
│  Step 4: Write to Neo4j                                         │
└──────┬──────────────────────────────────────────────────────────┘
       │
       │ Cypher Queries
       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Neo4j Knowledge Graph                        │
│                                                                 │
│  Transaction 1: Create/Update Resource Node                     │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ MERGE (r:Resource {url: $url})                            │ │
│  │ SET r.title = $title,                                     │ │
│  │     r.content = $content,                                 │ │
│  │     r.published_date = $published_date,                   │ │
│  │     r.embedding = $embedding,                             │ │
│  │     r.word_count = $word_count,                           │ │
│  │     r.last_updated = datetime()                           │ │
│  │ RETURN r                                                  │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
│  Transaction 2: Create Topic Nodes                              │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ UNWIND $topics AS topic                                   │ │
│  │ MERGE (t:Topic {name: topic.name})                        │ │
│  │ SET t.aliases = topic.aliases,                            │ │
│  │     t.last_seen = datetime()                              │ │
│  │ RETURN t                                                  │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
│  Transaction 3: Create Relationships                            │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ MATCH (r:Resource {url: $url})                            │ │
│  │ MATCH (t:Topic {name: $topic_name})                       │ │
│  │ MERGE (r)-[d:DISCUSSES]->(t)                              │ │
│  │ SET d.created_at = datetime()                             │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
│  Transaction 4: Create Vector Index (if not exists)            │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ CREATE VECTOR INDEX resource_embeddings IF NOT EXISTS     │ │
│  │ FOR (r:Resource)                                          │ │
│  │ ON (r.embedding)                                          │ │
│  │ OPTIONS {                                                 │ │
│  │   indexConfig: {                                          │ │
│  │     `vector.dimensions`: 3072,                            │ │
│  │     `vector.similarity_function`: 'cosine'                │ │
│  │   }                                                       │ │
│  │ }                                                         │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
│  Result: Knowledge graph updated with:                          │
│  • 1 Resource node                                              │
│  • 3 Topic nodes (Wi-Fi 7, MLO, 6 GHz)                         │
│  • 2 Organization nodes (Wi-Fi Alliance, IEEE)                  │
│  • 5 relationships (DISCUSSES, STANDARDIZED_BY, etc.)           │
└─────────────────────────────────────────────────────────────────┘
```

**Data Flow Summary:**
1. **Retriever** scrapes websites → RabbitMQ (message queue)
2. **RabbitMQ** buffers messages → Digester (async consumer)
3. **Digester** extracts entities (LLM) → Neo4j (graph database)
4. **Neo4j** stores knowledge graph → Available for queries

**Data Stored:**
- **RabbitMQ:** Temporary (7 day TTL), raw scraped content
- **Neo4j:** Permanent, structured knowledge graph
- **PostgreSQL:** Metadata (scrape jobs, processing stats)

**Processing Rate:**
- ~100-200 documents/hour (LLM bottleneck)
- Retry logic: Failed messages → dead letter queue
- Deduplication: By URL (prevents duplicate processing)

---

## 4. Teams Interface Data Flow

### 4.1 Teams Tab Initialization

```
User Opens Teams → Navigates to Aurora Tab
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│  Microsoft Teams loads iframe:                          │
│  https://d23ew7gbss3vnh.cloudfront.net/teams           │
└──────┬──────────────────────────────────────────────────┘
       │
       │ 1. GET /teams
       ▼
┌─────────────────────────────────────────────────────────┐
│                    CloudFront CDN                       │
│  • Caches static assets (JS, CSS, images)               │
│  • Serves from edge location (low latency)              │
└──────┬──────────────────────────────────────────────────┘
       │
       │ 2. Forward to origin
       ▼
┌─────────────────────────────────────────────────────────┐
│                    Nginx (EC2)                          │
│  • Rewrite /teams → /index.html                         │
│  • Serve React SPA                                      │
└──────┬──────────────────────────────────────────────────┘
       │
       │ 3. Return index.html + static assets
       ▼
┌─────────────────────────────────────────────────────────┐
│              Browser (Teams iframe)                      │
│                                                         │
│  React App Loads:                                        │
│  • TeamsTab.jsx                                         │
│  • Initialize Teams SDK (teamsSdk.js)                   │
│  • Check authentication status                           │
│  • Load chat history (local storage)                    │
│  • Fetch feed data                                      │
└──────┬──────────────────────────────────────────────────┘
       │
       │ 4. Parallel API calls:
       │
       ├─────────────────────────────────────────────────────┐
       │                                                     │
       │ 4a. GET /api/content_creator_service/feed           │
       │                                                     │
       ▼                                                     ▼
┌──────────────────────────┐             ┌──────────────────────────┐
│  Content Creator (8002)  │             │  Auth Check (8000)       │
│  • Returns AI posts      │             │  • Validate JWT          │
│  • Max 20 posts          │             │  • If no token, redirect │
│  • Sort by created_at    │             │    to login              │
└──────┬───────────────────┘             └──────────────────────────┘
       │
       │ Response:
       │ [
       │   {
       │     "agent_name": "Wi-Fi Expert",
       │     "title": "Wi-Fi 7 Updates",
       │     "body": "Latest developments in Wi-Fi 7...",
       │     "created_at": "2026-03-08T15:00:00Z",
       │     "like_count": 5,
       │     "comment_count": 2
       │   },
       │   ...
       │ ]
       ▼
┌─────────────────────────────────────────────────────────┐
│              Browser (Teams iframe)                      │
│                                                         │
│  Display:                                                │
│  ┌─────────────────┬──────────────────────────────────┐│
│  │   Chat Panel    │        Feed Panel                ││
│  │   (Left)        │        (Right)                   ││
│  │                 │                                  ││
│  │  • Input field  │  • Post 1 (unread badge)         ││
│  │  • Send button  │  • Post 2                        ││
│  │                 │  • Post 3                        ││
│  └─────────────────┴──────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

---

### 4.2 User Submits Chat Message

```
User types: "Explain WPA3 security"
       │
       │ Click Send
       ▼
┌─────────────────────────────────────────────────────────┐
│              Browser (Teams iframe)                      │
│  • Disable input (loading state)                         │
│  • Show typing indicator                                │
│  • Add user message to UI immediately                    │
└──────┬──────────────────────────────────────────────────┘
       │
       │ POST /api/oracle/query
       │ Body: {"question": "Explain WPA3 security"}
       │ Headers: Cookie (auth tokens)
       ▼
┌─────────────────────────────────────────────────────────┐
│                Auth Gateway (8000)                       │
│  • Validate JWT                                          │
│  • Add X-User-* headers                                  │
│  • Proxy to oracle:8003                                  │
└──────┬──────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│                Oracle Service (8003)                     │
│  • Process query (see section 2.1)                       │
│  • Query time: ~3-5 seconds                              │
└──────┬──────────────────────────────────────────────────┘
       │
       │ Response:
       │ {
       │   "answer": "WPA3 is the latest Wi-Fi security protocol...",
       │   "sources": [
       │     {"title": "...", "url": "...", "published_date": "..."},
       │     ...
       │   ],
       │   "related_topics": ["WPA2", "Encryption", "Security"],
       │   "query_time_ms": 3247
       │ }
       ▼
┌─────────────────────────────────────────────────────────┐
│              Browser (Teams iframe)                      │
│  • Parse markdown in answer                              │
│  • Render citations as clickable links                   │
│  • Display related topics as chips                       │
│  • Enable input (ready for next question)                │
│  • Store message in local storage (persistence)          │
│                                                         │
│  UI Update:                                              │
│  ┌─────────────────────────────────────────────────────┐│
│  │ User: Explain WPA3 security                         ││
│  │                                                     ││
│  │ Assistant: WPA3 is the latest Wi-Fi security       ││
│  │ protocol that replaces WPA2...                     ││
│  │                                                     ││
│  │ Sources:                                            ││
│  │ • WPA3 Specification (Wi-Fi Alliance)               ││
│  │ • Security Enhancements in WPA3 (IEEE)              ││
│  │                                                     ││
│  │ Related: [WPA2] [Encryption] [Security]            ││
│  │                                                     ││
│  │ 👍 👎 (Feedback buttons)                            ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

**Data Stored:**
- **Local Storage (Browser):** Chat history (up to 50 messages)
- **PostgreSQL:** Query event (user_id, question, timestamp)
- **Not Stored:** Full answer text (only preview for analytics)

---

## 5. User Data Management

### 5.1 What Data We Collect

**User Account Data (AWS Cognito):**
- Email address (verified, @extremenetworks.com)
- User ID (UUID, generated by Cognito)
- Account status (active/disabled)
- Last login timestamp
- MFA preferences (if enabled)

**User Preferences (PostgreSQL):**
```sql
Table: user_preferences
Columns:
  - user_id (UUID, foreign key to Cognito)
  - preferred_topics (JSON array)
  - preferred_organizations (JSON array)
  - preferred_people (JSON array)
  - notification_settings (JSON object)
  - created_at (timestamp)
  - updated_at (timestamp)
```

**Query History (PostgreSQL):**
```sql
Table: query_history
Columns:
  - id (UUID, primary key)
  - user_id (UUID, foreign key)
  - question (text)
  - answer_preview (text, first 200 chars)
  - sources_count (integer)
  - query_time_ms (integer)
  - created_at (timestamp)
```

**Feedback Data (PostgreSQL):**
```sql
Table: feedback
Columns:
  - id (UUID, primary key)
  - user_id (UUID, foreign key)
  - query_id (UUID, foreign key to query_history)
  - rating (integer, 1-5 or thumbs up/down)
  - comment (text, optional)
  - created_at (timestamp)
```

**Session Data (Redis):**
- Session ID → User ID mapping
- OAuth state tokens (5 min TTL)
- Rate limiting counters (1 hour TTL)

---

### 5.2 Data We Do NOT Collect

❌ **No tracking cookies** (only authentication cookies)
❌ **No IP address logging** (beyond standard web server logs)
❌ **No browser fingerprinting**
❌ **No third-party analytics** (Google Analytics, etc.)
❌ **No personal information** beyond email
❌ **No payment information** (system is free)
❌ **No location data**
❌ **No usage across other sites** (no cross-domain tracking)

---

## 6. External Service Integrations

### 6.1 Azure OpenAI API

**Data Sent:**
- User questions (plain text)
- Document content (from knowledge graph)
- System prompts (instructions)

**Data Received:**
- Generated answers (markdown text)
- Embeddings (vector arrays)
- API usage metadata (token counts)

**Data Retention (Azure):**
- Per Azure OpenAI policy: **30 days** (then deleted)
- No data used for model training (per enterprise agreement)

**API Endpoint:**
```
POST https://<your-resource>.openai.azure.com/openai/deployments/<deployment>/chat/completions
```

**Authentication:**
- API key (stored in environment variables)
- Rotated quarterly

---

### 6.2 AWS Cognito

**Data Sent:**
- OAuth authorization requests
- Token refresh requests
- User email (during registration by OCTO team)

**Data Received:**
- JWT tokens (access + refresh + ID)
- User attributes (email, user ID, groups)

**Data Retention (Cognito):**
- User accounts: Indefinite (until manually deleted)
- Tokens: Per expiration (1 hour access, 30 days refresh)

---

### 6.3 CloudFront CDN

**Data Sent:**
- Static assets (JS, CSS, images)
- HTML files

**Data Received:**
- HTTP requests from users

**Logs:**
- CloudFront access logs (optional, disabled by default)
- Standard fields: timestamp, client IP, request path, status code

---

## 7. Data at Rest

### 7.1 Database Locations

**PostgreSQL:**
- **Location:** EC2 instance (Docker volume)
- **Encryption:** EBS volume encryption (optional)
- **Backups:** Daily automated backups (pg_dump)
- **Retention:** 30 days

**Neo4j:**
- **Location:** EC2 instance (Docker volume)
- **Encryption:** EBS volume encryption (optional)
- **Backups:** Weekly graph snapshots
- **Retention:** 30 days

**Redis:**
- **Location:** EC2 instance (Docker volume)
- **Encryption:** None (ephemeral data, short TTL)
- **Backups:** None (cache can be rebuilt)

---

### 7.2 Data Backup and Recovery

**Backup Schedule:**
- PostgreSQL: Daily at 02:00 UTC
- Neo4j: Weekly on Sunday at 03:00 UTC
- Configuration: Git repository (version controlled)

**Backup Storage:**
- Location: S3 bucket (same AWS region)
- Encryption: AES-256 (S3 managed keys)
- Retention: 30 days (automatic deletion)

**Recovery Process:**
1. Provision new EC2 instance (or restore existing)
2. Restore Docker volumes from S3 backups
3. Start services via Docker Compose
4. Verify data integrity (spot checks)
5. Update CloudFront origin (if new EC2)

**RTO/RPO:**
- Recovery Time Objective (RTO): < 4 hours
- Recovery Point Objective (RPO): < 24 hours

---

## 8. Data Retention and Deletion

### 8.1 Retention Periods

| Data Type | Retention Period | Deletion Method |
|-----------|------------------|-----------------|
| User accounts | Until manual deletion | OCTO team deletes from Cognito |
| User preferences | Until account deletion | CASCADE delete on user_id |
| Query history | 90 days | Automated job (runs daily) |
| Feedback | 1 year | Automated job (runs weekly) |
| Session data (Redis) | 30 days | TTL expiration (automatic) |
| OAuth state tokens | 5 minutes | TTL expiration (automatic) |
| Web server logs | 30 days | Log rotation (automatic) |
| Database backups | 30 days | S3 lifecycle policy |

---

### 8.2 User Data Deletion (GDPR Right to Erasure)

**Process:**
1. User requests deletion via OCTO team
2. OCTO team verifies user identity
3. OCTO team executes deletion script:

```sql
-- PostgreSQL deletion
BEGIN;
DELETE FROM feedback WHERE user_id = $user_id;
DELETE FROM query_history WHERE user_id = $user_id;
DELETE FROM user_preferences WHERE user_id = $user_id;
COMMIT;
```

4. OCTO team disables user in AWS Cognito:
```bash
aws cognito-idp admin-disable-user \
  --user-pool-id $USER_POOL_ID \
  --username $email
```

5. After 30-day grace period, permanently delete from Cognito:
```bash
aws cognito-idp admin-delete-user \
  --user-pool-id $USER_POOL_ID \
  --username $email
```

**Timeline:**
- Immediate: User account disabled (cannot log in)
- Within 24 hours: PostgreSQL data deleted
- After 30 days: Cognito account permanently deleted
- After 30 days: Backup data expired (automatic)

---

## 9. Data Flow Security Summary

### 9.1 Data Classification

| Classification | Examples | Protection Measures |
|----------------|----------|---------------------|
| **Public** | Published Wi-Fi Alliance specs | None (already public) |
| **Internal** | User preferences, query history | Access control, network isolation |
| **Confidential** | Email addresses, JWT tokens | Encryption in transit, secure cookies |
| **Secrets** | API keys, database passwords | Environment variables, never in code |

---

### 9.2 Data Protection Checklist

**In Transit:**
- [x] HTTPS/TLS 1.2+ for all client communication
- [x] CloudFront with SSL/TLS termination
- [x] Secure cookies (HTTP-only, Secure flag)
- [x] Internal services use HTTP (isolated network)

**At Rest:**
- [x] Database credentials in environment variables
- [x] Optional EBS encryption for volumes
- [x] S3 backup encryption (AES-256)
- [x] No passwords stored (managed by Cognito)

**In Use:**
- [x] JWT validation on every request
- [x] Network isolation (Docker bridge network)
- [x] Rate limiting (prevents abuse)
- [x] Input validation (prevents injection)

---

## 10. Compliance Summary

### 10.1 Data Residency

**Primary Data Location:** AWS us-east-1 (or configured region)

**Data Flows:**
- User data: AWS Cognito (us-east-1) → EC2 (us-east-1)
- LLM processing: Azure OpenAI (configured region, typically East US)
- CDN caching: CloudFront global edge locations

**Cross-Border Transfers:**
- CloudFront serves from edge locations worldwide
- Azure OpenAI API calls may cross borders (depends on deployment)
- Knowledge graph data stays in EC2 instance (single region)

---

### 10.2 Regulatory Considerations

**GDPR (if applicable):**
- ✅ Right to access: User can export query history
- ✅ Right to erasure: Deletion process documented (see 8.2)
- ✅ Right to portability: JSON export available
- ✅ Data minimization: Only email + preferences stored
- ✅ Purpose limitation: Data used only for service functionality

**CCPA (if applicable):**
- ✅ Notice at collection: Privacy policy required
- ✅ Right to delete: Same process as GDPR
- ✅ Right to know: User can request data report
- ✅ Do not sell: No data selling (not applicable)

**SOC 2 (if required):**
- Access controls: JWT-based authentication
- Monitoring: OpenTelemetry logging and metrics
- Incident response: Documented procedures
- Change management: Git-based version control

---

**Document Control:**
- **Review Frequency:** Quarterly or after system changes
- **Next Review Date:** 2026-06-09
- **Document Owner:** OCTO Team
- **Approval Required:** IT Security Team
- **Related Documents:** SECURITY_OVERVIEW.md, ARCHITECTURE_DIAGRAM.md

