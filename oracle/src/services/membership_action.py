"""Membership action handler for conversational join/leave of WBA workgroups.

When the fast engine routes a query to MEMBERSHIP_ACTION, it calls
`handle()` here instead of executing a Cypher template. The handler:
  1. Parses the action (join vs. leave) and target name from the query.
  2. Resolves the target to a datasource_id via fuzzy Neo4j name match.
  3. Calls the backend API to update user_source_memberships.
  4. Returns a human-readable confirmation string.

Crucially: this function MUST NOT raise. Any error is caught and returned as
a friendly message. A raise would trigger the fast→baseline fallback in
oracle/src/routes/query.py, which would try to answer a RAG question for a
join/leave command — wrong behavior.
"""

import logging
import re
from typing import Optional

from src.settings import settings

logger = logging.getLogger(__name__)

# Words that precede the target name and should be stripped.
_ACTION_PREFIX = re.compile(
    r"^(join|leave|follow|unfollow|add|remove)\s+(the\s+)?",
    re.IGNORECASE,
)
# Suffixes that describe the noun type — also strip these from the target name.
_TARGET_SUFFIX = re.compile(
    r"\s+(workgroup|programme|program|group|community|wg)$",
    re.IGNORECASE,
)

_JOIN_WORDS = {"join", "follow", "add"}
_LEAVE_WORDS = {"leave", "unfollow", "remove"}


def _parse_action_and_target(question: str) -> tuple[Optional[str], Optional[str]]:
    """Return (action, target_name) where action is 'join' or 'leave'."""
    m = _ACTION_PREFIX.match(question.strip())
    if not m:
        return None, None
    verb = m.group(1).lower()
    action = "join" if verb in _JOIN_WORDS else "leave"
    remainder = question[m.end():].strip()
    remainder = _TARGET_SUFFIX.sub("", remainder).strip()
    return action, remainder if remainder else None


def _resolve_datasource(target_name: str, neo4j_client) -> list[dict]:
    """Find WBA Extranet DataSource nodes whose name contains the target.

    Returns up to 5 candidates: [{"datasource_id": str, "name": str}].
    """
    if not neo4j_client:
        return []
    query = """
    MATCH (d:DataSource {scraper_type: 'wba_extranet'})
    WHERE toLower(d.name)         CONTAINS toLower($name)
       OR toLower(coalesce(d.display_name,'')) CONTAINS toLower($name)
    RETURN d.datasource_id AS datasource_id,
           coalesce(d.display_name, d.name) AS name
    ORDER BY size(d.name)
    LIMIT 5
    """
    try:
        results = neo4j_client.execute_query(query, {"name": target_name})
        return [{"datasource_id": r["datasource_id"], "name": r["name"]} for r in results]
    except Exception as exc:
        logger.warning(f"membership_action: datasource lookup failed: {exc}")
        return []


async def _call_backend(user_id: str, datasource_id: str, action: str) -> bool:
    """PUT or DELETE the membership via the backend service.

    Uses common.service_client so we stay on the internal network
    (auth gateway is bypassed; X-User-Id header injected by the helper).
    """
    from common.service_client import call_internal_service

    method = "DELETE" if action == "leave" else "PUT"
    path = f"/users/{user_id}/source-memberships/{datasource_id}"
    body = {"status": "joined"} if action == "join" else None

    try:
        await call_internal_service(
            service="backend",
            path=path,
            method=method,
            json=body,
            user_id=user_id,
        )
        return True
    except Exception as exc:
        logger.error(f"membership_action: backend call failed ({method} {path}): {exc}")
        return False


async def handle(
    question: str,
    user_id: Optional[str],
    neo4j_client,
    span=None,
) -> str:
    """Handle a MEMBERSHIP_ACTION query. Returns a plain text answer.

    Never raises — all errors are surfaced as user-facing messages.
    """
    if not user_id:
        return "I need you to be logged in to join or leave a workgroup. Please sign in and try again."

    action, target_name = _parse_action_and_target(question)
    if not action or not target_name:
        return (
            "I couldn't tell which workgroup you'd like to join or leave. "
            "Try: \"join the AI/ML workgroup\" or \"leave the PQC group\"."
        )

    candidates = _resolve_datasource(target_name, neo4j_client)

    if not candidates:
        return (
            f"I couldn't find a WBA workgroup matching \"{target_name}\". "
            "Try asking \"What programmes are available in WBA?\" to see the full list."
        )

    if len(candidates) > 1:
        names = ", ".join(f"\"{c['name']}\"" for c in candidates[:5])
        return (
            f"I found several workgroups matching \"{target_name}\": {names}. "
            f"Could you be more specific? For example, say \"join the {candidates[0]['name']} workgroup\"."
        )

    ds = candidates[0]
    success = await _call_backend(user_id, ds["datasource_id"], action)

    if success:
        verb = "joined" if action == "join" else "left"
        extra = (
            " I'll now include their updates in answers about your groups."
            if action == "join"
            else " Their updates will no longer appear in your groups digest."
        )
        return f"Done — you've {verb} **{ds['name']}**.{extra}"
    else:
        return (
            f"Something went wrong updating your membership for {ds['name']}. "
            "Please try again in a moment."
        )
