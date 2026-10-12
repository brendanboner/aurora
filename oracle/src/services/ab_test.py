"""Pipeline selection — Fast-first with baseline fallback, or baseline-only.

This module used to implement deterministic A/B-test user-bucketing via SHA
hashing of the user_id. That added a `pipeline=unspecified` bucket of users
whose UUIDs hashed below the rollout cutoff and, more importantly, made
eval metrics noisy because three different code paths were producing
answers that all landed in the same `oracle_query_history` sample.

We now run one of two modes, controlled by `settings.oracle_pipeline_mode`:

  - "auto"     (default): every request goes through the fast pipeline. The
                          existing `fast_fallback_to_baseline` handles the
                          fast→baseline cascade when fast errs or returns
                          insufficient docs.
  - "baseline":           fast pipeline is bypassed entirely. Every request
                          goes through baseline. Useful for evaluation
                          runs that want a clean baseline-only signal.

A per-request `pipeline_override` (from QueryOptions) still wins over the
mode setting so individual eval/debug calls can force one path or the other.
"""

import logging
from typing import Optional

from src.settings import settings

logger = logging.getLogger(__name__)


def should_use_fast_pipeline(
    user_id: Optional[str] = None,
    pipeline_override: Optional[str] = None,
) -> bool:
    """Decide whether to attempt the fast pipeline for this request.

    Returns True for fast (with fallback handled by the caller); False for
    baseline-only. The `user_id` parameter is kept on the signature for
    backward compatibility with existing call sites but is no longer used
    in the decision — bucketing by user_id was the A/B test machinery we
    just removed.
    """
    # Explicit per-request override always wins.
    if pipeline_override is not None:
        choice = pipeline_override.lower()
        if choice == "fast":
            return True
        if choice == "baseline":
            return False
        logger.warning(
            "Unknown pipeline_override=%r — falling through to mode setting",
            pipeline_override,
        )

    # Master kill switch — if fast is disabled outright, force baseline.
    if not getattr(settings, "fast_pipeline_enabled", True):
        return False

    mode = (getattr(settings, "oracle_pipeline_mode", "auto") or "auto").lower()
    if mode == "baseline":
        return False
    # Default ("auto" or any other value) = fast with downstream fallback.
    return True


def get_pipeline_name(user_id: Optional[str] = None) -> str:
    """Return the pipeline name a request would use under current settings."""
    return "fast" if should_use_fast_pipeline(user_id) else "baseline"
