"""CreatorAgent model definitions."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class CreatorAgentBase(BaseModel):
    name: str = Field(..., description="Unique agent handle")
    description: Optional[str] = Field(default=None, description="Persona overview")
    persona: Optional[str] = Field(default=None, description="Detailed long-form persona script")
    expertise_topics: List[str] = Field(default_factory=list)
    expertise_organisations: List[str] = Field(default_factory=list)
    expertise_standards: List[str] = Field(default_factory=list)
    tone_style: str = Field(default="analytical")
    posting_cadence: str = Field(default="per-event")
    content_length_preference: str = Field(default="medium")
    importance_threshold: str = Field(default="normal")
    enabled: bool = True


class CreatorAgentCreate(CreatorAgentBase):
    pass


class CreatorAgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    persona: Optional[str] = None
    expertise_topics: Optional[List[str]] = None
    expertise_organisations: Optional[List[str]] = None
    expertise_standards: Optional[List[str]] = None
    tone_style: Optional[str] = None
    posting_cadence: Optional[str] = None
    content_length_preference: Optional[str] = None
    importance_threshold: Optional[str] = None
    enabled: Optional[bool] = None


class CreatorAgent(CreatorAgentBase):
    id: int
    created_at: datetime
    updated_at: datetime
    last_run_at: Optional[datetime] = None
    last_generated_at: Optional[datetime] = None
    last_event_cursor: Optional[str] = None

    class Config:
        from_attributes = True
