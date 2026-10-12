"""Expose inferred preference profiles."""
from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ..models.preferences import UserPreferenceProfile
from ..services.preference_service import PreferenceService

router = APIRouter(prefix="/preferences", tags=["preferences"])
_preference_service = PreferenceService()


class PreferenceUpdateRequest(BaseModel):
    preferred_length: Optional[str] = None
    preferred_cadence: Optional[str] = None
    topic_weights: Optional[Dict[str, float]] = None
    agent_affinity: Optional[Dict[str, float]] = None


@router.get("/{user_id}", response_model=UserPreferenceProfile)
async def get_preference_profile(user_id: str) -> UserPreferenceProfile:
    return _preference_service.get_profile(user_id)


@router.put("/{user_id}", response_model=UserPreferenceProfile)
async def update_preference_profile(user_id: str, payload: PreferenceUpdateRequest) -> UserPreferenceProfile:
    return _preference_service.update_profile(
        user_id,
        preferred_length=payload.preferred_length,
        preferred_cadence=payload.preferred_cadence,
        topic_weights=payload.topic_weights,
        agent_affinity=payload.agent_affinity,
    )
