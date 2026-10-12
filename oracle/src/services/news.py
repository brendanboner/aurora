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
import re
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
    source_name: Optional[str] = None
    people: List[str] = field(default_factory=list)
    organizations: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "summary": self.summary,
            "publish_date": self.publish_date,
            "datasource_id": self.datasource_id,
            "source_name": self.source_name,
            "people": self.people,
            "organizations": self.organizations,
            "topics": self.topics,
        }


# Leading-prefix filler — boilerplate that the digester's LLM tacks onto
# otherwise factual sentences ("This document outlines the agenda for X" →
# we strip the "This document outlines (the|an|some)?" prefix and keep the
# factual tail "agenda for X").
_LEADING_FILLER_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        # "This/The (document|presentation|note|file|...) (outlines|covers|highlights|...) (the|a|an)?"
        # Allows an optional "titled 'X'" / "from May 11th" interpolation between
        # the noun and the verb so e.g. "The document titled 'agenda 7th june
        # 2026' outlines …" and "The meeting notes from may 11th detail …" also
        # get caught.
        r"^(?:this|the)\s+"
        r"(?:document|file|presentation|video|note|notes|deck|slide(?:s|deck)?|minutes|"
        r"brief(?:ing)?|recording|session|update|report|blog|article|post|email|"
        r"agenda|page)\s+"
        r"(?:titled\s+['\"][^'\"]+['\"]\s+|from\s+[a-z0-9 ,.-]{1,40}\s+|"
        r"about\s+[a-z0-9 ,.-]{1,40}\s+)?"
        r"(?:also\s+)?"
        r"(?:outlines?|covers?|highlights?|describes?|discusses?|presents?|"
        r"introduces?|explains?|examines?|explores?|focuses?\s+on|details?|"
        r"provides?|offers?|emphasi[zs]es?|aims?\s+to|seeks?\s+to|reviews?|"
        r"summari[zs]es?|mentions?|notes?|states?|reports?\s+on|gives?|"
        r"includes?|contains?)\s+"
        r"(?:the\s+|an?\s+|some\s+)?",
        # "It (also)? (highlights|outlines|covers|...) (the|a)?"
        r"^it\s+(?:also\s+)?"
        r"(?:outlines?|covers?|highlights?|describes?|discusses?|presents?|"
        r"introduces?|explains?|examines?|explores?|focuses?\s+on|details?|"
        r"provides?|offers?|emphasi[zs]es?|reviews?|summari[zs]es?|"
        r"mentions?|notes?|states?|reports?\s+on|gives?|includes?|contains?)\s+"
        r"(?:the\s+|an?\s+|some\s+)?",
    ]
]

# Whole-sentence filler — generic "this document is essential for tracking
# progress"-style closers. These have no factual content to preserve and
# get dropped entirely.
_FULL_FILLER_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"^(?:this|the)\s+(?:document|file|note|notes|presentation|deck|recording|"
        r"brief(?:ing)?|video|session|report)\s+"
        r"(?:is|are|serves?|aims?|seeks?)\b[^.]*"
        r"(?:essential|crucial|vital|important|key|critical|valuable)\b",
        r"(?:essential|crucial|vital|important|key|critical)\s+for\s+"
        r"(?:tracking|reference|stakeholders|future\s+reference|the\s+team|"
        r"collaboration|maintaining|ensuring|navigating)",
        # Allow one optional adjective before record/reference so
        # "serves as a formal record" / "serves as a primary reference"
        # also get caught.
        r"serves?\s+as\s+(?:a|an|the)\s+(?:[a-z]+\s+)?"
        r"(?:record|reference|key|valuable|comprehensive|essential|critical|"
        r"crucial|primary|important|guide|resource|tool|agenda|summary)\b",
        r"providing\s+(?:valuable\s+)?(?:insights?|context|an?\s+overview)\s+"
        r"into\s+(?:the\s+)?(?:ongoing|current|broader)?\s*work",
        r"contributions?\s+of\s+(?:various|the|all)\s+(?:participants?|members|"
        r"attendees|stakeholders|individuals)",
        r"only\s+for\s+general\s+understanding",
        # "It is intended for stakeholders involved in..." / "It is meant for X".
        r"^it\s+(?:is|was)\s+(?:intended|meant|designed|created)\s+for\b",
        # "Key topics included updates on ongoing projects, action items..." —
        # generic meeting-notes summary that names no actual topic.
        r"^(?:key|main|primary)\s+(?:topics?|points?|items?|themes?|areas?)\s+"
        r"(?:included|covered|discussed|addressed|were)\s+"
        r"(?:updates?|discussions?|reviews?|action\s+items?|next\s+steps?|"
        r"future\s+meeting|ongoing\s+projects?|status\s+updates?)\b[^.]*",
        # "Detail discussions and decisions made during the meeting" — pure meta.
        r"detail(?:s|ed)?\s+(?:the\s+)?discussions?\s+and\s+decisions?\s+made",
        # "Outlines the key topics and discussions planned for X" — meta about
        # an agenda doc that says nothing about the actual topics.
        r"^(?:outlines?|describes?|covers?)\s+(?:the\s+)?(?:key\s+)?"
        r"(?:topics?|items?|subjects?)\s+and\s+(?:discussions?|decisions?|"
        r"action\s+items?)\s+(?:planned|scheduled|to\s+be\s+(?:addressed|"
        r"discussed|made))\b[^.]*",
    ]
]

# Mid-sentence hedge phrases — strip in place, the surrounding sentence
# usually still reads fine after they're removed.
_HEDGE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r",?\s*providing\s+(?:valuable\s+)?(?:insights?|context|an?\s+overview)"
        r"\s+into\s+[^.]+(?=\.|$)",
        r",?\s*(?:essential|crucial|vital|important)\s+for\s+"
        r"(?:tracking|reference|stakeholders|future\s+reference|the\s+team|"
        r"collaboration)(?=[\s.,]|$)",
        r",?\s*serving\s+as\s+(?:a|an|the)\s+(?:record|reference)\s+of\s+[^.]+(?=\.|$)",
    ]
]


def _strip_filler(summary: Optional[str]) -> Optional[str]:
    """Strip generic LLM filler from a Resource summary.

    Three layers of cleanup, applied per sentence:
      1. Drop the sentence entirely if it matches one of the "whole-filler"
         patterns (e.g. "This document is essential for tracking progress").
      2. Strip mid-sentence hedge phrases ("providing insights into X",
         "essential for stakeholders") in place.
      3. Strip the leading "This document outlines / It also highlights"
         filler prefix, keeping the factual tail. Re-capitalise the first
         remaining letter.

    Returns the cleaned string, or None if nothing factual survives.
    """
    if not summary:
        return None
    sentences = re.split(r"(?<=[.!?])\s+", summary.strip())
    kept: List[str] = []
    for raw in sentences:
        s = raw.strip()
        if not s:
            continue
        # 1. Whole-sentence filler — drop.
        if any(p.search(s) for p in _FULL_FILLER_PATTERNS):
            continue
        # 2. Mid-sentence hedges — strip in place.
        for hp in _HEDGE_PATTERNS:
            s = hp.sub("", s)
        # 3. Leading-prefix filler — strip from the start, keep the tail.
        for lp in _LEADING_FILLER_PATTERNS:
            s = lp.sub("", s, count=1)
        # Tidy up whitespace and stray commas.
        s = re.sub(r"\s+,", ",", s)
        s = re.sub(r"\s{2,}", " ", s).strip()
        # Drop trailing-comma artefacts left behind by the hedge strip.
        s = re.sub(r",\s*\.\s*$", ".", s).strip()
        if len(s) < 20:
            continue
        # Re-capitalise the first character so "agenda for X" → "Agenda for X".
        if s and s[0].islower():
            s = s[0].upper() + s[1:]
        kept.append(s)
    if not kept:
        return None
    return " ".join(kept)


def _format_facts(item: NewsItem) -> str:
    """Build a one-liner of structured facts pulled from the graph.

    Skips a category when the underlying list is empty; the result is "" when
    we have nothing concrete (which is the signal to fall back to the cleaned
    summary in the caller).
    """
    parts: List[str] = []
    if item.people:
        # Cap at 3 people — more than that and the line stops being readable.
        parts.append("Presented by " + ", ".join(item.people[:3]))
    if item.organizations:
        parts.append("Companies: " + ", ".join(item.organizations[:5]))
    if item.topics:
        parts.append("Topics: " + ", ".join(item.topics[:6]))
    return " · ".join(parts)


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
    // Pull structured facts from the graph alongside the LLM summary so we
    // can build a fact-led brief (presenter / companies / topics) instead
    // of leaning on the boilerplate-heavy free-text summary.
    OPTIONAL MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
    OPTIONAL MATCH (r)-[:MENTIONS]->(p_out:Person)
    OPTIONAL MATCH (p_in:Person)-[:MENTIONS]->(r)
    OPTIONAL MATCH (r)-[:MENTIONS]->(o_out:Organization)
    OPTIONAL MATCH (o_in:Organization)-[:MENTIONS]->(r)
    OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
    WITH r, ds,
         collect(DISTINCT p_out.name) + collect(DISTINCT p_in.name) AS people_raw,
         collect(DISTINCT o_out.name) + collect(DISTINCT o_in.name) AS orgs_raw,
         collect(DISTINCT t.name)                                   AS topics_raw
    RETURN r.title         AS title,
           r.url           AS url,
           r.summary       AS summary,
           toString(r.publish_date) AS publish_date,
           r.datasource_id AS datasource_id,
           ds.name         AS source_name,
           [x IN people_raw WHERE x IS NOT NULL AND x <> ''] AS people,
           [x IN orgs_raw   WHERE x IS NOT NULL AND x <> ''] AS organizations,
           [x IN topics_raw WHERE x IS NOT NULL AND x <> ''] AS topics
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
        raw_summary = (r.get("summary") or "").strip() or None
        cleaned = _strip_filler(raw_summary)

        people = sorted(set(r.get("people") or []))
        orgs = sorted(set(r.get("organizations") or []))
        topics = sorted(set(r.get("topics") or []))

        # Friendly source name: prefer DataSource.name from the graph, fall back
        # to a Title-Cased datasource_id ("wfa_causeway" → "Wfa Causeway") so the
        # UI never has to guess. The cleaner mapping (uppercased acronyms etc.)
        # lives in the frontend; we just give it something readable to start.
        ds_id = r.get("datasource_id")
        source_name = (r.get("source_name") or "").strip() or None
        if not source_name and ds_id:
            source_name = ds_id.replace("_", " ").strip().title() or None

        item = NewsItem(
            title=(r.get("title") or "").strip() or "(untitled)",
            url=r.get("url"),
            summary=None,  # rebuilt below
            publish_date=r.get("publish_date"),
            datasource_id=ds_id,
            source_name=source_name,
            people=people,
            organizations=orgs,
            topics=topics,
        )

        # Compose the displayed summary: structured graph facts first (most
        # informative), then the cleaned narrative as a fallback / supplement.
        facts_line = _format_facts(item)
        body_parts: List[str] = []
        if facts_line:
            body_parts.append(facts_line)
        if cleaned:
            body_parts.append(cleaned)
        item.summary = "\n".join(body_parts) if body_parts else None

        items.append(item)
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
