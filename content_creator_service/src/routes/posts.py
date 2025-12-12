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
    user_id: int


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
