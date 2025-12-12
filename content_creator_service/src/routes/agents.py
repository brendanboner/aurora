"""CreatorAgent management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..models.agent import CreatorAgent, CreatorAgentCreate, CreatorAgentUpdate
from ..services.agent_service import AgentService
from ..services.preference_service import PreferenceService

router = APIRouter(prefix="/agents", tags=["agents"])
_agent_service = AgentService()
_preference_service = PreferenceService()


class FollowRequest(BaseModel):
    user_id: int


@router.get("", response_model=list[CreatorAgent])
async def list_agents(include_disabled: bool = Query(default=False)) -> list[CreatorAgent]:
    return _agent_service.list_agents(include_disabled=include_disabled)


@router.post("", response_model=CreatorAgent)
async def create_agent(payload: CreatorAgentCreate) -> CreatorAgent:
    return _agent_service.create_agent(payload)


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
    _preference_service.adjust_agent_affinity(request.user_id, agent_id, delta=-0.2)
    return {"status": "unfollowed"}
