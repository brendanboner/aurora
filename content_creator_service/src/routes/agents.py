"""CreatorAgent management endpoints."""

import asyncio
from typing import List
from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel

from ..models.agent import CreatorAgent, CreatorAgentCreate, CreatorAgentUpdate
from ..services.agent_service import AgentService
from ..services.preference_service import PreferenceService
from ..services.scheduler import AgentScheduler

router = APIRouter(prefix="/agents", tags=["agents"])
_agent_service = AgentService()
_preference_service = PreferenceService()
_scheduler = AgentScheduler()


class FollowRequest(BaseModel):
    user_id: str  # Cognito UUID


class AgentPreferenceUpdate(BaseModel):
    user_id: str  # Cognito UUID
    relevance: float  # 0.0 to 1.0
    length_preference: str  # 'short', 'medium', 'long'


class TriggerRequest(BaseModel):
    force: bool = False
    limit: int = 5


@router.get("", response_model=List[CreatorAgent])
async def list_agents(include_disabled: bool = Query(default=False)) -> List[CreatorAgent]:
    return _agent_service.list_agents(include_disabled=include_disabled)


@router.post("", response_model=CreatorAgent)
async def create_agent(payload: CreatorAgentCreate) -> CreatorAgent:
    return _agent_service.create_agent(payload)


@router.get("/user/{user_id}/followed")
async def get_user_followed_agents(user_id: str) -> dict:
    """Get all agents followed by a user with their preference settings."""
    agents = _agent_service.get_followed_agents(user_id)
    profile = _preference_service.get_profile(user_id)
    
    # Combine agent info with preferences
    result = []
    for agent in agents:
        agent_id_str = str(agent["id"])
        result.append({
            **agent,
            "relevance": profile.agent_affinity.get(agent_id_str, 0.5),
            "length_preference": profile.preferred_length,
        })
    
    return {"agents": result, "followed_count": len(result)}


@router.put("/{agent_id}", response_model=CreatorAgent)
async def update_agent(agent_id: int, payload: CreatorAgentUpdate) -> CreatorAgent:
    return _agent_service.update_agent(agent_id, payload)


@router.delete("/{agent_id}")
async def delete_agent(agent_id: int) -> dict:
    _agent_service.delete_agent(agent_id)
    return {"status": "deleted"}


@router.post("/{agent_id}/follow")
async def follow_agent(agent_id: int, request: FollowRequest) -> dict:
    _agent_service.follow_agent(request.user_id, agent_id)
    _preference_service.adjust_agent_affinity(request.user_id, agent_id, delta=0.1)
    return {"status": "followed"}


@router.post("/{agent_id}/unfollow")
async def unfollow_agent(agent_id: int, request: FollowRequest) -> dict:
    _agent_service.unfollow_agent(request.user_id, agent_id)
    _preference_service.adjust_agent_affinity(request.user_id, agent_id, delta=-0.1)
    return {"status": "unfollowed"}


@router.put("/{agent_id}/preferences")
async def update_agent_preferences(agent_id: int, request: AgentPreferenceUpdate) -> dict:
    """Update user's preference settings for a specific agent (relevance and length)."""
    # Update agent affinity (relevance)
    _preference_service.set_agent_affinity(request.user_id, agent_id, request.relevance)
    
    # Update preferred length
    _preference_service.update_profile(
        request.user_id,
        preferred_length=request.length_preference
    )
    
    return {
        "status": "updated",
        "agent_id": agent_id,
        "relevance": request.relevance,
        "length_preference": request.length_preference
    }


@router.post("/{agent_id}/trigger")
async def trigger_agent_run(agent_id: int, request: TriggerRequest = Body(...)) -> dict:
    """Force a CreatorAgent to run immediately."""
    try:
        post_id, event = await asyncio.to_thread(
            _scheduler.run_agent_once,
            agent_id,
            force=request.force,
            limit=request.limit,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if post_id:
        return {
            "status": "success",
            "post_id": post_id,
            "event_title": event.title if event else None,
        }
    return {
        "status": "no_content",
        "message": "Agent processed but did not generate a post. Check logs for details.",
    }
