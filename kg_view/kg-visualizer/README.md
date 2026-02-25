# Knowledge Graph Visualizer

A high-performance, sci-fi styled 3D visualizer for Neo4j knowledge graphs with intelligent natural language query transformation via Azure OpenAI GPT-4o.

![Knowledge Graph Visualizer](https://img.shields.io/badge/React-19.2-blue) ![TypeScript](https://img.shields.io/badge/TypeScript-5.6-blue) ![Three.js](https://img.shields.io/badge/Three.js-3D-green) ![FastAPI](https://img.shields.io/badge/FastAPI-Python-green)

## Features

- 🌌 **3D Universe View**: WebGL-powered 3D force-directed graph with up to 100k nodes
- 🧠 **AI-Powered Queries**: Natural language to Cypher query transformation using GPT-4o
- 🎯 **Smart Entity Selection**: Autocomplete topics, organizations, and people with caching
- ⚡ **Synaptic Animations**: Pulsing connections between selected entities
- 🔍 **Multi-Hop Exploration**: Explore 1-hop and 2-hop neighborhoods dynamically
- 🎨 **Visual Encoding**: Node size by importance, edge width/opacity by confidence
- 📊 **Real-time Stats**: Live graph statistics and node counts
- 🎭 **Smooth Animations**: GSAP-powered transitions and camera movements
- 💾 **Smart Caching**: LocalStorage for recent queries and entity selections

## Architecture

```
kg-visualizer/                    # React + TypeScript frontend
├── src/
│   ├── components/
│   │   ├── GraphCanvas.tsx       # 3D visualization (Three.js + react-force-graph)
│   │   ├── QueryBar.tsx          # Natural language query input
│   │   ├── TopicSelector.tsx     # Entity autocomplete selector
│   │   └── NodeDetails.tsx       # Node property inspector
│   ├── services/
│   │   └── api.ts                # API client for backend
│   └── types/
│       └── graph.ts              # TypeScript interfaces

backend/                          # Python FastAPI backend
├── services/
│   ├── neo4j_service.py         # Neo4j client wrapper
│   └── llm_service.py           # Azure OpenAI integration
└── main.py                       # FastAPI app with REST endpoints
```

## Prerequisites

- **Node.js** 18+ and npm
- **Python** 3.10+
- **Neo4j** 5.x running with populated knowledge graph
- **Azure OpenAI** API key with GPT-4o deployment

## Quick Start

### 1. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Environment is already configured in .env
# Start the FastAPI server
python main.py
# API will be available at http://localhost:8000
```

### 2. Frontend Setup

```bash
cd kg-visualizer

# Install dependencies (already done)
npm install

# Start development server
npm run dev
# App will be available at http://localhost:5173
```

### 3. Open in Browser

Navigate to `http://localhost:5173` and start exploring!

## Usage

### Natural Language Queries

Type questions in plain English:

- "Show me all Wi-Fi 6 resources"
- "Find topics related to IEEE 802.11"
- "What organizations work on Wi-Fi standards?"
- "Show resources from Wi-Fi Alliance published in 2024"

The system will:
1. Transform your query to Cypher using GPT-4o
2. Extract relevant entities (topics, organizations, people)
3. Execute the query and visualize results
4. Populate the topic selector with extracted entities

### Entity Selection

Type in the topic selector to search:

- `topic:Wi-Fi 6` - Find and highlight a specific topic
- `organization:IEEE` - Find and highlight an organization
- `person:John Smith` - Find and highlight a person

**Multi-Select**: Select multiple entities to see pulsing connections between them!

### Graph Interaction

- **Click** a node to select it and show details
- **Hover** over nodes to see tooltips
- **Drag** nodes to reposition
- **Scroll** to zoom in/out
- **Right-drag** to rotate the 3D view
- **Click background** to deselect

### Node Details Panel

When a node is selected:
- View all properties and metadata
- Click "1-Hop Neighbors" to explore immediate connections
- Click "2-Hop Neighbors" to explore broader neighborhood
- Links and dates are clickable

## Configuration

### Node Color Mapping

Colors are coded by node type:
- 🔵 **Resource** (Documents) - Blue (#4A90E2)
- 🟣 **Topic** - Purple (#9B59B6)
- 🟢 **Organization** - Green (#2ECC71)
- 🟠 **Event** - Orange (#E67E22)
- 🔴 **Person** - Red (#E74C3C)
- ⚪ **DataSource** - Gray (#95A5A6)

## API Endpoints

### Graph Data
- `GET /api/graph/stats` - Graph statistics
- `GET /api/graph/data` - Paginated graph data
- `POST /api/graph/query` - Execute Cypher query
- `GET /api/graph/neighborhood/{node_id}` - Get node neighborhood
- `GET /api/graph/search` - Full-text search

### Autocomplete
- `GET /api/autocomplete/topics` - Topic autocomplete
- `GET /api/autocomplete/organizations` - Organization autocomplete
- `GET /api/autocomplete/people` - People autocomplete
- `GET /api/autocomplete/all` - All entity types

### LLM Services
- `POST /api/llm/transform-query` - Transform natural language to Cypher
- `POST /api/llm/extract-entities` - Extract entities from text

## Technologies Used

**Frontend**:
- React 19 + TypeScript
- Three.js + react-force-graph-3d (WebGL rendering)
- D3-force (physics simulation)
- GSAP (animations)
- Axios + TanStack Query (data fetching)

**Backend**:
- FastAPI (async Python web framework)
- neo4j-client (custom Neo4j wrapper)
- Azure OpenAI (GPT-4o for query transformation)
- Pydantic (data validation)

## License

Proprietary - Aurora Knowledge Graph Project
