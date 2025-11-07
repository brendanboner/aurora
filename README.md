# AURORA — Standards & Industry Intelligence Navigator

AURORA is a UI-driven, knowledge-graph–backed prototype that helps teams track activity across standards bodies, alliances, and academic organizations, and delivers personalized synopses of relevant events, working groups, and documents.

- Frontend: React + Vite (TypeScript)
- Backend: TypeScript (Express)
- DB: Postgres + Neo4j
- Deployment: Docker / Docker Compose

## Quick Start
1) Copy `.env.example` to `.env` and set values.
2) docker compose -f ops/docker-compose.yml up --build
3) Frontend: http://localhost:5173
   Backend:  http://localhost:8080
   Neo4j:    http://localhost:7474


---
## Repository Structure

```
/aurora
  /frontend             # React app (Overview, Profile, Admin)
  /backend              # REST API, RBAC, LLM orchestration, validators
  /graph                # Neo4j: schema.cql, constraints, seed loaders
  /db                   # Postgres: schema.sql, migrations, seed
  /ingestion            # Fetchers/parsers for web + file uploads
  /llm                  # Prompt templates, JSON schemas, guards
  /ops                  # Dockerfiles, docker-compose, k8s (optional)
  /scripts              # Admin CLI utilities
  /tests                # Unit/integration tests
```

---

## Quick Start (Containers)

### 1. Prerequisites
- Docker + Docker Compose
- (Optional) Node 18+ if running services outside containers

### 2. Environment Variables
Create a `.env` file at the repo root:

```
# Postgres
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=aurora
POSTGRES_USER=aurora
POSTGRES_PASSWORD=aurora

# Neo4j
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=devpassword

# Backend
PORT=8080
JWT_SECRET=change-me
ALLOWED_ORIGINS=http://localhost:5173

# LLM Provider
LLM_PROVIDER=openai
LLM_API_KEY=sk-...

# Optional
DATA_DIR=/data
```

### 3. Start the system

```
docker compose -f ops/docker-compose.yml up --build
```

Services:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8080
- Neo4j Browser: http://localhost:7474
- Postgres: localhost:5432 (db: `aurora`, user: `aurora`, pass: `aurora`)

---

## Components

### Frontend (React)
- Views:
  - Overview: followed bodies/WGs, headlines, events, participation
  - Profile: topic sliders (1–10), preferred bodies, working groups
  - Admin: initialization workflows, interest regeneration, yearly events export

Run:
```
cd frontend
npm install
npm run dev
```

---

### Backend (API + Orchestration)
- Tech: Node.js + TypeScript with Zod/JSON Schema
- Stores:
  - Postgres: auth, user state, event participation, cached LLM output
  - Neo4j: topics, bodies, working groups, events, document relationships
- Functions:
  - Authentication + RBAC
  - CRUD for topics, bodies, working groups, events, headlines
  - LLM Orchestration (initialization, interest modeling, summaries)

Run:
```
cd backend
npm install
npm run dev
```

---

## Data Model

### Postgres (transactional)
- users
- user_topic_preferences
- user_body_preferences
- user_working_group_preferences
- events
- headlines
- user_event_status
- daily_synopsis

### Neo4j (knowledge graph)
Nodes:
- TopicArea
- Body {type}
- WorkingGroup
- Event
- Document

Relationships:
- (:Body)-[:HAS_WG]->(:WorkingGroup)
- (:WorkingGroup)-[:ABOUT {weight}]->(:TopicArea)
- (:Document)-[:ASSOCIATED_WITH]->(:WorkingGroup|Body|TopicArea)
- (:Event)-[:RELATED_TO]->(:WorkingGroup|Body|TopicArea)

---

## LLM JSON Schema Contracts
- topics.v1
- bodies.v1
- working-groups.v1
- user-interests.v1
- daily-synopsis.v1
- events-yearly.v1

All LLM responses must match schema and version.

---

## Local Development (without containers)

### Backend
```
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=aurora
export POSTGRES_USER=aurora
export POSTGRES_PASSWORD=aurora

export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=devpassword

cd backend
npm install
npm run migrate
npm run start:dev
```

### Frontend
```
cd frontend
npm install
npm run dev
```

---

## Tests
```
npm run test
```

Tests include:
- API routes
- JSON schema validation
- RBAC enforcement
- Graph linkage tests

---

## Security Notes (Prototype)
- JWT-based login for prototype (SSO later)
- Secrets via `.env` or container env
- Rate limiting on LLM routes
- Admin actions audited and idempotent

---

## License
Internal prototype. Not for external distribution.
