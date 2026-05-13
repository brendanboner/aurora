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
    discovery_tolerance: float = Field(
        default=0.5,
        description="How willing to explore adjacent topics (0=strict, 1=exploratory)",
        ge=0.0,
        le=1.0,
    )
    cadence_window_days: int = Field(
        default=7,
        description="Time window in days for considering events",
        ge=1,
        le=365,
    )
    llm_temperature_override: Optional[float] = Field(
        default=None,
        description="Override LLM temperature for this agent (0.0-1.0). If None, uses system default",
        ge=0.0,
        le=1.0,
    )
    teams_slug: Optional[str] = Field(
        default=None,
        description="Teams bot slug for @aurora-<slug> routing (e.g. aurora-wba-wifi-design-wg)",
        pattern=r"^aurora-[a-z0-9-]+$",
    )
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
    discovery_tolerance: Optional[float] = None
    cadence_window_days: Optional[int] = None
    llm_temperature_override: Optional[float] = None
    teams_slug: Optional[str] = None
    enabled: Optional[bool] = None


class CreatorAgent(CreatorAgentBase):
    id: int
    created_at: datetime
    updated_at: datetime
    last_run_at: Optional[datetime] = None
    last_generated_at: Optional[datetime] = None
    last_event_cursor: Optional[str] = None
    persona_version: int = Field(default=1, description="Version number for persona, increments on updates")
    persona_updated_at: Optional[datetime] = Field(default=None, description="Timestamp of last persona modification")

    class Config:
        from_attributes = True
