# KG View - Knowledge Graph Visualization

Interactive 3D visualization tool for exploring Neo4j knowledge graphs with natural language query support via Azure OpenAI.

## Project Structure

- `backend/` - FastAPI backend service (port 8002)
- `kg-visualizer/` - React frontend (built and served via nginx/proxy)
- `Makefile` - Aurora service Makefile for Docker builds
- `Dockerfile.backend` - Backend container image
- `Dockerfile.frontend` - Frontend container image
- `nginx.conf` - Local development nginx configuration

## Integration with Aurora

The KG View service is integrated into the main Aurora project:

1. **Local Development**: Services run in `docker-compose.yml` on ports 8002 (backend) and 5173 (frontend)
2. **Production**: Deployed via `prod-deployment/docker-compose.prod.yml` with:
   - Backend accessible at `/api/visualisation/` via nginx proxy
   - Frontend accessible at `/visualisation/` via nginx rewrite to React Router
3. **Shared Resources**:
   - Uses shared `neo4j-client` library from root
   - Inherits all environment variables from root `.env` file
   - Connects to same Neo4j instance as main Aurora services

## Configuration

All configuration is inherited from parent `.env` file:

```env
# Neo4j
NEO4J_DATABASE=neo4j
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
NEO4J_URI=bolt://neo4j:7687

# Azure OpenAI
AZURE_OPENAI_API_KEY=your_key
AZURE_OPENAI_ENDPOINT=https://...
```

## Building & Deploying

From root directory:

```bash
# Build both backend and frontend images
cd kg_view && make build

# Push to ECR
make push

# Or complete workflow (test -> build -> push)
make ship
```

## API Endpoints

Backend exposes these endpoints (proxied at `/api/visualisation/`):

- `GET /health` - Health check
- `GET /api/graph/stats` - Graph statistics
- `GET /api/graph/search` - Entity search
- `POST /api/graph/query` - Execute Cypher queries
- `POST /api/llm/transform-query` - Natural language to Cypher

## Documentation

Full documentation moved to `doc/`:
- `doc/KG_VIEW.md` - Feature overview and architecture
- `doc/KG_VIEW_INTEGRATION.md` - Integration guide

## Running Locally

```bash
# Start with main project
docker compose up

# Services available at:
# - Backend: http://localhost:8002
# - Frontend: http://localhost:5173
# - Via nginx: http://localhost/visualisation
```
