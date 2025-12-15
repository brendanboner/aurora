"""Post interaction endpoints."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..services.post_service import PostService
from ..services.preference_service import PreferenceService

router = APIRouter(prefix="/posts", tags=["posts"])
_post_service = PostService()
_preference_service = PreferenceService()


class ReactionRequest(BaseModel):
    user_id: str  # Cognito UUID


@router.post("/{post_id}/like")
async def like_post(post_id: int, request: ReactionRequest) -> dict:
    post = _post_service.get_post(post_id)
    _post_service.store_reaction(request.user_id, post_id, "like")
    _preference_service.apply_topic_feedback(request.user_id, post.tags, delta=0.1)
    _preference_service.update_length_preference(request.user_id, post.content_length)
    return {"status": "liked"}


@router.post("/{post_id}/dislike")
async def dislike_post(post_id: int, request: ReactionRequest) -> dict:
    post = _post_service.get_post(post_id)
    _post_service.store_reaction(request.user_id, post_id, "dislike")
    _preference_service.apply_topic_feedback(request.user_id, post.tags, delta=-0.1)
    _preference_service.update_length_preference(request.user_id, post.content_length)
    return {"status": "disliked"}


@router.delete("/agent/{agent_id}/purge")
async def purge_agent_posts(agent_id: int) -> dict:
    """Delete all posts (and associated sources/reactions) for a specific agent."""
    count = _post_service.purge_agent_posts(agent_id)
    return {"status": "purged", "agent_id": agent_id, "deleted": count}


@router.delete("/purge_all")
async def purge_all_posts() -> dict:
    """Delete all posts (and associated sources/reactions) across all agents."""
    count = _post_service.purge_all_posts()
    return {"status": "purged", "deleted": count}
