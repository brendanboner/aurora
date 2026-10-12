"""Admin configuration routes for content quality settings."""
from __future__ import annotations

import logging
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/config", tags=["admin"])


class ContentQualityConfig(BaseModel):
    """Configuration model for content quality and diversity settings."""
    
    diversity_similarity_threshold: float = Field(
        ...,
        description="Jaccard similarity threshold for filtering similar articles (0.0-1.0). "
                    "Higher values = stricter filtering (more duplicates removed)",
        ge=0.0,
        le=1.0,
    )
    min_relevance_score_default: float = Field(
        ...,
        description="Default minimum relevance score for article selection (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )
    max_topics_per_article: int = Field(
        ...,
        description="Maximum number of topics per article before filtering as generic",
        ge=1,
    )
    max_articles_per_domain: int = Field(
        ...,
        description="Maximum articles from the same domain in a single post",
        ge=1,
    )
    temporal_window_days_default: int = Field(
        ...,
        description="Default temporal window in days for article selection",
        ge=1,
        le=365,
    )


@router.get("/content-quality", response_model=ContentQualityConfig)
async def get_content_quality_config() -> ContentQualityConfig:
    """
    Get current content quality and diversity configuration.
    
    Returns settings that control how articles are selected and filtered
    for post generation, including similarity thresholds and quality limits.
    """
    settings = get_settings()
    
    return ContentQualityConfig(
        diversity_similarity_threshold=settings.diversity_similarity_threshold,
        min_relevance_score_default=settings.min_relevance_score_default,
        max_topics_per_article=settings.max_topics_per_article,
        max_articles_per_domain=settings.max_articles_per_domain,
        temporal_window_days_default=settings.temporal_window_days_default,
    )


@router.put("/content-quality", response_model=ContentQualityConfig)
async def update_content_quality_config(config: ContentQualityConfig) -> ContentQualityConfig:
    """
    Update content quality and diversity configuration.
    
    Note: This updates the runtime settings but does NOT persist across
    service restarts. To persist changes, update environment variables
    or configuration files.
    
    Configuration parameters:
    - **diversity_similarity_threshold**: Controls how aggressively similar articles 
      are filtered. Range 0.0-1.0. Recommended: 0.6-0.8
      - 0.5: Very loose (keeps most articles)
      - 0.7: Balanced (default)
      - 0.9: Very strict (removes many similar articles)
    
    - **min_relevance_score_default**: Minimum quality threshold for articles.
      Range 0.0-1.0. Recommended: 0.2-0.4
      - 0.2: Permissive (includes more articles)
      - 0.3: Balanced (default)
      - 0.5: Strict (only high-quality focused articles)
    
    - **max_topics_per_article**: Filter out generic aggregation articles.
      Recommended: 15-25
      - Lower values = more focused content
      - Higher values = allow broader coverage
    
    - **max_articles_per_domain**: Limit articles from single source.
      Recommended: 2-3
      - 1: Maximum diversity
      - 2: Balanced (default)
      - 3+: Allow source dominance
    
    - **temporal_window_days_default**: How far back to look for articles.
      Range 1-365 days. Recommended: 60-120
      - 30: Recent news only
      - 90: Balanced (default)
      - 180: Include older historical content
    """
    settings = get_settings()
    
    # Update runtime settings
    settings.diversity_similarity_threshold = config.diversity_similarity_threshold
    settings.min_relevance_score_default = config.min_relevance_score_default
    settings.max_topics_per_article = config.max_topics_per_article
    settings.max_articles_per_domain = config.max_articles_per_domain
    settings.temporal_window_days_default = config.temporal_window_days_default
    
    logger.info(
        "Content quality config updated: similarity_threshold=%.2f, min_relevance=%.2f, "
        "max_topics=%d, max_per_domain=%d, window_days=%d",
        config.diversity_similarity_threshold,
        config.min_relevance_score_default,
        config.max_topics_per_article,
        config.max_articles_per_domain,
        config.temporal_window_days_default,
    )
    
    return config


@router.post("/content-quality/reset")
async def reset_content_quality_config() -> Dict[str, Any]:
    """
    Reset content quality configuration to default values.
    
    This resets runtime settings to the defaults specified in the Settings class.
    """
    settings = get_settings()
    
    # Reset to class defaults
    from ..settings import Settings
    defaults = Settings()
    
    settings.diversity_similarity_threshold = defaults.diversity_similarity_threshold
    settings.min_relevance_score_default = defaults.min_relevance_score_default
    settings.max_topics_per_article = defaults.max_topics_per_article
    settings.max_articles_per_domain = defaults.max_articles_per_domain
    settings.temporal_window_days_default = defaults.temporal_window_days_default
    
    logger.info("Content quality config reset to defaults")
    
    return {
        "message": "Configuration reset to defaults",
        "config": ContentQualityConfig(
            diversity_similarity_threshold=settings.diversity_similarity_threshold,
            min_relevance_score_default=settings.min_relevance_score_default,
            max_topics_per_article=settings.max_topics_per_article,
            max_articles_per_domain=settings.max_articles_per_domain,
            temporal_window_days_default=settings.temporal_window_days_default,
        )
    }
