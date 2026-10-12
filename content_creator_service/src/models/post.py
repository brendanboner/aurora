"""Post models shared across services and API."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class PostSource(BaseModel):
    source_kind: str = Field(..., description="Type of reference (url, neo4j_node, document)")
    source_identifier: Optional[str] = Field(default=None)
    url: Optional[str] = Field(default=None)
    confidence: Optional[float] = Field(default=None)
    title: Optional[str] = Field(default=None)


class PostReaction(BaseModel):
    """User reaction to a post (like/dislike)."""
    post_id: int
    reaction_type: str = Field(..., description="'like' or 'dislike'")
    created_at: datetime


class PostRecord(BaseModel):
    id: int
    agent_id: int
    agent_name: str
    title: str
    body: str
    summary: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    visibility: str = "public"
    importance: str = "normal"
    content_length: str = "medium"
    created_at: datetime
    score: float = 0.0
    sources: List[PostSource] = Field(default_factory=list)


class FeedPost(PostRecord):
    is_following_agent: bool = False
    user_reaction: Optional[str] = None
    normalized_score: Optional[float] = None
    agent_type: Optional[str] = Field(default='shared', description="'shared' or 'personal'")


class FeedPostPublic(BaseModel):
    id: int
    agent_id: int
    agent_name: str
    title: str
    body: str
    summary: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    visibility: str = "public"
    importance: str = "normal"
    content_length: str = "medium"
    created_at: datetime
    sources: List[PostSource] = Field(default_factory=list)
    is_following_agent: bool = False
    user_reaction: Optional[str] = None
    normalized_score: Optional[float] = None
    agent_type: Optional[str] = Field(default='shared', description="'shared' or 'personal'")
