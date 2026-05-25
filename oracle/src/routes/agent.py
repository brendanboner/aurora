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
from src.models.route_plan import RouteId

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["creator-agents"])


def _get_scraper_types_for_orgs(org_names: List[str]) -> List[str]:
    """Map agent organisation names to their Neo4j DataSource scraper_type values.

    This allows AGENT_CONTENT_DISCOVERY to find content ingested from WBA Extranet
    and WFA Causeway even when the Resource→MENTIONS→Organization relationship is
    absent or uses a variant org name.
    """
    scraper_types: List[str] = []
    for org in org_names:
        org_lower = org.lower()
        if "wba" in org_lower or "broadband alliance" in org_lower or "wireless broadband" in org_lower:
            scraper_types.append("wba_extranet")
        if "wi-fi alliance" in org_lower or "wifi alliance" in org_lower or "wfa" in org_lower:
            scraper_types.append("wfa_causeway")
        if "ietf" in org_lower:
            scraper_types.append("ietf")
        if "ieee" in org_lower:
            scraper_types.append("ieee")
    return list(set(scraper_types))


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
        
        # Use AgentRouter to calculate the correct date range based on cadence/perspective,
        # but always execute AGENT_CONTENT_DISCOVERY — the cadence-based templates
        # (WORKGROUP_WEEKLY_RECAP etc.) only cover WFA Causeway (scraper_type='wfa_causeway')
        # and completely miss WBA Extranet content (scraper_type='wba_extranet').
        _, route_plan, confidence = _agent_router.route_for_agent(
            agent_prefs,
            perspective=request.perspective
        )

        # Override: always use AGENT_CONTENT_DISCOVERY so all content sources
        # (WFA Causeway, WBA Extranet, IETF, IEEE, etc.) are searched.
        route_id = RouteId.AGENT_CONTENT_DISCOVERY

        # Get template
        template = _template_registry.get_template(route_id)
        if not template:
            raise HTTPException(
                status_code=500,
                detail=f"No template found for route {route_id.value}"
            )

        # Build base parameters from route plan
        params = template.build_params(route_plan)
        params["limit"] = request.limit

        # CRITICAL FIX: actually pass exclude_ids to Cypher (previously only appended
        # to raw_query string with no effect on the Neo4j query execution).
        params["exclude_ids"] = request.last_content_ids or []

        # Map org names to DataSource scraper types so WBA Extranet and WFA Causeway
        # content is found even when the MENTIONS→Organization relationship is absent.
        params["scraper_types"] = _get_scraper_types_for_orgs(request.expertise_organisations)

        # Priority topics: first 3 topics in the agent's list get a relevance boost
        # (agents should order their expertise_topics by priority, e.g. Wi-Fi 8 before MDU)
        params["priority_topics"] = request.expertise_topics[:3] if request.expertise_topics else []

        # Reuse Oracle's existing Neo4j repository helper instead of relying on
        # a package-level export that is not present in production images.
        repo = get_repo()

        logger.info(
            f"Executing {route_id.value} for agent {request.agent_id}: "
            f"topics={len(request.expertise_topics)}, orgs={len(request.expertise_organisations)}, "
            f"scraper_types={params['scraper_types']}, excluding={len(params['exclude_ids'])} IDs, "
            f"priority_topics={params['priority_topics']}"
        )
        results = repo.client.execute_query(template.cypher, params)

        # Post-process results
        processed = template.execute_post_process(results)

        logger.info(
            f"Agent {request.agent_id} discovery complete: "
            f"route={route_id.value}, "
            f"items={len(processed)}, "
            f"excluded={len(request.last_content_ids)}"
        )

        return AgentContentResponse(
            agent_id=request.agent_id,
            route_used=route_id.value,
            confidence=confidence,
            date_range={
                "start": route_plan.start_date.isoformat() if route_plan.start_date else None,
                "end": route_plan.end_date.isoformat() if route_plan.end_date else None,
                "relative_days": str(route_plan.relative_days) if route_plan.relative_days is not None else None
            },
            content_items=processed,
            rollup_used=False,  # AGENT_CONTENT_DISCOVERY is a live query, not a rollup
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
