"""UserAgent model definitions for personal AI agents."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class UserAgentBase(BaseModel):
    """Base model for user agent creation/updates."""
    name: str = Field(..., description="Agent name (unique per user)")
    project_description: str = Field(..., description="Natural language description of the project to monitor")
    scope_notes: Optional[str] = Field(default=None, description="Additional constraints and preferences")
    cadence: str = Field(default="daily", description="Content generation frequency: 'daily' or 'weekly'")
    show_in_feed: bool = Field(default=True, description="Show generated content in user's feed")
    enabled: bool = Field(default=True, description="Agent is active")


class UserAgentCreate(UserAgentBase):
    """Payload for creating a new user agent."""
    pass


class UserAgentUpdate(BaseModel):
    """Payload for updating an existing user agent."""
    name: Optional[str] = None
    project_description: Optional[str] = None
    scope_notes: Optional[str] = None
    cadence: Optional[str] = None
    show_in_feed: Optional[bool] = None
    enabled: Optional[bool] = None


class UserAgentFeedback(BaseModel):
    """Feedback on generated content to improve agent."""
    agent_id: int = Field(..., description="User agent ID")
    post_id: Optional[int] = Field(default=None, description="Optional post ID this feedback relates to")
    feedback_text: str = Field(..., description="Free-form feedback to improve content generation")


class UserAgent(UserAgentBase):
    """Complete user agent with all fields."""
    id: int
    user_id: str
    teams_slug: Optional[str] = None   # URL-safe slug for Teams @mentions

    # AI-generated fields
    expertise_topics: List[str] = Field(default_factory=list)
    expertise_organisations: List[str] = Field(default_factory=list)
    tone_style: str = Field(default="analytical")
    persona: Optional[str] = None
    
    # Feedback history (list of feedback entries)
    feedback_history: List[dict] = Field(default_factory=list)
    
    # Timestamps
    created_at: datetime
    updated_at: datetime
    last_run_at: Optional[datetime] = None
    last_generated_at: Optional[datetime] = None

    # Error state — set when generation fails, cleared on success
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
