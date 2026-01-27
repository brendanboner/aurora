"""Admin configuration routes for Oracle query settings."""
from __future__ import annotations

import logging
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/config", tags=["admin"])


class QuerySettingsConfig(BaseModel):
    """Configuration model for Oracle query settings."""
    
    # Fast Pipeline
    fast_pipeline_enabled: bool = Field(
        default=False,
        description="Enable fast retrieval pipeline"
    )
    fast_pipeline_rollout_percentage: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Percentage of users in fast pipeline (0-100)"
    )
    fast_pipeline_shadow_mode: bool = Field(
        default=False,
        description="Run fast pipeline in shadow mode (log only, return baseline)"
    )
    
    # Confidence & Quality
    fast_confidence_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Minimum confidence to return fast result"
    )
    
    # Cache Settings (converted to user-friendly units)
    fast_cache_plan_ttl_hours: int = Field(
        default=24,
        ge=1,
        le=48,
        description="Route plan cache TTL in hours"
    )
    fast_cache_result_ttl_minutes: int = Field(
        default=60,
        ge=5,
        le=120,
        description="Retrieval result cache TTL in minutes"
    )
    fast_cache_answer_ttl_minutes: int = Field(
        default=60,
        ge=5,
        le=120,
        description="Final answer cache TTL in minutes"
    )
    
    # Deep Dive
    fast_deep_dive_enabled: bool = Field(
        default=True,
        description="Enable deep dive retrieval for low confidence queries"
    )


@router.get("/query-settings", response_model=QuerySettingsConfig)
async def get_query_settings_config() -> QuerySettingsConfig:
    """Retrieve current Oracle query settings."""
    try:
        return QuerySettingsConfig(
            fast_pipeline_enabled=settings.fast_pipeline_enabled,
            fast_pipeline_rollout_percentage=settings.fast_pipeline_rollout_percentage,
            fast_pipeline_shadow_mode=settings.fast_pipeline_shadow_mode,
            fast_confidence_threshold=settings.fast_confidence_threshold,
            fast_cache_plan_ttl_hours=settings.fast_cache_plan_ttl // 3600,
            fast_cache_result_ttl_minutes=settings.fast_cache_result_ttl // 60,
            fast_cache_answer_ttl_minutes=settings.fast_cache_answer_ttl // 60,
            fast_deep_dive_enabled=settings.fast_deep_dive_enabled,
        )
    except Exception as e:
        logger.error(f"Error retrieving query settings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve query settings"
        )


@router.put("/query-settings", response_model=QuerySettingsConfig)
async def update_query_settings_config(config: QuerySettingsConfig) -> QuerySettingsConfig:
    """Update Oracle query settings (runtime only, not persisted to .env)."""
    try:
        # Update settings in memory
        settings.fast_pipeline_enabled = config.fast_pipeline_enabled
        settings.fast_pipeline_rollout_percentage = config.fast_pipeline_rollout_percentage
        settings.fast_pipeline_shadow_mode = config.fast_pipeline_shadow_mode
        settings.fast_confidence_threshold = config.fast_confidence_threshold
        settings.fast_cache_plan_ttl = config.fast_cache_plan_ttl_hours * 3600
        settings.fast_cache_result_ttl = config.fast_cache_result_ttl_minutes * 60
        settings.fast_cache_answer_ttl = config.fast_cache_answer_ttl_minutes * 60
        settings.fast_deep_dive_enabled = config.fast_deep_dive_enabled
        
        logger.info(
            f"Query settings updated: fast_pipeline_enabled={config.fast_pipeline_enabled}, "
            f"rollout={config.fast_pipeline_rollout_percentage}%, "
            f"shadow_mode={config.fast_pipeline_shadow_mode}, "
            f"confidence_threshold={config.fast_confidence_threshold}"
        )
        
        return config
    except Exception as e:
        logger.error(f"Error updating query settings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update query settings"
        )


@router.post("/query-settings/reset")
async def reset_query_settings_config() -> Dict[str, Any]:
    """Reset Oracle query settings to default values."""
    try:
        # Create default config
        default_config = QuerySettingsConfig()
        
        # Update settings to defaults
        settings.fast_pipeline_enabled = default_config.fast_pipeline_enabled
        settings.fast_pipeline_rollout_percentage = default_config.fast_pipeline_rollout_percentage
        settings.fast_pipeline_shadow_mode = default_config.fast_pipeline_shadow_mode
        settings.fast_confidence_threshold = default_config.fast_confidence_threshold
        settings.fast_cache_plan_ttl = default_config.fast_cache_plan_ttl_hours * 3600
        settings.fast_cache_result_ttl = default_config.fast_cache_result_ttl_minutes * 60
        settings.fast_cache_answer_ttl = default_config.fast_cache_answer_ttl_minutes * 60
        settings.fast_deep_dive_enabled = default_config.fast_deep_dive_enabled
        
        logger.info("Query settings reset to defaults")
        
        return {
            "message": "Query settings reset to default values",
            "config": default_config
        }
    except Exception as e:
        logger.error(f"Error resetting query settings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset query settings"
        )
