"""Feed response objects."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from .post import FeedPost


class FeedResponse(BaseModel):
    user_id: int
    posts: List[FeedPost]
    next_offset: Optional[int]
