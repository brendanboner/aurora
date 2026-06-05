"""Personalised /news brief.

Builds a short "what's new since you last checked" summary scoped to the
user's joined datasources (subscriptions). Falls back to the user's
profile (topic / organisation / domain preferences) when they have no
subscriptions.

Caching:
  * The brief itself is cached in Redis with a short TTL so repeated
    ``/news`` calls in quick succession share work.
  * ``last_requested_at`` is stored separately so re-reading the brief
    doesn't reset the user's high-water mark (only the explicit "mark
    seen" path updates it).

The route layer (``oracle/src/routes/news.py``) is the only caller. A
periodic refresh worker is layered on top later — keeping the
compute-on-demand path here means cold ``/news`` calls always work even
if the worker is down.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from src.services.cache import OracleCache
from src.services.keyword_retriever import get_repo
from src.services.personalization import (
    get_user_preferences,
    get_user_source_memberships,
)

logger = logging.getLogger(__name__)


# How far to look back when the user has no prior /news request on record.
DEFAULT_FIRST_LOOKBACK_DAYS = 3

# Max items to surface in a single brief.
MAX_ITEMS = 8

# Brief cache: short TTL so the user gets fresh content on repeated calls,
# but identical requests within the window share a single DB query.
BRIEF_CACHE_TTL_SECONDS = 600  # 10 minutes

# How long to retain last_requested_at (so first-time logic stays correct
# even for infrequent users).
LAST_SEEN_TTL_SECONDS = 60 * 60 * 24 * 90  # 90 days


@dataclass
class NewsItem:
    title: str
    url: Optional[str]
    summary: Optional[str]
    publish_date: Optional[str]
    datasource_id: Optional[str]

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "summary": self.summary,
            "publish_date": self.publish_date,
            "datasource_id": self.datasource_id,
        }


@dataclass
class NewsBrief:
    items: List[NewsItem] = field(default_factory=list)
    since: Optional[str] = None          # ISO-8601 of the cutoff used (last_requested_at or first-look fallback)
    source: str = "none"                 # "subscriptions" | "profile" | "global"
    cached_at: Optional[str] = None      # ISO-8601 of when this brief was generated
    datasource_count: int = 0            # how many sources the brief drew from

    def to_dict(self) -> dict:
        return {
            "items": [i.to_dict() for i in self.items],
            "since": self.since,
            "source": self.source,
            "cached_at": self.cached_at,
            "datasource_count": self.datasource_count,
        }


def _brief_cache_key(user_id: str) -> str:
    return f"news:brief:{user_id}"


def _last_seen_key(user_id: str) -> str:
    return f"news:last_seen:{user_id}"


async def _get_redis():
    """Convenience accessor — returns the singleton redis client or None."""
    try:
        cache = await OracleCache.get_cache()
        if cache.is_available():
            return cache._redis_client
    except Exception as exc:
        logger.warning(f"news: could not acquire Redis client: {exc}")
    return None


async def get_last_seen(user_id: str) -> Optional[datetime]:
    redis_client = await _get_redis()
    if not redis_client:
        return None
    try:
        raw = await redis_client.get(_last_seen_key(user_id))
        if raw:
            return datetime.fromisoformat(raw)
    except Exception as exc:
        logger.warning(f"news: get_last_seen failed for {user_id}: {exc}")
    return None


async def mark_seen(user_id: str, when: Optional[datetime] = None) -> None:
    """Bump the user's last_requested_at high-water mark."""
    redis_client = await _get_redis()
    if not redis_client:
        return
    when = when or datetime.now(timezone.utc)
    try:
        await redis_client.setex(_last_seen_key(user_id), LAST_SEEN_TTL_SECONDS, when.isoformat())
    except Exception as exc:
        logger.warning(f"news: mark_seen failed for {user_id}: {exc}")


async def _resolve_datasources(user_id: str) -> tuple[List[str], str]:
    """Return (datasource_ids, source_label).

    Tries the user's joined subscriptions first; falls back to "profile"
    (no source filter at all — the topic/domain weighting happens via the
    user_preferences query later) when they have none.
    """
    try:
        memberships = get_user_source_memberships(user_id) or {}
        joined = list(memberships.get("joined") or [])
    except Exception as exc:
        logger.warning(f"news: failed to load memberships for {user_id}: {exc}")
        joined = []

    if joined:
        # Expand parents → children (techfieldday → techfieldday_ai/…). Same
        # one-hop fanout the fast engine does for @-mentions.
        try:
            joined = await _expand_parents(joined)
        except Exception as exc:
            logger.warning(f"news: parent expansion failed: {exc}")
        return joined, "subscriptions"

    # No subscriptions — broad-scope brief gated by the user's profile
    # interests. Return an empty datasource list and let the caller use
    # topic/domain weighting instead of a hard filter.
    return [], "profile"


async def _expand_parents(datasource_ids: List[str]) -> List[str]:
    """One-hop parent → children fanout via Neo4j parent_datasource_id."""
    if not datasource_ids:
        return datasource_ids
    try:
        repo = get_repo()
        rows = repo.client.execute_query(
            """
            MATCH (child:DataSource)
            WHERE child.parent_datasource_id IN $parents
              AND child.parent_datasource_id <> ''
            RETURN child.datasource_id AS child
            """,
            {"parents": list(datasource_ids)},
        )
        expanded = list(datasource_ids)
        for r in rows:
            cid = r.get("child")
            if cid and cid not in expanded:
                expanded.append(cid)
        return expanded
    except Exception as exc:
        logger.warning(f"news: _expand_parents Neo4j lookup failed: {exc}")
        return datasource_ids


async def _fetch_news_items(
    *,
    datasource_ids: List[str],
    cutoff: datetime,
    topics: Optional[List[str]] = None,
    organisations: Optional[List[str]] = None,
    domains: Optional[List[str]] = None,
    limit: int = MAX_ITEMS,
) -> List[NewsItem]:
    """Query Neo4j for new Resources published since `cutoff`.

    Filters cascade: datasource scope first, then topic/org/domain
    boosting via OPTIONAL MATCH. Results are ordered newest first and
    capped at ``limit``.
    """
    repo = get_repo()

    where_clauses = ["r.publish_date IS NOT NULL"]
    params: dict = {
        "cutoff": cutoff.isoformat(),
        "limit": int(limit),
    }
    # Compare on the string form — Neo4j stores publish_date as either
    # a datetime() value or an ISO string depending on the writer, and
    # toString() works for both.
    where_clauses.append("toString(r.publish_date) >= $cutoff")

    if datasource_ids:
        params["datasource_ids"] = list(datasource_ids)
        where_clauses.append("r.datasource_id IN $datasource_ids")

    boost_terms: List[str] = []
    if topics:
        params["topic_names"] = [t.lower() for t in topics]
        boost_terms.append(
            "OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic) "
            "WHERE toLower(t.name) IN $topic_names WITH r, count(t) AS topic_hits"
        )
    if organisations:
        params["org_names"] = [o.lower() for o in organisations]
        boost_terms.append(
            "OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization) "
            "WHERE toLower(o.name) IN $org_names "
            f"WITH r{', topic_hits' if topics else ''}, count(o) AS org_hits"
        )

    score_expr_parts = ["toString(r.publish_date)"]
    if topics:
        score_expr_parts.insert(0, "topic_hits")
    if organisations:
        score_expr_parts.insert(0, "org_hits")
    order_by = ", ".join(f"{p} DESC" for p in score_expr_parts)

    cypher = f"""
    MATCH (r:Resource)
    WHERE {' AND '.join(where_clauses)}
    {' '.join(boost_terms)}
    RETURN r.title         AS title,
           r.url           AS url,
           r.summary       AS summary,
           toString(r.publish_date) AS publish_date,
           r.datasource_id AS datasource_id
    ORDER BY {order_by}
    LIMIT $limit
    """

    try:
        rows = repo.client.execute_query(cypher, params)
    except Exception as exc:
        logger.warning(f"news: Neo4j query failed: {exc}")
        return []

    items: List[NewsItem] = []
    for r in rows or []:
        items.append(
            NewsItem(
                title=(r.get("title") or "").strip() or "(untitled)",
                url=r.get("url"),
                summary=(r.get("summary") or "").strip() or None,
                publish_date=r.get("publish_date"),
                datasource_id=r.get("datasource_id"),
            )
        )
    return items


async def build_brief(user_id: str, *, force_refresh: bool = False) -> NewsBrief:
    """Top-level entry point — returns the user's current news brief.

    Reads from the Redis brief cache when warm; otherwise computes a
    fresh brief and writes it back. Does NOT update ``last_requested_at``
    on its own — the route layer decides when to mark-seen so that
    repeat polling within a session doesn't reset the high-water mark
    accidentally.
    """
    redis_client = await _get_redis()
    cache_key = _brief_cache_key(user_id)

    if not force_refresh and redis_client:
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                payload = json.loads(cached)
                items = [NewsItem(**i) for i in payload.get("items", [])]
                return NewsBrief(
                    items=items,
                    since=payload.get("since"),
                    source=payload.get("source", "none"),
                    cached_at=payload.get("cached_at"),
                    datasource_count=payload.get("datasource_count", 0),
                )
        except Exception as exc:
            logger.warning(f"news: brief cache read failed for {user_id}: {exc}")

    # ---------- compute fresh ----------
    last_seen = await get_last_seen(user_id)
    now = datetime.now(timezone.utc)
    if last_seen:
        cutoff = last_seen
    else:
        cutoff = now - timedelta(days=DEFAULT_FIRST_LOOKBACK_DAYS)

    datasource_ids, source_label = await _resolve_datasources(user_id)

    topics: List[str] = []
    organisations: List[str] = []
    domains: List[str] = []
    if source_label == "profile":
        try:
            prefs = await get_user_preferences(user_id)
            topics = prefs.topics or []
            organisations = prefs.organisations or []
            domains = prefs.domains or []
            if not (topics or organisations or domains):
                # Truly no signal — degrade to a global "what's new" pull so the
                # user still sees something useful on first use.
                source_label = "global"
        except Exception as exc:
            logger.warning(f"news: get_user_preferences failed for {user_id}: {exc}")
            source_label = "global"

    items = await _fetch_news_items(
        datasource_ids=datasource_ids,
        cutoff=cutoff,
        topics=topics or None,
        organisations=organisations or None,
        domains=domains or None,
        limit=MAX_ITEMS,
    )

    brief = NewsBrief(
        items=items,
        since=cutoff.isoformat(),
        source=source_label,
        cached_at=now.isoformat(),
        datasource_count=len(datasource_ids),
    )

    if redis_client:
        try:
            await redis_client.setex(
                cache_key,
                BRIEF_CACHE_TTL_SECONDS,
                json.dumps(brief.to_dict()),
            )
        except Exception as exc:
            logger.warning(f"news: brief cache write failed for {user_id}: {exc}")

    return brief
