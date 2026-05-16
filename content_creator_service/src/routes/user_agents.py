"""User agent management endpoints for personal AI agents."""
from __future__ import annotations

import asyncio
import logging
from typing import List

from fastapi import APIRouter, Header, HTTPException, status

from ..models.user_agent import (
    UserAgent,
    UserAgentCreate,
    UserAgentFeedback,
    UserAgentUpdate,
)
from ..services.user_agent_service import UserAgentService
from ..services.generation_service import GenerationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user_agents", tags=["user-agents"])
_user_agent_service = UserAgentService()
_generation_service = GenerationService()


@router.get("", response_model=List[UserAgent])
async def get_user_agents(x_user_id: str = Header(..., alias="X-User-Id")) -> List[UserAgent]:
    """Get all personal agents for the authenticated user."""
    try:
        return _user_agent_service.get_user_agents(x_user_id)
    except Exception as e:
        logger.error(f"Failed to get user agents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve user agents: {str(e)}"
        )


@router.post("", response_model=UserAgent)
async def create_user_agent(
    payload: UserAgentCreate,
    x_user_id: str = Header(..., alias="X-User-Id")
) -> UserAgent:
    """Create a new personal agent with AI-extracted metadata from project description."""
    try:
        agent = _user_agent_service.create_from_description(x_user_id, payload)
        logger.info(f"Created user agent {agent.id} for user {x_user_id}")
        return agent
    except Exception as e:
        logger.error(f"Failed to create user agent: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create user agent: {str(e)}"
        )


@router.put("/{agent_id}", response_model=UserAgent)
async def update_user_agent(
    agent_id: int,
    payload: UserAgentUpdate,
    x_user_id: str = Header(..., alias="X-User-Id")
) -> UserAgent:
    """Update a personal agent. Re-runs AI extraction if description changed."""
    try:
        agent = _user_agent_service.update_user_agent(x_user_id, agent_id, payload)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User agent {agent_id} not found or access denied"
            )
        logger.info(f"Updated user agent {agent_id} for user {x_user_id}")
        return agent
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update user agent: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user agent: {str(e)}"
        )


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_agent(
    agent_id: int,
    x_user_id: str = Header(..., alias="X-User-Id")
) -> None:
    """Delete a personal agent and all its generated posts."""
    try:
        deleted = _user_agent_service.delete_user_agent(x_user_id, agent_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User agent {agent_id} not found or access denied"
            )
        logger.info(f"Deleted user agent {agent_id} for user {x_user_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete user agent: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete user agent: {str(e)}"
        )


@router.post("/feedback", response_model=UserAgent)
async def submit_feedback(
    payload: UserAgentFeedback,
    x_user_id: str = Header(..., alias="X-User-Id")
) -> UserAgent:
    """Submit feedback to improve a personal agent. AI analyzes and applies improvements."""
    try:
        agent = _user_agent_service.process_feedback(
            user_id=x_user_id,
            agent_id=payload.agent_id,
            feedback_text=payload.feedback_text,
            post_id=payload.post_id
        )
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User agent {payload.agent_id} not found or access denied"
            )
        logger.info(f"Processed feedback for user agent {payload.agent_id}")
        return agent
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process feedback: {str(e)}"
        )


@router.post("/{agent_id}/generate")
async def trigger_manual_generation(
    agent_id: int,
    x_user_id: str = Header(..., alias="X-User-Id")
) -> dict:
    """Manually trigger content generation for a personal agent."""
    try:
        # Verify ownership
        agent = _user_agent_service.get_user_agent(x_user_id, agent_id)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User agent {agent_id} not found or access denied"
            )
        
        # Convert UserAgent to dict format expected by generation service
        agent_dict = {
            'id': agent.id,
            'user_id': agent.user_id,
            'name': agent.name,
            'persona': agent.persona,
            'expertise_topics': agent.expertise_topics,
            'expertise_organisations': agent.expertise_organisations,
            'tone_style': agent.tone_style,
            'cadence': agent.cadence,
            'feedback_history': agent.feedback_history,
            'agent_type': 'personal'
        }
        
        # Generation performs blocking I/O and internally manages async Oracle discovery.
        result = await asyncio.to_thread(
            _generation_service.generate_for_user_agent,
            agent_dict,
        )
        
        if result:
            logger.info(f"Manual generation triggered for agent {agent_id}, generated post {result.get('post_id')}")
            return {
                "status": "success",
                "message": "Content generated successfully",
                "post_id": result.get('post_id'),
                "post": result.get('post')
            }
        else:
            logger.warning(f"Manual generation for agent {agent_id} returned no content")
            return {
                "status": "no_content",
                "message": "No new content found to generate"
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger manual generation: {e}")
        # Persist the error so the UI can surface a fix notification
        try:
            _user_agent_service.mark_error(agent_id, str(e))
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate content: {str(e)}"
        )


@router.post("/{agent_id}/fix-prompt")
async def fix_agent_prompt(
    agent_id: int,
    x_user_id: str = Header(..., alias="X-User-Id"),
) -> dict:
    """Use the LLM to rewrite the agent description to avoid content-filter issues,
    apply it, clear the error state, and return the new description."""
    agent = _user_agent_service.get_user_agent(x_user_id, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    from ..llm_client import get_llm_client
    llm = get_llm_client()

    system_prompt = (
        "You are a helpful editor. Rewrite the user's AI agent description so it is "
        "clear, professional, and avoids any language that could be misread as a "
        "jailbreak or prompt injection (e.g. 'ignore previous instructions', 'act as', "
        "role-play framing, or aggressive instruction-style directives). "
        "Keep the intent and topics identical. Return ONLY the rewritten description "
        "with no preamble."
    )
    user_prompt = f"Original description:\n{agent.project_description or agent.persona or ''}"

    try:
        result = llm.generate(system_prompt, user_prompt, temperature_override=0.3)
        new_description = (result or {}).get("body") or (result or {}).get("summary") or ""
        if not new_description and isinstance(result, str):
            new_description = result
        if not new_description:
            raise ValueError("LLM returned empty rewrite")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not generate fix: {e}")

    # Apply the rewrite and clear the error
    from ..models.user_agent import UserAgentUpdate
    _user_agent_service.update_user_agent(
        x_user_id, agent_id,
        UserAgentUpdate(project_description=new_description)
    )
    _user_agent_service.clear_error(agent_id)

    return {"new_description": new_description}
