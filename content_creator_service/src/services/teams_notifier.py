"""Proactive Teams push notifications — called after a new post is created."""
from __future__ import annotations

import logging
import os
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

_TEAMS_AGENT_URL = os.getenv("TEAMS_AGENT_URL", "")


def push_feed_update(
    *,
    agent_slug: str,
    agent_name: str,
    post_id: int,
    title: str,
    summary: str,
    body: str = "",
    tags: List[str],
    source_url: Optional[str] = None,
    published_at: Optional[str] = None,
) -> None:
    """
    Fire-and-forget: POST to teams-agent /internal/push-feed-update.
    Routes by agent_slug → subscribed conversations.
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
        "body":         body,
        "tags":         tags,
        "source_url":   source_url,
        "published_at": published_at,
    }

    try:
        resp = httpx.post(url, json=payload, timeout=5)
        if resp.is_success:
            logger.info("Teams push queued for post %d (%s)", post_id, agent_slug)
        else:
            logger.warning("Teams push returned %d: %s", resp.status_code, resp.text[:200])
    except Exception as exc:  # pragma: no cover
        logger.warning("Teams push failed (non-fatal): %s", exc)


def push_user_agent_update(
    *,
    aurora_user_id: str,
    agent_name: str,
    post_id: int,
    title: str,
    summary: str,
    tags: List[str],
    source_url: Optional[str] = None,
    published_at: Optional[str] = None,
) -> None:
    """
    Fire-and-forget: POST to teams-agent /internal/push-user-agent-update.
    Routes by aurora_user_id → all Teams conversations linked to that user.
    Used for personal "My Agents" project-scoped agents.
    Silently skipped when TEAMS_AGENT_URL is not set (Teams not deployed).
    """
    if not _TEAMS_AGENT_URL:
        return

    url = f"{_TEAMS_AGENT_URL.rstrip('/')}/internal/push-user-agent-update"
    payload = {
        "aurora_user_id": aurora_user_id,
        "agent_name":     agent_name,
        "post_id":        post_id,
        "title":          title,
        "summary":        summary,
        "tags":           tags,
        "source_url":     source_url,
        "published_at":   published_at,
    }

    try:
        resp = httpx.post(url, json=payload, timeout=5)
        if resp.is_success:
            logger.info("Teams user-agent push queued for post %d (user %s)", post_id, aurora_user_id)
        else:
            logger.warning("Teams user-agent push returned %d: %s", resp.status_code, resp.text[:200])
    except Exception as exc:  # pragma: no cover
        logger.warning("Teams user-agent push failed (non-fatal): %s", exc)
