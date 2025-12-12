"""User preference models for deterministic personalisation."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel, Field


class UserPreferenceProfile(BaseModel):
    user_id: str
    topic_weights: Dict[str, float] = Field(default_factory=dict)
    agent_affinity: Dict[str, float] = Field(default_factory=dict)
    preferred_length: str = "medium"
    preferred_cadence: str = "per-event"
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
