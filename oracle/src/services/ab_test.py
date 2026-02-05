"""A/B testing logic for fast pipeline rollout."""

import hashlib
import logging
from typing import Optional
from src.settings import settings

logger = logging.getLogger(__name__)


def should_use_fast_pipeline(user_id: Optional[str], pipeline_override: Optional[str] = None) -> bool:
    """
    Determine if a user should use the fast pipeline based on A/B test assignment or override.
    
    Uses deterministic hash-based bucketing to ensure consistent assignment
    for the same user across requests, unless overridden by user selection.
    
    Args:
        user_id: User identifier (Cognito UUID or similar)
        pipeline_override: Optional user override ('fast' or 'baseline')
        
    Returns:
        True if user should use fast pipeline, False for baseline
    """
    # Check for explicit override first (beta feature for user testing)
    if pipeline_override is not None:
        use_fast = pipeline_override.lower() == "fast"
        logger.info(
            f"Pipeline override: user={user_id[:8] if user_id else 'anonymous'}... "
            f"override={pipeline_override} -> {'fast' if use_fast else 'baseline'}"
        )
        return use_fast
    
    # Fast pipeline must be enabled
    if not settings.fast_pipeline_enabled:
        return False
    
    # If no user_id, default to baseline
    if not user_id:
        logger.debug("No user_id provided, using baseline pipeline")
        return False
    
    # Rollout percentage controls exposure
    rollout_pct = settings.fast_pipeline_rollout_percentage
    
    # 0% = nobody gets fast pipeline
    if rollout_pct <= 0:
        return False
    
    # 100% = everyone gets fast pipeline
    if rollout_pct >= 100:
        return True
    
    # Hash user ID to get consistent bucket assignment (0-99)
    user_hash = hashlib.sha256(user_id.encode()).hexdigest()
    bucket = int(user_hash[:8], 16) % 100
    
    # User is in fast pipeline if their bucket < rollout percentage
    use_fast = bucket < rollout_pct
    
    logger.debug(
        f"A/B test assignment: user={user_id[:8]}... bucket={bucket} "
        f"rollout={rollout_pct}% -> {'fast' if use_fast else 'baseline'}"
    )
    
    return use_fast


def get_pipeline_name(user_id: Optional[str]) -> str:
    """
    Get the pipeline name that should be used for a user.
    
    Args:
        user_id: User identifier
        
    Returns:
        "fast" or "baseline"
    """
    return "fast" if should_use_fast_pipeline(user_id) else "baseline"
