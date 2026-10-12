"""Feed response objects."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from .post import FeedPostPublic


class FeedResponse(BaseModel):
    user_id: str  # Cognito UUID
    posts: List[FeedPostPublic]
    next_offset: Optional[int]
