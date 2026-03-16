"""API endpoints for creator agent integration with Oracle.

Provides content discovery endpoints optimized for creator agents,
leveraging Oracle's fast engine, rollups, and query templates.
"""

import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field

from src.services.agent_adapter import (
    AgentRouter,
    CreatorAgentPreferences,
    create_agent_preferences_from_dict
)
from src.services.keyword_retriever import get_repo
from src.services.query_template_registry import QueryTemplateRegistry
from src.engines.fast_engine import FastEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["creator-agents"])


class AgentContentRequest(BaseModel):
    """Request model for agent content discovery."""
    
    agent_id: str = Field(..., description="Unique agent identifier")
    agent_name: str = Field(..., description="Agent display name")
    expertise_topics: List[str] = Field(default_factory=list, description="Topics agent focuses on")
    expertise_organisations: List[str] = Field(default_factory=list, description="Organizations agent tracks")
    cadence_days: Optional[int] = Field(7, description="Days between content generation", ge=1, le=90)
    discovery_tolerance: float = Field(0.5, description="0.0=strict, 1.0=exploratory", ge=0.0, le=1.0)
    last_content_ids: List[str] = Field(default_factory=list, description="Previously used content IDs")
    perspective: Optional[str] = Field(None, description="Content angle: news, events, analysis, trends")
    limit: int = Field(20, description="Maximum items to return", ge=1, le=100)


class AgentContentResponse(BaseModel):
    """Response model for agent content discovery."""
    
    agent_id: str
    route_used: str
    confidence: float
    date_range: Dict[str, str]
    content_items: List[Dict[str, Any]]
    rollup_used: bool
    excluded_count: int


# Initialize services
_agent_router = AgentRouter()
_template_registry = QueryTemplateRegistry()
_fast_engine = FastEngine()


@router.post("/discover", response_model=AgentContentResponse)
async def discover_content(
    request: AgentContentRequest,
    x_user_id: Optional[str] = Header(None)
) -> AgentContentResponse:
    """
    Discover content for creator agent using Oracle's fast engine.
    
    This endpoint:
    1. Converts agent preferences to Oracle routing format
    2. Routes to appropriate query template (daily/weekly/monthly rollups)
    3. Applies deduplication based on last_content_ids
    4. Returns relevance-scored content with full context
    
    The agent can then apply its persona and voice to generate posts.
    """
    try:
        logger.info(f"Content discovery request for agent {request.agent_id} ({request.agent_name})")
        
        # Create agent preferences
        agent_prefs = CreatorAgentPreferences(
            agent_id=request.agent_id,
            agent_name=request.agent_name,
            expertise_topics=request.expertise_topics,
            expertise_organisations=request.expertise_organisations,
            cadence_days=request.cadence_days,
            discovery_tolerance=request.discovery_tolerance,
            last_content_ids=request.last_content_ids
        )
        
        # Route to appropriate template
        route_id, route_plan, confidence = _agent_router.route_for_agent(
            agent_prefs,
            perspective=request.perspective
        )
        
        # Add exclusion IDs to raw query for template parameter building
        if request.last_content_ids:
            route_plan.raw_query += f" exclude_ids:[{','.join(request.last_content_ids)}]"
        
        # Get template
        template = _template_registry.get_template(route_id)
        if not template:
            raise HTTPException(
                status_code=500,
                detail=f"No template found for route {route_id.value}"
            )
        
        # Build parameters
        params = template.build_params(route_plan)
        params["limit"] = request.limit
        
        # Reuse Oracle's existing Neo4j repository helper instead of relying on
        # a package-level export that is not present in production images.
        repo = get_repo()
        
        logger.info(f"Executing {route_id.value} with params: topics={len(request.expertise_topics)}, orgs={len(request.expertise_organisations)}")
        results = repo.client.execute_query(template.cypher, params)
        
        # Post-process results
        processed = template.execute_post_process(results)
        
        # Check if rollup was used (indicated by source_type or rollup_id in results)
        rollup_used = any(
            r.get("source_type") == "rollup" or r.get("rollup_id") 
            for r in processed
        )
        
        logger.info(
            f"Agent {request.agent_id} discovery complete: "
            f"route={route_id.value}, "
            f"items={len(processed)}, "
            f"rollup_used={rollup_used}, "
            f"excluded={len(request.last_content_ids)}"
        )
        
        return AgentContentResponse(
            agent_id=request.agent_id,
            route_used=route_id.value,
            confidence=confidence,
            date_range={
                "start": route_plan.start_date.isoformat() if route_plan.start_date else None,
                "end": route_plan.end_date.isoformat() if route_plan.end_date else None,
                "relative_days": route_plan.relative_days
            },
            content_items=processed,
            rollup_used=rollup_used,
            excluded_count=len(request.last_content_ids)
        )
        
    except Exception as e:
        logger.error(f"Agent content discovery failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Content discovery failed: {str(e)}")


@router.get("/health")
async def health_check():
    """Health check for agent integration."""
    return {
        "status": "healthy",
        "templates_registered": len(_template_registry.templates),
        "agent_router": "initialized"
    }
