"""
Aurora Alert Service — retriever side

Posts structured system alerts to the Teams bot's /internal/system-alert endpoint
so they appear as proactive messages in admin users' personal Teams chats.

Usage:
    from alert_service import AlertService

    AlertService.notify(
        severity="critical",
        component="WBA Extranet Scraper",
        title="Session token expired — HLLogin cookie needs renewal",
        detail="The WBA Extranet datasource auth_token was rejected on 2026-05-25 14:30 UTC. "
               "No WBA workgroup documents have been scraped since.",
        action="Log in to https://extranet.wballiance.com, copy the HLLogin cookie from "
               "DevTools → Application → Cookies, update WBA_EXTRANET_HLLOGIN in .env.prod, "
               "then restart the retriever.",
        datasource_id="wba_extranet",
    )

Failures are fully silent — if the Teams bot is unreachable the retriever
continues normally and the error is logged at DEBUG level only.
"""

import logging
import os
import urllib.request
import json as _json
from datetime import datetime, timezone
from typing import Literal, Optional

logger = logging.getLogger(__name__)

# Internal Teams bot URL (docker-compose network)
_TEAMS_BOT_URL = os.environ.get("TEAMS_AGENT_URL", "http://teams-agent:3978")
_ALERT_ENDPOINT = f"{_TEAMS_BOT_URL}/internal/system-alert"
_TIMEOUT_S = 5

# Rate-limit: don't spam the same alert within this window (seconds)
_COOLDOWN_S = 3600  # 1 hour
_last_alert: dict[str, datetime] = {}


def _is_on_cooldown(key: str) -> bool:
    last = _last_alert.get(key)
    if last is None:
        return False
    age = (datetime.now(timezone.utc) - last).total_seconds()
    return age < _COOLDOWN_S


class AlertService:
    """Static helper — call AlertService.notify() anywhere in the retriever."""

    @staticmethod
    def notify(
        severity: Literal["critical", "warning", "info"],
        component: str,
        title: str,
        detail: str,
        action: Optional[str] = None,
        datasource_id: Optional[str] = None,
        docs_count: Optional[int] = None,
    ) -> None:
        """
        Send a system alert to admin Teams chats.
        Fire-and-forget; never raises.
        """
        # Rate-limit: skip duplicate alerts within the cooldown window
        cooldown_key = f"{severity}:{component}:{title}"
        if _is_on_cooldown(cooldown_key):
            logger.debug(f"AlertService: suppressed duplicate alert (cooldown active): {title}")
            return

        payload: dict = {
            "severity": severity,
            "component": component,
            "title": title,
            "detail": detail,
        }
        if action:
            payload["action"] = action
        if datasource_id:
            payload["datasource_id"] = datasource_id
        if docs_count is not None:
            payload["docs_count"] = docs_count

        try:
            body = _json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                _ALERT_ENDPOINT,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                logger.info(
                    f"AlertService: alert sent [{severity}] {component} — {title} "
                    f"(HTTP {resp.status})"
                )
            _last_alert[cooldown_key] = datetime.now(timezone.utc)
        except Exception as exc:
            # Non-fatal — Teams bot may not be reachable in all environments
            logger.debug(f"AlertService: failed to send alert (non-fatal): {exc}")
