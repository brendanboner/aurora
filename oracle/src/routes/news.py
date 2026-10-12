"""GET /news — personalised "what's new since you last checked" brief.

The brief draws from the user's joined subscriptions when they have any;
otherwise from their profile preferences (topics / organisations /
domains). Result is short-cached in Redis so repeated calls in quick
succession share work.

The route updates ``last_requested_at`` only when ``mark_seen=true``
(the default), so polling clients can read the brief without resetting
the high-water mark by passing ``?mark_seen=false``.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from common.auth_middleware import get_user_context, require_user_context
from src.services.news import build_brief, mark_seen

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["news"])


@router.get("/news")
@require_user_context
async def get_news(
    mark_seen_flag: bool = Query(True, alias="mark_seen"),
    force_refresh: bool = Query(False, alias="refresh"),
    user: Optional[dict] = Depends(get_user_context),
) -> dict:
    """Return the caller's news brief.

    Query params:
      mark_seen (default true): bump ``last_requested_at`` after building
        the brief, so the next call only surfaces newer items.
      refresh (default false): bypass the brief cache and recompute.
    """
    user_id = (user or {}).get("user_id") if user else None
    if not user_id:
        return {"items": [], "since": None, "source": "none", "datasource_count": 0}

    brief = await build_brief(str(user_id), force_refresh=force_refresh)

    if mark_seen_flag:
        await mark_seen(str(user_id))

    response = brief.to_dict()
    response["user_id"] = str(user_id)
    logger.info(
        f"news: served brief for user={user_id} "
        f"items={len(brief.items)} source={brief.source} since={brief.since}"
    )
    return response
