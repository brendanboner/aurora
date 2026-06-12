"""Fire-and-forget Teams push for /survey submissions.

Posts to the teams-agent's /internal/push-survey-result endpoint, which
builds an Adaptive Card and delivers it to channels subscribed to the
`survey-feedback` slug. Silently skipped when TEAMS_AGENT_URL is unset.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


def _teams_agent_url() -> str:
    """Read fresh each call so test monkeypatch / config reloads work."""
    return os.getenv("TEAMS_AGENT_URL", "")


def push_survey_result(
    *,
    user_email: Optional[str],
    user_display_name: Optional[str],
    submitted_at: str,
    duration_seconds: Optional[int],
    responses: Dict[str, Any],
) -> None:
    """Fire-and-forget POST a survey submission to teams-agent.

    Failure is logged at WARN but never raised — the survey row is already
    persisted before this is called, so the user-facing response stays 200.
    """
    base = _teams_agent_url()
    if not base:
        return

    url = f"{base.rstrip('/')}/internal/push-survey-result"
    payload = {
        "user_email":        user_email,
        "user_display_name": user_display_name,
        "submitted_at":      submitted_at,
        "duration_seconds":  duration_seconds,
        "responses":         responses,
    }

    try:
        resp = httpx.post(url, json=payload, timeout=5)
        if resp.is_success:
            logger.info("Teams push queued for survey from %s", user_email)
        else:
            logger.warning(
                "Teams push returned %d: %s",
                resp.status_code, resp.text[:200],
            )
    except Exception as exc:
        logger.warning("Teams push failed (non-fatal): %s", exc)
