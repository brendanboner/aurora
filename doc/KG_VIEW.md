# Knowledge Graph Visualizer

Interactive 3D visualization tool for exploring Neo4j knowledge graphs with natural language query support via Azure OpenAI.

## Features

- **3D Force-Directed Graph**: Interactive Three.js visualization with physics-based layout
- **Entity Search**: Search and highlight entities with relationship exploration (1-hop, 2-hop neighborhoods)
- **Natural Language Queries**: Transform plain English to Cypher queries using Azure OpenAI
- **Topic-Based Filtering**: Filter by topics (Person, Organization, Technology, Resource)
- **Keyboard Navigation**: Arrow keys for rotation/pan, +/- for zoom
- **Dynamic Node Sizing**: Entity-centric sizing based on connection strength and hop distance
- **Hierarchical Highlighting**: Primary entity highlights separate from node exploration

## Architecture

### Backend (Port 8002)
- **Framework**: FastAPI (Python 3.11)
- **Database**: Neo4j (via `neo4j-client` shared library)
- **LLM**: Azure OpenAI GPT-4o for query transformation
- **Endpoints**:
  - `GET /api/graph/stats` - Graph statistics
  - `GET /api/graph/search` - Entity search with autocomplete
  - `POST /api/graph/query` - Execute Cypher queries
  - `GET /api/graph/connections` - Get entity relationships
  - `POST /api/llm/transform-query` - Natural language to Cypher
  - `POST /api/llm/extract-entities` - Extract entities from text
  - `GET /api/autocomplete/topics` - Topic suggestions

### Frontend (Port 5173)
- **Framework**: React 19.2 with TypeScript
- **Visualization**: Three.js + react-force-graph-3d
- **Animation**: GSAP for node pulsing effects
- **Build Tool**: Vite 7.3

## Key Configuration

### Environment Variables
Located in parent directory's `.env`:
```env
# Neo4j Connection
NEO4J_DATABASE=neo4j
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
NEO4J_URI=bolt://neo4j:7687
NEO4J_HTTP_PORT=7474
NEO4J_BOLT_PORT=7687

# Azure OpenAI
AZURE_OPENAI_API_KEY=your_key
AZURE_OPENAI_ENDPOINT=https://your-endpoint.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_DEPLOYMENT=gpt-4o
```

### Ports
- **Frontend**: 5173
- **Backend**: 8002

### Dependencies
- **Shared Library**: `../neo4j-client` (relative to this directory)
- **Database**: Neo4j 5.26+ (shared with main project)

## Docker Integration

### Add to Main Project's docker-compose.yml

```yaml
services:
  # ... your existing services (postgres, neo4j, redis, etc.)

  kg-view-backend:
    build:
      context: ./kg_view
      dockerfile: Dockerfile.backend
    container_name: kg_view_backend
    environment:
      - NEO4J_DATABASE=${NEO4J_DATABASE}
      - NEO4J_USER=${NEO4J_USER}
      - NEO4J_PASSWORD=${NEO4J_PASSWORD}
      - NEO4J_URI=bolt://neo4j:${NEO4J_BOLT_PORT}
      - AZURE_OPENAI_API_KEY=${AZURE_OPENAI_API_KEY}
      - AZURE_OPENAI_ENDPOINT=${AZURE_OPENAI_ENDPOINT}
      - AZURE_OPENAI_API_VERSION=${AZURE_OPENAI_API_VERSION:-2024-10-21}
      - AZURE_OPENAI_DEPLOYMENT=${AZURE_OPENAI_DEPLOYMENT}
    networks:
      - main_network
    depends_on:
      - neo4j
    restart: unless-stopped

  kg-view-frontend:
    build:
      context: ./kg_view
      dockerfile: Dockerfile.frontend
    container_name: kg_view_frontend
    networks:
      - main_network
    depends_on:
      - kg-view-backend
    restart: unless-stopped

networks:
  main_network:
    driver: bridge
```

### Nginx Configuration (Main Project)

Add to your main project's nginx configuration:

```nginx
# Knowledge Graph Visualizer
location /kg_view/ {
    proxy_pass http://kg-view-frontend:5173/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection 'upgrade';
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_cache_bypass $http_upgrade;
    
    # Rewrite to remove /kg_view prefix
    rewrite ^/kg_view/(.*) /$1 break;
}

# KG Visualizer API
location /api/kg_view/ {
    proxy_pass http://kg-view-backend:8002/api/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    
    # Rewrite to remove /kg_view prefix
    rewrite ^/api/kg_view/(.*) /api/$1 break;
}
```

## File Structure

```
kg_view/
├── README.md                    # This file - complete documentation
├── .env.example                 # Environment variable template
├── Dockerfile.backend           # Backend container definition
├── Dockerfile.frontend          # Frontend container definition
├── backend/
│   ├── main.py                  # FastAPI application
│   ├── requirements.txt         # Python dependencies
│   └── services/
│       ├── neo4j_service.py     # Neo4j client wrapper
│       └── llm_service.py       # Azure OpenAI integration
└── kg-visualizer/
    ├── package.json             # Node.js dependencies
    ├── vite.config.ts           # Vite build configuration
    ├── index.html               # Entry HTML
    └── src/
        ├── App.tsx              # Main React application
        ├── components/
        │   ├── GraphCanvas.tsx  # 3D visualization component
        │   ├── NodeDetails.tsx  # Entity details panel
        │   ├── QueryBar.tsx     # Search and query interface
        │   └── TopicSelector.tsx # Topic filtering
        ├── services/
        │   └── api.ts           # API client
        └── types/
            └── graph.ts         # TypeScript type definitions
```

## API Examples

### Get Graph Statistics
```bash
curl http://localhost:8002/api/graph/stats
```

### Search Entities
```bash
curl "http://localhost:8002/api/graph/search?q=david%20coleman&limit=10"
```

### Natural Language Query
```bash
curl -X POST http://localhost:8002/api/llm/transform-query \
  -H 'Content-Type: application/json' \
  -d '{"natural_language_query": "what does david coleman talk about"}'
```

### Get Entity Connections
```bash
curl "http://localhost:8002/api/graph/connections?entity_ids=Person:123,Person:456"
```

## Development Setup (Standalone)

Only needed for standalone development (not required when integrated):

```bash
# Install backend dependencies
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install frontend dependencies
cd ../kg-visualizer
npm install

# Start services (requires Neo4j running)
# Terminal 1 - Backend
cd backend && source venv/bin/activate && python main.py

# Terminal 2 - Frontend
cd kg-visualizer && npm run dev
```

Access at:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8002/docs

## Visualization Features

### Node Sizing
- **Selected Entity**: 250% size with pulsing animation
- **1-Hop Strong Links**: 230% (connection count > median)
- **1-Hop Regular**: 200%
- **2-Hop**: 170%
- **3+ Hops**: 150%
- **Unrelated**: 100% base size

### Link Opacity
- **1-Hop**: 95% opacity
- **2-Hop**: 85% opacity
- **3+ Hops**: 70% opacity
- **Unrelated**: 20% opacity

### Keyboard Controls
- **Arrow Keys**: Rotate/pan camera
- **+/-**: Zoom in/out
- **Click Node**: Center and show details
- **Hover Node**: Highlight connections

### Node Colors (by Type)
- Person: Blue (#4299e1)
- Organization: Purple (#9f7aea)
- Technology: Green (#48bb78)
- Resource: Orange (#ed8936)
- Topic: Yellow (#ecc94b)

## Technical Details

### Backend Dependencies
- fastapi==0.115.0
- uvicorn==0.32.0
- neo4j==5.26.0
- openai==1.54.0
- pydantic==2.10.0
- python-dotenv==1.0.0

### Frontend Dependencies
- react==19.2.0
- three==0.183.0
- react-force-graph-3d==1.25.4
- gsap==3.14.2
- axios==1.13.5
- vite==7.3.1

### Database Schema
Expects Neo4j nodes with:
- Labels: `Person`, `Organization`, `Technology`, `Resource`, `Topic`
- Properties: `name` (required), `description`, `title`, `url`
- Relationships: Any type (RELATED_TO, WORKS_WITH, etc.)

### Performance
- Graph physics stabilization: ~2-3 seconds for 100-500 nodes
- Camera animations: 200ms smooth transitions
- Node rendering: Instanced meshes for performance
- API response: <100ms for most queries (depends on Neo4j)

## Troubleshooting

### Frontend can't connect to backend
- Check backend is running: `curl http://localhost:8002/api/graph/stats`
- Verify VITE_API_URL in `kg-visualizer/.env`
- Check Docker network connectivity

### No data showing
- Verify Neo4j connection: Check NEO4J_URI environment variable
- Ensure Neo4j has data: Run `MATCH (n) RETURN count(n)` in Neo4j Browser
- Check backend logs for connection errors

### Azure OpenAI not working
- Verify AZURE_OPENAI_API_KEY is set
- Check AZURE_OPENAI_ENDPOINT format (must include https://)
- Ensure deployment name matches AZURE_OPENAI_DEPLOYMENT

### Graph performance issues
- Limit query results (default: 100 nodes)
- Use topic filtering to reduce visible nodes
- Consider Neo4j query optimization

## Security Considerations

- Backend validates all Cypher queries before execution
- CORS configured for frontend origin only
- Environment variables required (no hardcoded credentials)
- Neo4j read-only user recommended for production
- API rate limiting recommended via nginx

## Monitoring

Docker logs available via:
```bash
docker logs kg_view_backend
docker logs kg_view_frontend
```

Health checks:
```bash
# Backend health
curl http://kg-view-backend:8002/api/graph/stats

# Frontend health (through nginx)
curl http://your-domain/kg_view/
```

## License

Internal project - not for external distribution.

## Support

For issues or questions, contact the development team or refer to:
- Neo4j Documentation: https://neo4j.com/docs/
- FastAPI Documentation: https://fastapi.tiangolo.com/
- Three.js Documentation: https://threejs.org/docs/
