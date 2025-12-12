"""Feed endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..models.feed import FeedResponse
from ..services.feed_service import FeedService
from ..settings import get_settings

router = APIRouter(prefix="/feed", tags=["feed"])
_feed_service = FeedService()
_settings = get_settings()


@router.get("", response_model=FeedResponse)
async def get_feed(
    user_id: int,
    limit: int = Query(default=20, ge=1),
    offset: int = Query(default=0, ge=0),
) -> FeedResponse:
    limit = min(limit, _settings.max_feed_page_size)
    return _feed_service.fetch_feed(user_id=user_id, limit=limit, offset=offset)
