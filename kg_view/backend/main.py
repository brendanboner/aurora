"""
FastAPI Backend for Knowledge Graph Visualizer
"""
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
import os
import sys

# Add common directory to path for auth middleware
sys.path.insert(0, '/app/common')
from auth_middleware import get_user_context

from services.neo4j_service import Neo4jService
from services.llm_service import LLMService

# Load environment variables
load_dotenv()

app = FastAPI(
    title="Knowledge Graph Visualizer API",
    description="API for querying and visualizing Neo4j knowledge graph",
    version="1.0.0"
)

# CORS configuration - only for local development
# In production, nginx handles all requests from same origin (no CORS needed)
cors_origins = os.getenv('CORS_ORIGINS', '')
if cors_origins:
    origins = [origin.strip() for origin in cors_origins.split(',') if origin.strip()]
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
async def health_check(user: Optional[dict] = Depends(get_user_context)):
    """Health check endpoint"""
    response = {"status": "healthy", "service": "kg-visualizer-api"}
    if user:
        response["user"] = user.get("email")
    return response


# Graph Statistics
@app.get("/graph/stats")
async def get_graph_stats():
    """Get statistics about the knowledge graph"""
    try:
        stats = neo4j_service.get_graph_stats()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Graph Data
@app.get("/graph/data")
async def get_graph_data(
    limit: int = Query(default=1000, le=10000, description="Maximum nodes to return"),
    skip: int = Query(default=0, ge=0, description="Number of nodes to skip"),
    node_types: Optional[str] = Query(default=None, description="Comma-separated node types to filter"),
    importance_threshold: float = Query(default=0.0, ge=0.0, le=1.0, description="Minimum importance score (0-1)"),
    curated_only: bool = Query(default=False, description="If true, only show high-importance curated nodes")
):
    """Get graph nodes and relationships for visualization with smart filtering"""
    try:
        node_type_list = node_types.split(',') if node_types else None
        data = neo4j_service.get_graph_data(
            limit=limit, 
            node_types=node_type_list, 
            skip=skip,
            importance_threshold=importance_threshold,
            curated_only=curated_only
        )
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Balanced Graph Data (new default for diverse visualization)
@app.get("/graph/balanced-data")
async def get_balanced_graph_data(
    limit: int = Query(default=1000, le=10000, description="Maximum nodes to return across all types"),
    importance_threshold: float = Query(default=0.0, ge=0.0, le=1.0, description="Minimum importance score (0-1)")
):
    """
    Get graph data with balanced sampling across all node types for diverse visualization.
    
    This endpoint ensures representation from Resources, Topics, Events, Organizations, 
    and Persons by proportionally sampling each type rather than taking the first N nodes.
    """
    try:
        data = neo4j_service.get_balanced_graph_data(
            total_limit=limit,
            importance_threshold=importance_threshold
        )
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graph/connected-data")
async def get_connected_graph_data(
    limit: int = Query(default=2000, le=10000, description="Maximum nodes to return across all types"),
    importance_threshold: float = Query(default=0.0, ge=0.0, le=1.0, description="Minimum importance score (0-1)")
):
    """
    Get graph data prioritizing well-connected nodes (hubs) while maintaining type diversity.

    This endpoint creates a more interconnected view by selecting the most connected nodes
    of each type and ensuring their relationships are included, showing actual connection
    patterns in the knowledge graph rather than isolated nodes.
    """
    try:
        data = neo4j_service.get_connected_graph_data(
            total_limit=limit,
            importance_threshold=importance_threshold
        )
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graph/recent-connected")
async def get_recent_connected_graph_data(
    seed_resource_count: int = Query(default=80, ge=10, le=300, description="How many recent Resources to seed the view with"),
    days_back: int = Query(default=120, ge=14, le=365, description="Recency window in days"),
    node_budget: int = Query(default=500, ge=100, le=2000, description="Hard cap on total nodes returned"),
    anchor_orgs: str = Query(default='', description="Comma-separated org names to always include with their 1-hop"),
    anchor_people: str = Query(default='', description="Comma-separated person names/emails to always include with their 1-hop"),
):
    """
    Default view for the KG viewer. Seeds with the most-recent Resources (within
    `days_back`, importance-weighted) and expands 1-hop to their Topics, Orgs,
    People and Events. The result is an interlinked cluster of actually-related
    recent work — not a 3000-event random galaxy.

    `anchor_orgs` / `anchor_people` always appear in the result (with their
    1-hop neighbours), regardless of recency — useful for demos that want the
    viewer's home org and named colleagues visible from the first paint.
    """
    try:
        orgs   = [s.strip() for s in anchor_orgs.split(',')   if s.strip()] if anchor_orgs   else []
        people = [s.strip() for s in anchor_people.split(',') if s.strip()] if anchor_people else []
        data = neo4j_service.get_recent_connected_graph_data(
            seed_resource_count=seed_resource_count,
            days_back=days_back,
            node_budget=node_budget,
            anchor_orgs=orgs,
            anchor_people=people,
        )
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Execute Cypher Query
@app.post("/graph/query")
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
@app.get("/autocomplete/topics")
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


@app.get("/autocomplete/organizations")
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


@app.get("/autocomplete/people")
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


@app.get("/autocomplete/all")
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
@app.get("/graph/neighborhood/{node_id}")
async def get_node_neighborhood(
    node_id: str,  # Changed to str to support Neo4j elementId format
    hops: int = Query(default=2, ge=1, le=3, description="Number of hops"),
    limit: int = Query(default=100, le=500),
    stratified: bool = Query(default=False, description="When hops=1, cap per type for a balanced result")
):
    """Get neighborhood of a node"""
    try:
        data = neo4j_service.get_node_neighborhood(
            node_id=node_id, hops=hops, limit=limit, stratified=stratified
        )
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Entity subgraph
@app.post("/graph/entity-subgraph")
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
@app.get("/graph/search")
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
@app.post("/llm/transform-query")
async def transform_query(request: TransformQueryRequest):
    """Transform natural language query to Cypher using LLM"""
    try:
        result = llm_service.transform_query(request.natural_language_query)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/llm/extract-entities")
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
