"""Proactive Teams push notifications — called after a new post is created."""
from __future__ import annotations

import logging
import os
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

_TEAMS_AGENT_URL = os.getenv("TEAMS_AGENT_URL", "")


def push_feed_update(
    *,
    agent_slug: str,
    agent_name: str,
    post_id: int,
    title: str,
    summary: str,
    tags: List[str],
    source_url: Optional[str] = None,
    published_at: Optional[str] = None,
) -> None:
    """
    Fire-and-forget: POST to teams-agent /internal/push-feed-update.
    Silently skipped when TEAMS_AGENT_URL is not set (Teams not deployed).
    """
    if not _TEAMS_AGENT_URL:
        return

    url = f"{_TEAMS_AGENT_URL.rstrip('/')}/internal/push-feed-update"
    payload = {
        "agent_slug":   agent_slug,
        "agent_name":   agent_name,
        "post_id":      post_id,
        "title":        title,
        "summary":      summary,
        "tags":         tags,
        "source_url":   source_url,
        "published_at": published_at,
    }

    try:
        resp = requests.post(url, json=payload, timeout=5)
        if resp.ok:
            logger.info(
                "Teams push sent for post %d (%s → %d conversations)",
                post_id,
                agent_slug,
                resp.json().get("sent", "?"),
            )
        else:
            logger.warning("Teams push returned %d: %s", resp.status_code, resp.text[:200])
    except Exception as exc:  # pragma: no cover
        logger.warning("Teams push failed (non-fatal): %s", exc)
