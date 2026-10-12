# Aurora Teams Integration - Architecture Diagram

**Document Version:** 1.0  
**Last Updated:** 2026-03-09  
**Classification:** Internal Use  
**Prepared For:** IT Infrastructure Teams  

---

## System Architecture Overview

Aurora is a microservices-based AI knowledge management platform with a Teams interface. This document provides detailed architecture diagrams showing component interactions, network topology, and data flows.

---

## 1. High-Level System Architecture

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                               Internet Users                                  │
│                   (Extreme Networks employees with @extremenetworks.com)      │
└──────────────────────────────────┬────────────────────────────────────────────┘
                                   │
                                   │ HTTPS (443)
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         AWS CloudFront CDN                                    │
│                  https://d23ew7gbss3vnh.cloudfront.net                       │
│                                                                               │
│  Features:                                                                    │
│  • SSL/TLS Termination (AWS Certificate Manager)                             │
│  • Global Edge Locations                                                     │
│  • DDoS Protection (AWS Shield)                                              │
│  • Caching (static assets)                                                   │
│  • WAF Ready                                                                 │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   │ HTTPS (443) → HTTP (80)
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          EC2 Instance (VPC)                                   │
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                         Nginx Reverse Proxy                             │ │
│  │                            (Port 80)                                    │ │
│  │                                                                         │ │
│  │  Routes:                                                                │ │
│  │  • /teams         → Static React files                                 │ │
│  │  • /api/*         → Auth Gateway (port 8000)                           │ │
│  │  • /visualisation → KG View Frontend (port 5173)                       │ │
│  │  • /*             → Static React files (SPA fallback)                  │ │
│  │                                                                         │ │
│  │  Security:                                                              │ │
│  │  • Rate limiting (10 req/s API, 30 req/s general)                      │ │
│  │  • Security headers (X-Frame-Options, CSP, etc.)                       │ │
│  │  • Gzip compression                                                    │ │
│  └────────────────────────────┬────────────────────────────────────────────┘ │
│                               │                                              │
│  ┌────────────────────────────▼────────────────────────────────────────────┐ │
│  │                     Auth Gateway Service                                │ │
│  │                       (FastAPI, Port 8000)                              │ │
│  │                                                                         │ │
│  │  Responsibilities:                                                      │ │
│  │  • OAuth 2.0 flow with AWS Cognito                                     │ │
│  │  • JWT token validation                                                │ │
│  │  • Session management (HTTP-only cookies)                              │ │
│  │  • Request proxying to internal services                               │ │
│  │  • User context injection (X-User-Id, X-User-Email, X-User-Role)       │ │
│  │  • CSRF protection                                                     │ │
│  └────────────────────────────┬────────────────────────────────────────────┘ │
│                               │                                              │
│                               │ Docker Bridge Network (aurora-network)       │
│                               │ (Private - no external access)               │
│                               │                                              │
│  ┌────────────────────────────┴────────────────────────────────────────────┐ │
│  │                      Application Services Layer                         │ │
│  │                                                                         │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │ │
│  │  │  Backend API (FastAPI, Port 8001)                               │   │ │
│  │  │  • User preferences                                             │   │ │
│  │  │  • Query orchestration                                          │   │ │
│  │  │  • Feedback collection                                          │   │ │
│  │  └─────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                         │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │ │
│  │  │  Oracle Service (FastAPI, Port 8003)                            │   │ │
│  │  │  • AI-powered Q&A                                               │   │ │
│  │  │  • Multi-strategy retrieval (graph + vector + keyword)          │   │ │
│  │  │  • Azure OpenAI integration                                     │   │ │
│  │  │  • Context assembly and ranking                                 │   │ │
│  │  └─────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                         │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │ │
│  │  │  Content Creator Service (FastAPI, Port 8002)                   │   │ │
│  │  │  • AI agent personas                                            │   │ │
│  │  │  • Social media post generation                                 │   │ │
│  │  │  • Feed API for Teams interface                                 │   │ │
│  │  └─────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                         │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │ │
│  │  │  Retriever Service (FastAPI, Port 8004)                         │   │ │
│  │  │  • Web scraping (Wi-Fi Alliance sites)                          │   │ │
│  │  │  • Content extraction                                           │   │ │
│  │  │  • RabbitMQ publishing                                          │   │ │
│  │  └─────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                         │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │ │
│  │  │  Digester Service (FastAPI, Port 8005)                          │   │ │
│  │  │  • RabbitMQ consumer                                            │   │ │
│  │  │  • Entity extraction (LLM-powered)                              │   │ │
│  │  │  • Neo4j graph population                                       │   │ │
│  │  └─────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                         │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │ │
│  │  │  Curator Service (FastAPI, Port 8006)                           │   │ │
│  │  │  • Graph post-processing                                        │   │ │
│  │  │  • Topic hierarchy organization                                 │   │ │
│  │  │  • Deduplication                                                │   │ │
│  │  └─────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                         │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │ │
│  │  │  KG View Frontend (Vite/React, Port 5173)                       │   │ │
│  │  │  • Interactive graph visualization                              │   │ │
│  │  │  • Neo4j graph exploration                                      │   │ │
│  │  └─────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                         │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │ │
│  │  │  Teams Agent (Node.js, Port 8007)                               │   │ │
│  │  │  • Microsoft Teams bot integration (future)                     │   │ │
│  │  └─────────────────────────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                     Data Layer (Internal Only)                       │  │
│  │                                                                      │  │
│  │  ┌──────────────────────┐  ┌──────────────────────┐                │  │
│  │  │  PostgreSQL (5432)   │  │  Neo4j (7474, 7687)  │                │  │
│  │  │  • Users             │  │  • Knowledge Graph   │                │  │
│  │  │  • Preferences       │  │  • Vector indexes    │                │  │
│  │  │  • Query history     │  │  • Graph algorithms  │                │  │
│  │  │  • Feedback          │  │                      │                │  │
│  │  └──────────────────────┘  └──────────────────────┘                │  │
│  │                                                                      │  │
│  │  ┌──────────────────────┐  ┌──────────────────────┐                │  │
│  │  │  RabbitMQ (5672)     │  │  Redis (6379)        │                │  │
│  │  │  • Message queue     │  │  • Caching           │                │  │
│  │  │  • Async processing  │  │  • Rate limiting     │                │  │
│  │  │  • Retry logic       │  │  • Monitoring        │                │  │
│  │  └──────────────────────┘  └──────────────────────┘                │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                  Observability Stack (Internal)                      │  │
│  │                                                                      │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐   │  │
│  │  │  Tempo     │  │   Loki     │  │ Prometheus │  │  Grafana   │   │  │
│  │  │  (Traces)  │  │   (Logs)   │  │ (Metrics)  │  │ (Dashboards)│  │  │
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────┘   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Network Security Zones

### Zone 1: Public Internet (Untrusted)
- **Access:** Anyone with internet connection
- **Protocol:** HTTPS only
- **Entry Point:** CloudFront CDN

### Zone 2: Edge Layer (Managed by AWS)
- **Component:** CloudFront CDN
- **Security:** AWS Shield, AWS WAF (optional), TLS 1.2+
- **Threat Protection:** DDoS, common web exploits

### Zone 3: Presentation Layer (DMZ)
- **Component:** Nginx reverse proxy
- **Exposure:** HTTP port 80 (behind CloudFront)
- **Security:** Rate limiting, security headers, static file serving
- **Access Control:** None (public access, protected by auth layer)

### Zone 4: Authentication Layer (Trust Boundary)
- **Component:** Auth Gateway service
- **Exposure:** Internal only (docker network)
- **Security:** OAuth 2.0, JWT validation, CSRF protection
- **Access Control:** All requests must pass through this layer

### Zone 5: Application Layer (Trusted)
- **Components:** Backend services (Oracle, Backend API, Content Creator, etc.)
- **Exposure:** Internal only (docker network)
- **Security:** Trusts X-User-* headers from auth gateway
- **Access Control:** Network isolation enforces trust boundary

### Zone 6: Data Layer (Highly Protected)
- **Components:** PostgreSQL, Neo4j, RabbitMQ, Redis
- **Exposure:** Internal only (docker network)
- **Security:** No external access, volume encryption
- **Access Control:** Service-level credentials, connection pooling

---

## 3. Teams Integration Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     Microsoft Teams Client                        │
│                  (Desktop, Web, Mobile)                           │
└──────────────────┬───────────────────────────────────────────────┘
                   │
                   │ HTTPS
                   ▼
┌──────────────────────────────────────────────────────────────────┐
│              Teams Tab (React SPA)                                │
│         https://d23ew7gbss3vnh.cloudfront.net/teams              │
│                                                                   │
│  ┌────────────────────────┐  ┌────────────────────────┐          │
│  │   Chat Interface       │  │   Feed Interface       │          │
│  │   (Left Panel)         │  │   (Right Panel)        │          │
│  │                        │  │                        │          │
│  │  • User input          │  │  • AI-generated posts  │          │
│  │  • Message history     │  │  • Unread badges       │          │
│  │  • Markdown rendering  │  │  • Auto-refresh        │          │
│  └────────┬───────────────┘  └────────┬───────────────┘          │
│           │                           │                           │
└───────────┼───────────────────────────┼───────────────────────────┘
            │                           │
            │ POST /api/oracle/query    │ GET /api/content_creator_service/feed
            │                           │
            ▼                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                      Auth Gateway                                 │
│                   (JWT Validation)                                │
└──────────────────┬───────────────────┬───────────────────────────┘
                   │                   │
                   ▼                   ▼
        ┌──────────────────┐  ┌──────────────────────┐
        │  Oracle Service  │  │  Content Creator     │
        │  (Port 8003)     │  │  Service (Port 8002) │
        │                  │  │                      │
        │  • Query parsing │  │  • Feed generation   │
        │  • Neo4j search  │  │  • Agent personas    │
        │  • LLM response  │  │  • Post caching      │
        └────────┬─────────┘  └────────┬─────────────┘
                 │                     │
                 ▼                     ▼
        ┌────────────────────────────────────┐
        │         Neo4j Knowledge Graph      │
        │         (Port 7474, 7687)          │
        │                                    │
        │  • Topics, Organizations, People   │
        │  • Resources, Events               │
        │  • Vector embeddings               │
        └────────────────────────────────────┘
```

### Teams Interface Features

**Chat Panel (`/api/oracle/query`):**
- User submits natural language questions
- Oracle service performs multi-strategy retrieval
- Azure OpenAI generates contextualized answers
- Citations provided with source documents

**Feed Panel (`/api/content_creator_service/feed`):**
- Displays AI-generated content posts
- Refreshes periodically (client-side polling)
- Shows agent names, timestamps, engagement metrics
- Unread badge for new posts

---

## 4. Authentication Flow (Teams Integration)

```
┌────────────┐              ┌──────────────┐              ┌─────────────┐
│   Teams    │              │     Auth     │              │  AWS        │
│   Client   │              │   Gateway    │              │  Cognito    │
└─────┬──────┘              └──────┬───────┘              └──────┬──────┘
      │                            │                             │
      │ 1. GET /teams              │                             │
      ├───────────────────────────>│                             │
      │                            │                             │
      │ 2. Check cookie            │                             │
      │    (no valid token)        │                             │
      │                            │                             │
      │ 3. Redirect to Cognito     │                             │
      │<───────────────────────────┤                             │
      │                            │                             │
      │ 4. GET /oauth2/authorize                                 │
      ├──────────────────────────────────────────────────────────>│
      │                            │                             │
      │ 5. Show login page         │                             │
      │<──────────────────────────────────────────────────────────┤
      │                            │                             │
      │ 6. User enters             │                             │
      │    @extremenetworks.com    │                             │
      │    credentials             │                             │
      ├──────────────────────────────────────────────────────────>│
      │                            │                             │
      │ 7. Validate credentials    │                             │
      │    (check email domain)    │                             │
      │                            │                             │
      │ 8. Redirect with code      │                             │
      │<──────────────────────────────────────────────────────────┤
      │                            │                             │
      │ 9. GET /callback?code=XXX  │                             │
      ├───────────────────────────>│                             │
      │                            │                             │
      │                            │ 10. Exchange code for tokens│
      │                            ├────────────────────────────>│
      │                            │                             │
      │                            │ 11. Validate code           │
      │                            │     Return JWT + refresh    │
      │                            │<────────────────────────────┤
      │                            │                             │
      │ 12. Set HTTP-only cookies  │                             │
      │     (access_token,         │                             │
      │      refresh_token)        │                             │
      │<───────────────────────────┤                             │
      │                            │                             │
      │ 13. Redirect to /teams     │                             │
      │<───────────────────────────┤                             │
      │                            │                             │
      │ 14. GET /teams             │                             │
      │     (with cookies)         │                             │
      ├───────────────────────────>│                             │
      │                            │                             │
      │ 15. Validate JWT           │                             │
      │                            ├────────────────────────────>│
      │                            │                             │
      │ 16. JWT valid              │                             │
      │                            │<────────────────────────────┤
      │                            │                             │
      │ 17. Serve React app        │                             │
      │<───────────────────────────┤                             │
      │                            │                             │
      │ 18. API requests with      │                             │
      │     cookies                │                             │
      ├───────────────────────────>│                             │
      │                            │                             │
      │ 19. Validate JWT, add      │                             │
      │     X-User-* headers       │                             │
      │                            │                             │
      │ 20. Proxy to backend       │                             │
      │     services               │                             │
      │                            │                             │
```

**Key Security Points:**
1. All authentication handled by AWS Cognito (no password storage)
2. Email domain validated (@extremenetworks.com required)
3. JWT tokens in HTTP-only cookies (no JavaScript access)
4. CSRF protection via OAuth state parameter
5. Automatic token refresh (transparent to user)

---

## 5. Data Flow - Query Processing

```
┌────────────┐
│  User in   │
│   Teams    │
│            │
│ Question:  │
│ "What is   │
│  Wi-Fi 7?" │
└──────┬─────┘
       │
       │ HTTPS POST /api/oracle/query
       ▼
┌────────────────────────────────────────┐
│         Auth Gateway                   │
│  • Validate JWT                        │
│  • Extract user context                │
│  • Add X-User-Id header                │
└──────┬─────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────┐
│         Backend API (8001)             │
│  • Load user preferences from PG       │
│  • Parse query for filters (LLM)       │
│  • Merge filters with preferences      │
└──────┬─────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────┐
│         Oracle Service (8003)          │
│  Step 1: Multi-strategy retrieval      │
│   ├─ Vector search (embeddings)        │
│   ├─ Keyword search (full-text)        │
│   └─ Graph traversal (relationships)   │
│                                        │
│  Step 2: Score and rank results        │
│   ├─ Relevance (70%)                   │
│   │   • Topic match (40%)              │
│   │   • Organization match (30%)       │
│   │   • People match (20%)             │
│   │   • Relationship bonus (10%)       │
│   └─ Recency (30%)                     │
│                                        │
│  Step 3: Context assembly              │
│   • Top N documents                    │
│   • Metadata (authors, dates, urls)   │
│   • Graph context (related topics)    │
└──────┬─────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────┐
│      Neo4j Knowledge Graph             │
│  Query:                                │
│  MATCH (r:Resource)-[:DISCUSSES]->(t:Topic)│
│  WHERE t.name CONTAINS "Wi-Fi 7"       │
│  RETURN r, t                           │
└──────┬─────────────────────────────────┘
       │
       │ Results: [doc1, doc2, doc3...]
       ▼
┌────────────────────────────────────────┐
│      Azure OpenAI API                  │
│  Model: gpt-4o                         │
│  Prompt:                               │
│  "Based on the following documents,    │
│   answer the question: What is Wi-Fi 7?│
│   Documents: [...]                     │
│   Important: Only use information from │
│   the provided documents. Cite sources."│
└──────┬─────────────────────────────────┘
       │
       │ Response with citations
       ▼
┌────────────────────────────────────────┐
│         Oracle Service (8003)          │
│  • Format response with citations      │
│  • Add source metadata                 │
│  • Return JSON                         │
└──────┬─────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────┐
│         Backend API (8001)             │
│  • Log query event to PostgreSQL       │
│  • Track usage metrics                 │
│  • Return to client                    │
└──────┬─────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────┐
│         Teams Client                   │
│  Display:                              │
│  • Answer with markdown formatting     │
│  • Source citations (clickable)        │
│  • Related documents                   │
│  • Feedback buttons (👍👎)             │
└────────────────────────────────────────┘
```

**Performance:**
- Average query time: 2-5 seconds
- 90% of queries < 10 seconds
- Neo4j vector search: ~100ms
- Azure OpenAI API: ~2-3 seconds
- Context assembly: ~500ms

---

## 6. Service Communication Patterns

### 6.1 Synchronous (HTTP/REST)

```
Frontend → Auth Gateway → Backend Services
          (JWT validation)  (trusted headers)
```

**Example:**
```
GET /api/oracle/query
├─ Auth Gateway validates JWT
├─ Adds X-User-Id: "user-123"
├─ Adds X-User-Email: "john@extremenetworks.com"
├─ Adds X-User-Role: "user"
└─ Proxies to http://oracle:8003/query
```

### 6.2 Asynchronous (RabbitMQ)

```
Retriever → RabbitMQ Queue → Digester → Neo4j
          (scraped_content)  (entity extraction)
```

**Example:**
```
1. Retriever scrapes Wi-Fi Alliance website
2. Publishes message to 'scraped_content' queue
3. Digester consumes message
4. Extracts entities via LLM
5. Writes to Neo4j graph
```

---

## 7. Deployment Architecture (AWS)

```
┌─────────────────────────────────────────────────────────┐
│                    AWS Account                          │
│                                                         │
│  ┌────────────────────────────────────────────────────┐│
│  │              CloudFront Distribution                ││
│  │  • Global edge locations                           ││
│  │  • SSL certificate (ACM)                           ││
│  │  • Origin: EC2 public IP                           ││
│  └──────────────────┬─────────────────────────────────┘│
│                     │                                   │
│  ┌──────────────────▼──────────────────────────────┐   │
│  │                 VPC                              │   │
│  │                                                  │   │
│  │  ┌────────────────────────────────────────────┐ │   │
│  │  │         Public Subnet                      │ │   │
│  │  │                                            │ │   │
│  │  │  ┌──────────────────────────────────────┐ │ │   │
│  │  │  │  EC2 Instance (t3.xlarge)            │ │ │   │
│  │  │  │  • Ubuntu 22.04 LTS                  │ │ │   │
│  │  │  │  • Docker + Docker Compose           │ │ │   │
│  │  │  │  • EBS Volume (100GB gp3)            │ │ │   │
│  │  │  │                                      │ │ │   │
│  │  │  │  Exposed Ports:                      │ │ │   │
│  │  │  │  • 80 (HTTP - from CloudFront)       │ │ │   │
│  │  │  │  • 443 (HTTPS - if direct access)    │ │ │   │
│  │  │  │  • 22 (SSH - restricted to admin IP) │ │ │   │
│  │  │  └──────────────────────────────────────┘ │ │   │
│  │  │                                            │ │   │
│  │  │  Security Group:                          │ │   │
│  │  │  • Inbound: 80, 443 (CloudFront)          │ │   │
│  │  │  • Inbound: 22 (admin IP only)            │ │   │
│  │  │  • Outbound: All (for updates, AWS APIs)  │ │   │
│  │  └────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  ┌────────────────────────────────────────────────────┐│
│  │              AWS Cognito User Pool                  ││
│  │  • User authentication                             ││
│  │  • OAuth 2.0 endpoints                             ││
│  │  • JWT token issuance                              ││
│  │  • Email verification                              ││
│  │  • Password policies                               ││
│  └────────────────────────────────────────────────────┘│
│                                                         │
│  ┌────────────────────────────────────────────────────┐│
│  │         Certificate Manager (ACM)                   ││
│  │  • SSL/TLS certificate for CloudFront              ││
│  │  • Auto-renewal                                    ││
│  └────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

---

## 8. Scaling Considerations

### Current Deployment (Single EC2)
- **Capacity:** ~100 concurrent users
- **Bottleneck:** LLM API calls (Azure OpenAI)
- **Storage:** EBS volumes (expand as needed)

### Horizontal Scaling Path

```
                   CloudFront
                       │
                       ▼
                Application Load Balancer
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
      EC2-1         EC2-2         EC2-3
         │             │             │
         └─────────────┼─────────────┘
                       │
              Shared Data Layer
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
    RDS Postgres   Neo4j Cluster   ElastiCache
```

**When to Scale:**
- CPU utilization > 70% sustained
- Response times > 10 seconds for queries
- User count > 50 concurrent

---

## 9. Disaster Recovery

### Backup Strategy
- **PostgreSQL:** Daily automated backups (pg_dump)
- **Neo4j:** Weekly graph snapshots
- **Configuration:** Git repository (version controlled)
- **Retention:** 30 days

### Recovery Procedures
1. Provision new EC2 instance
2. Restore Docker volumes from backups
3. Update CloudFront origin to new EC2 IP
4. DNS propagation (~5 minutes)
5. Verify all services operational

**RTO (Recovery Time Objective):** < 4 hours  
**RPO (Recovery Point Objective):** < 24 hours  

---

## 10. Technology Stack Summary

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **CDN** | AWS CloudFront | Global content delivery, SSL/TLS |
| **Web Server** | Nginx | Reverse proxy, static files, rate limiting |
| **Auth** | AWS Cognito | User authentication (OAuth 2.0 + JWT) |
| **API Gateway** | FastAPI (Python) | Authentication proxy, request routing |
| **Backend** | FastAPI (Python) | REST APIs for all services |
| **Frontend** | React 18 + TypeScript | Teams UI, chat interface |
| **Database** | PostgreSQL 16 | User data, preferences, analytics |
| **Graph DB** | Neo4j 2025 Community | Knowledge graph, vector search |
| **Message Queue** | RabbitMQ 3.12 | Async processing pipeline |
| **Cache** | Redis 7.2 | Rate limiting, session caching |
| **LLM** | Azure OpenAI (GPT-4o) | Q&A generation, entity extraction |
| **Embeddings** | Azure OpenAI (text-embedding-3-large) | Vector search |
| **Observability** | Grafana Stack | Logging (Loki), metrics (Prometheus), tracing (Tempo) |
| **Orchestration** | Docker Compose | Service management |
| **OS** | Ubuntu 22.04 LTS | EC2 instance |

---

**Document Control:**
- **Review Frequency:** Quarterly or after major architecture changes
- **Next Review Date:** 2026-06-09
- **Document Owner:** OCTO Team
- **Related Documents:** SECURITY_OVERVIEW.md, DATA_FLOW.md

