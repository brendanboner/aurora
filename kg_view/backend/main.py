"""
FastAPI Backend for Knowledge Graph Visualizer
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
import os

from services.neo4j_service import Neo4jService
from services.llm_service import LLMService

# Load environment variables
load_dotenv()

app = FastAPI(
    title="Knowledge Graph Visualizer API",
    description="API for querying and visualizing Neo4j knowledge graph",
    version="1.0.0"
)

# CORS configuration
origins = os.getenv('CORS_ORIGINS', 'http://localhost:5173').split(',')
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
neo4j_service = Neo4jService()
llm_service = LLMService()


# Request/Response Models
class QueryRequest(BaseModel):
    query: str
    parameters: Optional[Dict[str, Any]] = None


class TransformQueryRequest(BaseModel):
    natural_language_query: str


class QueryResponse(BaseModel):
    results: List[Dict[str, Any]]
    execution_time_ms: Optional[float] = None


# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "kg-visualizer-api"}


# Graph Statistics
@app.get("/api/graph/stats")
async def get_graph_stats():
    """Get statistics about the knowledge graph"""
    try:
        stats = neo4j_service.get_graph_stats()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Graph Data
@app.get("/api/graph/data")
async def get_graph_data(
    limit: int = Query(default=1000, le=10000, description="Maximum nodes to return"),
    skip: int = Query(default=0, ge=0, description="Number of nodes to skip"),
    node_types: Optional[str] = Query(default=None, description="Comma-separated node types to filter")
):
    """Get graph nodes and relationships for visualization"""
    try:
        node_type_list = node_types.split(',') if node_types else None
        data = neo4j_service.get_graph_data(limit=limit, node_types=node_type_list, skip=skip)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Execute Cypher Query
@app.post("/api/graph/query")
async def execute_query(request: QueryRequest):
    """Execute a Cypher query with timeout protection"""
    try:
        timeout = int(os.getenv('QUERY_TIMEOUT', '10'))
        results = neo4j_service.execute_cypher(
            query=request.query,
            parameters=request.parameters,
            timeout=timeout
        )
        return {"results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Query error: {str(e)}")


# Autocomplete endpoints
@app.get("/api/autocomplete/topics")
async def autocomplete_topics(
    search: str = Query(default="", description="Search text"),
    limit: int = Query(default=50, le=100)
):
    """Get topics for autocomplete"""
    try:
        results = neo4j_service.get_topics_autocomplete(search=search, limit=limit)
        return {"results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/autocomplete/organizations")
async def autocomplete_organizations(
    search: str = Query(default="", description="Search text"),
    limit: int = Query(default=50, le=100)
):
    """Get organizations for autocomplete"""
    try:
        results = neo4j_service.get_organizations_autocomplete(search=search, limit=limit)
        return {"results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/autocomplete/people")
async def autocomplete_people(
    search: str = Query(default="", description="Search text"),
    limit: int = Query(default=50, le=100)
):
    """Get people for autocomplete"""
    try:
        results = neo4j_service.get_people_autocomplete(search=search, limit=limit)
        return {"results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/autocomplete/all")
async def autocomplete_all(
    search: str = Query(default="", description="Search text"),
    limit: int = Query(default=50, le=100)
):
    """Get all entity types for autocomplete"""
    try:
        # Fetch entities with their rankings
        orgs = neo4j_service.get_organizations_autocomplete(search=search, limit=limit)
        topics = neo4j_service.get_topics_autocomplete(search=search, limit=limit)
        people = neo4j_service.get_people_autocomplete(search=search, limit=limit)
        events = neo4j_service.get_events_autocomplete(search=search, limit=limit)
        
        # Format with prefixes and add entity_rank (0 for orgs first, then others)
        org_results = [{"value": f"organization:{o['name']}", "label": f"Organization: {o['name']}", "data": o, "rank": o.get('rank', 99), "entity_rank": 0} for o in orgs]
        topic_results = [{"value": f"topic:{t['name']}", "label": f"Topic: {t['name']}", "data": t, "rank": t.get('rank', 99), "entity_rank": 1} for t in topics]
        event_results = [{"value": f"event:{e['name']}", "label": f"Event: {e['name']}", "data": e, "rank": e.get('rank', 99), "entity_rank": 2} for e in events]
        person_results = [{"value": f"person:{p['name']}", "label": f"Person: {p['name']}", "data": p, "rank": p.get('rank', 99), "entity_rank": 3} for p in people]
        
        # Combine and sort: organizations first, then by rank within each type
        all_results = org_results + topic_results + event_results + person_results
        all_results.sort(key=lambda x: (x['entity_rank'], x['rank']))
        
        # Remove temporary ranking fields
        for result in all_results:
            result.pop('rank', None)
            result.pop('entity_rank', None)
        
        return {"results": all_results[:limit], "count": len(all_results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Node neighborhood
@app.get("/api/graph/neighborhood/{node_id}")
async def get_node_neighborhood(
    node_id: str,  # Changed to str to support Neo4j elementId format
    hops: int = Query(default=2, ge=1, le=3, description="Number of hops"),
    limit: int = Query(default=100, le=500)
):
    """Get neighborhood of a node"""
    try:
        data = neo4j_service.get_node_neighborhood(node_id=node_id, hops=hops, limit=limit)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Entity subgraph
@app.post("/api/graph/entity-subgraph")
async def get_entity_subgraph(
    entity_ids: List[str],
    hops: int = Query(default=3, ge=1, le=4, description="Number of hops"),
    limit: int = Query(default=500, le=2000)
):
    """Get subgraph connecting multiple entities by their IDs"""
    try:
        data = neo4j_service.get_entity_subgraph(entity_ids=entity_ids, hops=hops, limit=limit)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Search nodes
@app.get("/api/graph/search")
async def search_nodes(
    q: str = Query(description="Search query"),
    limit: int = Query(default=100, le=500)
):
    """Full-text search across all nodes"""
    try:
        results = neo4j_service.search_nodes(search_text=q, limit=limit)
        return {"results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# LLM Query Transformation
@app.post("/api/llm/transform-query")
async def transform_query(request: TransformQueryRequest):
    """Transform natural language query to Cypher using LLM"""
    try:
        result = llm_service.transform_query(request.natural_language_query)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/llm/extract-entities")
async def extract_entities(request: QueryRequest):
    """Extract entities from text and match them to database entities using aliases"""
    try:
        # Extract entities using LLM
        entities = llm_service.extract_entities_from_text(request.query)
        
        # Enhance entities with database matches using aliases
        enhanced_entities = []
        unmatched_entities = []
        
        for entity in entities:
            # Search database for matches including aliases
            search_results = neo4j_service.search_nodes(entity['name'], limit=10)
            
            if search_results:
                # Find best match by type, checking aliases
                best_match = None
                for result in search_results:
                    if result['label'].lower() == entity['type'].lower():
                        # Check if name or aliases match
                        props = result.get('properties', {})
                        aliases = props.get('aliases', [])
                        entity_name_lower = entity['name'].lower()
                        
                        if (result['name'].lower() == entity_name_lower or
                            any(alias.lower() == entity_name_lower for alias in aliases) or
                            any(entity_name_lower in alias.lower() for alias in aliases)):
                            best_match = result
                            break
                
                if best_match:
                    # Use the database entity with proper ID
                    props = best_match.get('properties', {})
                    entity_id = (props.get('person_id') or 
                               props.get('org_id') or 
                               props.get('topic_id') or
                               props.get('event_id') or
                               best_match['name'])
                    
                    enhanced_entities.append({
                        'type': best_match['label'].lower(),
                        'name': best_match['name'],
                        'id': entity_id
                    })
                else:
                    # No type match, keep for potential plain text search
                    unmatched_entities.append(entity)
            else:
                # No search results, keep for potential plain text search
                unmatched_entities.append(entity)
        
        # If we have unmatched entities, do a plain text search and extract entities from results
        if unmatched_entities and len(enhanced_entities) == 0:
            # Do a broader plain text search with the original query
            plain_text_results = neo4j_service.search_nodes(request.query, limit=20)
            
            if plain_text_results:
                # Build context from search results for LLM to analyze
                context_parts = []
                for result in plain_text_results[:10]:  # Limit to top 10 results
                    props = result.get('properties', {})
                    name = result['name']
                    label = result['label']
                    summary = props.get('summary', props.get('description', ''))[:200]
                    context_parts.append(f"{label}: {name} - {summary}")
                
                context = "\n".join(context_parts)
                
                # Ask LLM to extract entities from this context
                extraction_prompt = f"""Based on the user's query "{request.query}" and these related entities from the database:

{context}

Extract the most relevant entities that match the user's intent. Return entities in this format:
[{{"type": "topic|organization|person|event", "name": "Entity Name"}}]

Focus on entities that actually appear in the database results above."""
                
                contextual_entities = llm_service.extract_entities_with_context(extraction_prompt, context)
                
                # Match these contextual entities to the search results
                for entity in contextual_entities:
                    for result in plain_text_results:
                        if result['label'].lower() == entity['type'].lower():
                            name_match = (
                                entity['name'].lower() in result['name'].lower() or
                                result['name'].lower() in entity['name'].lower()
                            )
                            
                            if name_match:
                                props = result.get('properties', {})
                                entity_id = (props.get('person_id') or 
                                           props.get('org_id') or 
                                           props.get('topic_id') or
                                           props.get('event_id') or
                                           result['name'])
                                
                                enhanced_entities.append({
                                    'type': result['label'].lower(),
                                    'name': result['name'],
                                    'id': entity_id
                                })
                                break
        
        return {"entities": enhanced_entities}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Shutdown handler
@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on shutdown"""
    neo4j_service.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
