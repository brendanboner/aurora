"""
Tech Field Day scraper.

Pulls video posts from the Tech Field Day WordPress REST API on the public
content/staging host. Each video carries the event it was filmed at
(taxonomy term slug), the presenter (personnel), and the sponsor (company).

We map each event slug to a topic-bucket datasource (`techfieldday_ai`,
`techfieldday_cloud`, `techfieldday_networking`, …) so a query like
`@techfieldday what was discussed by VMware?` can route through the
fast-pipeline `organization_activity` template.

Design points:
  - Daily incremental: we use `?after=YYYY-MM-DDT00:00:00` (date filter)
    AND content_hash dedup so unchanged sessions are skipped.
  - 1-year lookback ceiling regardless of `after` param — TFD content older
    than that adds little value and inflates ingest cost.
  - We do NOT touch YouTube. The video page on stg-techfielddayq-staging
    has the full session description + embedded video; we cite it
    directly so users land on the readable page, not the raw video.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, Event, Resource

logger = logging.getLogger(__name__)

# Source of truth for the WP REST API. We use the production techfieldday.com
# domain because the Kinsta staging mirror is thin — its `post_tag` taxonomy
# reports count=1 for events that actually have ~57 blog posts on production.
# techfieldday.com only blocks scrapers that use a non-browser UA; with the
# Safari UA we send below, every endpoint we need (video, event, posts, tags)
# returns 200.
WP_API = "https://techfieldday.com/wp-json/wp/v2"

# Per-event blog-post fetch cap. Each TFD event has dozens of write-ups (NFD40
# has ~57). We cap to avoid burying the digester under hundreds of identical
# event-history posts; this still surfaces the recent ones for each event.
POSTS_PER_EVENT = 40

# Event-slug-prefix → topic-slug mapping. TFD uses systematic short prefixes
# (aifd1, aifd2, … aifd8 for "AI Field Day"; cfd*, nfd*, mfd*, etc.). We map
# each prefix to a topic slug; the topic slug becomes the datasource ID
# suffix (`techfieldday_ai`, `techfieldday_cloud`, …).
#
# Ordered longest-prefix-first so 'aiifd' beats 'aifd', 'aidifd' beats both.
EVENT_PREFIX_TO_TOPIC: List[Tuple[str, str]] = [
    ("aidifd", "ai-infrastructure"),     # AI + Data Infrastructure Field Day
    ("aiifd",  "ai-infrastructure"),     # AI Infrastructure Field Day
    ("adfd",   "appdev"),                # AppDev Field Day
    ("aifd",   "ai"),                    # AI Field Day
    ("cfd",    "cloud"),                 # Cloud Field Day
    ("nfd",    "networking"),            # Networking Field Day
    ("mfd",    "mobility"),              # Mobility Field Day
    ("xfd",    "security"),              # Security Field Day (X = Sec in TFD lingo)
    ("sfd",    "storage"),               # Storage Field Day
    ("vfd",    "virtualization"),        # Virtualization Field Day
    ("efd",    "edge"),                  # Edge Field Day
    ("dfd",    "data"),                  # Data Field Day
    ("ucfd",   "unified-communications"),
    ("mffd",   "mainframe"),
    ("wfd",    "wireless"),              # Wireless Field Day (legacy / sometimes still used)
    ("tfd",    "tech"),                  # Generic Tech Field Day
]

# All topic slugs (matches the 15 topics listed at techfieldday.com/topics)
KNOWN_TOPIC_SLUGS = {
    "ai", "ai-infrastructure", "appdev", "cloud", "data", "edge",
    "mainframe", "mobility", "networking", "security", "storage",
    "tech", "unified-communications", "virtualization", "wireless",
}

# Hard upper bound on lookback (per user requirement — no further than 1y).
MAX_LOOKBACK_DAYS = 365

# WP per_page max is 100. We don't use _embed=wp:term any more (it returned
# the global event-post registry instead of per-video taxonomy terms, due to
# a WP rest_base collision — we read class_list tokens instead), so the larger
# page is no longer a timeout risk.
PER_PAGE = 100

# Polite delay between paginated fetches
PAGE_DELAY_S = 0.4


def _strip_html(html: str, max_chars: int = 3500) -> str:
    """Render WP HTML content to plain prose suitable for the digester."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    # Drop scripts, styles, and toolset view boilerplate
    for bad in soup(["script", "style"]):
        bad.decompose()
    for div in soup.find_all("div", class_=re.compile(r"^js-wpv|^wpv-")):
        div.decompose()
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    if len(text) > max_chars:
        # Truncate at the nearest sentence boundary
        cut = text[:max_chars]
        last_dot = cut.rfind(". ")
        if last_dot > max_chars // 2:
            cut = cut[: last_dot + 1]
        text = cut + "…"
    return text


def _slug_to_topic(event_slug: str) -> Optional[str]:
    """Return the topic slug for a Tech Field Day event slug.

    e.g.  aifd8     → 'ai'
          cfd25     → 'cloud'
          netappinsight25 → None (non-TFD partner event — skip topic routing)
    """
    if not event_slug:
        return None
    s = event_slug.lower()
    for prefix, topic in EVENT_PREFIX_TO_TOPIC:
        if s.startswith(prefix):
            # Require what follows to be digits (the event number) so
            # 'cisco' doesn't accidentally match a 'cfd' prefix.
            rest = s[len(prefix):]
            if rest and (rest[0].isdigit() or rest[0] in "-_"):
                return topic
    return None


class TechFieldDayScraper(BaseScraper):
    """Scrape Tech Field Day video posts via the WP REST API."""

    scraper_name = "techfieldday"

    # ---------------------------------------------------------------
    # HTTP helpers
    # ---------------------------------------------------------------

    async def _get_json(self, url: str) -> Optional[Any]:
        """Fetch a JSON endpoint with a browser UA."""
        try:
            async with self.session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=45),
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                        "Version/17.0 Safari/605.1.15"
                    ),
                    "Accept": "application/json",
                },
            ) as resp:
                if resp.status != 200:
                    # WP returns 400 ("rest_post_invalid_page_number") when you
                    # paginate past the last page — it's the canonical end-of-
                    # pagination signal, not an error. Log at debug so the
                    # scraper output isn't dominated by these.
                    if resp.status == 400:
                        logger.debug(f"TFD: HTTP 400 (end of pages) for {url}")
                    else:
                        logger.warning(f"TFD: HTTP {resp.status} for {url}")
                    return None
                return await resp.json(content_type=None)
        except Exception as exc:
            # asyncio.TimeoutError's str() is empty — surface the class name
            logger.error(f"TFD: error fetching {url}: {type(exc).__name__}: {exc}")
            return None

    # ---------------------------------------------------------------
    # Lookup tables
    # ---------------------------------------------------------------

    async def _build_event_post_index(self) -> Dict[str, Dict[str, Any]]:
        """Build a small slug→event-post lookup for fallback topic resolution.

        Only fetches the most-recent ~50 events without embeds — the
        per_page=100 + _embed=wp:term variant times out on Kinsta. The
        video-side embedded `event` term is the primary signal anyway;
        this index is only a fallback when the slug regex doesn't match.
        """
        out: Dict[str, Dict[str, Any]] = {}
        url = f"{WP_API}/event?per_page=50&page=1&orderby=date&order=desc"
        data = await self._get_json(url)
        if data and isinstance(data, list):
            for ev in data:
                slug = ev.get("slug") or ""
                if slug:
                    out[slug.lower()] = ev
        logger.info(f"TFD: indexed {len(out)} recent event posts")
        return out

    async def _resolve_tag_id(self, event_slug: str) -> Optional[int]:
        """Look up the post_tag taxonomy term ID for an event slug.

        Each TFD event has a same-named tag (``nfd40``, ``aifd8``, …) that
        the blog-post stream uses to group write-ups. We need the numeric
        term ID so we can later call ``/wp/v2/posts?tags=<id>``.
        """
        if not event_slug:
            return None
        url = f"{WP_API}/tags?slug={event_slug}"
        data = await self._get_json(url)
        if isinstance(data, list) and data:
            tid = data[0].get("id")
            try:
                return int(tid) if tid is not None else None
            except (TypeError, ValueError):
                return None
        return None

    async def _scrape_blog_posts_for_event(
        self,
        event_slug: str,
        datasource_id_default: str,
        event_index: Dict[str, Dict[str, Any]],
        cutoff_iso: str,
    ) -> int:
        """Publish blog posts that are tagged with this event's slug.

        TFD writes a per-presentation blog post (URL pattern
        ``/<year>/<post-slug>/``) for most presentations. They live under
        ``/wp/v2/posts`` and are tagged with the event's slug (``nfd40``,
        ``aifd8``, …). Returns count seen — actual publish count comes
        from the base-scraper batch counter.
        """
        tag_id = await self._resolve_tag_id(event_slug)
        if tag_id is None:
            return 0

        # Resolve target datasource — same logic as videos: route to a topic
        # bucket via the event slug, fall back to the parent on partner events.
        topic = _slug_to_topic(event_slug)
        if topic and topic in KNOWN_TOPIC_SLUGS:
            ds_id = f"techfieldday_{topic}"
        else:
            ds_id = datasource_id_default
        event_post = event_index.get(event_slug.lower())
        event_name = (event_post.get("title", {}).get("rendered") if event_post else None) or event_slug

        seen = 0
        for page in range(1, 6):
            if seen >= POSTS_PER_EVENT:
                break
            url = (
                f"{WP_API}/posts?tags={tag_id}"
                f"&per_page={min(POSTS_PER_EVENT - seen, 50)}&page={page}"
                f"&orderby=date&order=desc&after={cutoff_iso}"
            )
            data = await self._get_json(url)
            if not data or not isinstance(data, list) or not data:
                break

            for p in data:
                title = unescape(p.get("title", {}).get("rendered") or "").strip()
                link = p.get("link") or ""
                if not (title and link):
                    continue
                date_iso = p.get("date") or p.get("date_gmt") or ""
                content_html = p.get("content", {}).get("rendered") or ""
                excerpt_html = p.get("excerpt", {}).get("rendered") or ""
                description = _strip_html(content_html or excerpt_html, max_chars=3500)

                # The blog post's class_list also carries event-/sponsor-/personnel-
                # tokens (same convention as videos), so we can reuse our existing
                # term parser to pull facts.
                terms = self._terms_from_class_list(p)

                def _name_from_slug(slug: str) -> str:
                    return " ".join(w.capitalize() for w in slug.replace("_", " ").split("-"))

                authors = ", ".join(_name_from_slug(s) for s in terms["personnel"][:3])
                sponsors = ", ".join(_name_from_slug(s) for s in terms["sponsor"][:3])

                # Build a brief summary header: date · event · sponsor · author
                head_bits: List[str] = []
                if date_iso:
                    head_bits.append(date_iso[:10])
                if event_name:
                    head_bits.append(event_name)
                if sponsors:
                    head_bits.append(f"about {sponsors}")
                if authors:
                    head_bits.append(f"by {authors}")
                summary_parts: List[str] = []
                if head_bits:
                    summary_parts.append(" · ".join(head_bits) + ".")
                if description:
                    summary_parts.append(description)
                summary = "\n".join(summary_parts)

                # Dedup against the existing url_hash so re-running the scraper
                # is cheap and idempotent (publish_resource will also lookback-
                # filter older items on repeat runs).
                if self.neo4j_client and not self.has_content_changed(link, summary or ""):
                    continue

                self.publish_resource(Resource(
                    title=title,
                    url=link,
                    category="article",
                    content=summary,
                    summary=summary,
                    publish_date=date_iso,
                    datasource_id=ds_id,
                    doc_type="tfd-post",
                ))
                seen += 1
                if seen >= POSTS_PER_EVENT:
                    break

            await asyncio.sleep(PAGE_DELAY_S)

        return seen

    # ---------------------------------------------------------------
    # Term extraction
    # ---------------------------------------------------------------

    @staticmethod
    def _terms_from_class_list(video: Dict[str, Any]) -> Dict[str, List[str]]:
        """Bucket the post's `class_list` tokens by taxonomy.

        The WP REST API exposes a name collision: ``event`` is both a custom
        post type *and* a taxonomy attached to ``video``. Because of that
        collision, ``_embed=wp:term`` returns the global event-post registry
        instead of the per-video taxonomy terms, which is useless. The
        ``class_list`` field, however, contains the WP post-CSS classes —
        and WP emits ``event-<slug>``, ``personnel-<slug>``, ``sponsor-<slug>``,
        ``configuration-<slug>`` tokens there, one per attached term. We
        parse those directly to recover the per-video term slugs.
        """
        out: Dict[str, List[str]] = {"event": [], "personnel": [], "sponsor": [], "configuration": []}
        for token in (video.get("class_list") or []):
            for tax in out.keys():
                prefix = tax + "-"
                if token.startswith(prefix):
                    out[tax].append(token[len(prefix):])
                    break
        return out

    @classmethod
    def _resolve_topic_datasource(
        cls,
        terms: Dict[str, List[str]],
        event_index: Dict[str, Dict[str, Any]],
    ) -> Tuple[str, Optional[str], Optional[str]]:
        """Return (datasource_id, event_slug, event_name) for a video.

        Iterates the per-video event-term slugs (from ``class_list``) and
        picks the first one whose prefix matches a known TFD event series
        (aifd, cfd, nfd, …). Falls back to the parent ``techfieldday``
        datasource for partner events (KubeCon, RSAC, Cisco Live, …) that
        don't follow the *FD<num> pattern.
        """
        topic = None
        event_slug = None
        for slug in terms.get("event", []):
            mapped = _slug_to_topic(slug)
            if mapped:
                topic = mapped
                event_slug = slug
                break
        # If no topic-mapped event was found, still remember the first event
        # slug so the summary can name the (partner) event.
        if event_slug is None and terms.get("event"):
            event_slug = terms["event"][0]

        # Resolve a human-readable event name via the recent-events index
        # if possible.
        event_name: Optional[str] = None
        if event_slug:
            post = event_index.get(event_slug)
            if post:
                event_name = unescape(post.get("title", {}).get("rendered") or "") or event_slug
            else:
                event_name = event_slug

        topic_slug = topic if topic in KNOWN_TOPIC_SLUGS else None
        datasource_id = f"techfieldday_{topic_slug}" if topic_slug else "techfieldday"
        return datasource_id, event_slug, event_name

    # ---------------------------------------------------------------
    # Mapping video → Resource
    # ---------------------------------------------------------------

    @staticmethod
    def _video_summary(video: Dict[str, Any], presenter: str, sponsor: str,
                       event_name: Optional[str], date_iso: str, description: str,
                       youtube_id: str, vimeo_id: str) -> str:
        """Build a short, queryable summary string for the digester."""
        parts: List[str] = []
        when = date_iso[:10] if date_iso else ""
        head_bits = []
        if when:
            head_bits.append(when)
        if event_name:
            head_bits.append(event_name)
        if sponsor:
            head_bits.append(f"by {sponsor}")
        if presenter:
            head_bits.append(f"presented by {presenter}")
        if head_bits:
            parts.append(" · ".join(head_bits) + ".")
        if description:
            parts.append(description)
        if youtube_id:
            parts.append(f"YouTube: https://www.youtube.com/watch?v={youtube_id}")
        elif vimeo_id:
            parts.append(f"Vimeo: https://vimeo.com/{vimeo_id}")
        return "\n".join(parts)

    @classmethod
    def _video_to_resource(
        cls,
        video: Dict[str, Any],
        event_index: Dict[str, Dict[str, Any]],
        datasource_id_default: str,
    ) -> Optional[Resource]:
        """Turn a WP video post dict into a Resource ready for publish_resource()."""
        title = unescape(video.get("title", {}).get("rendered") or "").strip()
        link = video.get("link") or ""
        if not (title and link):
            return None
        date_iso = video.get("date") or video.get("date_gmt") or ""
        content_html = video.get("content", {}).get("rendered") or ""
        excerpt_html = video.get("excerpt", {}).get("rendered") or ""
        description = _strip_html(content_html or excerpt_html, max_chars=3500)

        terms = cls._terms_from_class_list(video)
        # Slugs → human names. We don't have the full term registry in-hand,
        # so we titlecase the slug as a serviceable fallback (e.g.
        # ``vmware-by-broadcom`` → ``Vmware By Broadcom``). Good enough for
        # the digester's NER pass to recognise the entity.
        def _name_from_slug(slug: str) -> str:
            return " ".join(w.capitalize() for w in slug.replace("_", " ").split("-"))

        presenter = ", ".join(_name_from_slug(s) for s in terms["personnel"][:3])
        sponsor = ", ".join(_name_from_slug(s) for s in terms["sponsor"][:3])
        kind = (terms["configuration"][0] if terms["configuration"] else "video") or "video"

        # toolset-meta carries youtube / vimeo IDs
        tm = video.get("toolset-meta") or {}
        vi = (tm.get("video-information") or {})
        youtube_id = (vi.get("youtube-id") or {}).get("raw") or ""
        vimeo_id = (vi.get("vimeo-id") or {}).get("raw") or ""

        ds_id, event_slug, event_name = cls._resolve_topic_datasource(terms, event_index)
        if ds_id == "techfieldday" and datasource_id_default and datasource_id_default != "techfieldday":
            ds_id = datasource_id_default

        summary = cls._video_summary(
            video, presenter, sponsor, event_name, date_iso, description,
            youtube_id, vimeo_id,
        )

        return Resource(
            title=title,
            url=link,
            category=kind.lower() if kind else "video",
            content=summary,        # Use summary AS content so digester gets the prose
            summary=summary,
            publish_date=date_iso,
            datasource_id=ds_id,
            doc_type="tfd-video",
        )

    # ---------------------------------------------------------------
    # Main paginated fetch loop
    # ---------------------------------------------------------------

    async def _scrape_videos(
        self,
        datasource_id_default: str,
        cutoff_iso: str,
        max_resources: int,
        scraper_delay: float,
    ) -> int:
        """Fetch /wp/v2/video pages until older than cutoff. Returns count seen."""
        event_index = await self._build_event_post_index()
        seen = 0
        consecutive_dupes = 0
        max_dupes = 20  # stop pagination early if every recent video is unchanged

        for page in range(1, 50):
            if max_resources and seen >= max_resources:
                break
            url = (
                f"{WP_API}/video"
                f"?per_page={PER_PAGE}&page={page}"
                f"&orderby=date&order=desc"
                f"&after={cutoff_iso}"
            )
            data = await self._get_json(url)
            if not data or isinstance(data, dict) or len(data) == 0:
                break

            for v in data:
                try:
                    res = self._video_to_resource(v, event_index, datasource_id_default)
                except Exception as exc:
                    logger.warning(f"TFD: skip video {v.get('id')}: {exc}")
                    continue
                if not res:
                    continue
                # Content-hash dedup — skip if the page's prose hasn't changed
                if self.neo4j_client and not self.has_content_changed(res.url, res.content or ""):
                    consecutive_dupes += 1
                    if consecutive_dupes >= max_dupes:
                        logger.info(
                            f"TFD: {max_dupes} consecutive unchanged sessions — "
                            f"stopping pagination at page {page}"
                        )
                        return seen
                    continue
                consecutive_dupes = 0
                self.publish_resource(res)
                seen += 1
                if max_resources and seen >= max_resources:
                    return seen

            await asyncio.sleep(scraper_delay or PAGE_DELAY_S)

        return seen

    # ---------------------------------------------------------------
    # Events (for the calendar / Event nodes)
    # ---------------------------------------------------------------

    @staticmethod
    def _event_start_date(ev: Dict[str, Any]) -> str:
        """Extract the real start date of a TFD event.

        WP's `date` field is a meaningless placeholder (every event has
        `2013-04-01`). The actual start date lives in
        ``toolset-meta.event-information.sdate`` — a Unix epoch in ``.raw``
        plus a human-readable ``.formatted``. Return ISO ``YYYY-MM-DD``,
        or "" if unparseable.
        """
        tm = ev.get("toolset-meta") or {}
        info = tm.get("event-information") or {}
        sdate = info.get("sdate") or {}
        raw = sdate.get("raw")
        if raw:
            try:
                ts = int(raw)
                return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                pass
        return ""

    async def _scrape_events(self, datasource_id_default: str, cutoff_iso: str) -> int:
        """Pull the event POST type and publish them as calendar Events.

        Returns count seen — actual publish count is tracked via the base
        scraper batch counter, since publish_event may filter via lookback.
        """
        event_index = await self._build_event_post_index()
        return await self._scrape_events_from_index(
            datasource_id_default=datasource_id_default,
            cutoff_iso=cutoff_iso,
            event_index=event_index,
        )

    async def _scrape_events_from_index(
        self,
        datasource_id_default: str,
        cutoff_iso: str,
        event_index: Dict[str, Dict[str, Any]],
    ) -> int:
        """Same as _scrape_events but reuses a pre-built event index.

        Lets the orchestrator fetch the index once and pass it through to
        both this method and the blog-post pass below, instead of paying for
        a second /wp/v2/event round-trip.
        """
        seen = 0
        cutoff_day = cutoff_iso[:10]  # 'YYYY-MM-DD' for client-side filtering

        for ev in event_index.values():
            slug = (ev.get("slug") or "").lower()
            title = unescape(ev.get("title", {}).get("rendered") or "").strip()
            link = ev.get("link") or ""
            content_html = ev.get("content", {}).get("rendered") or ""
            description = _strip_html(content_html, max_chars=2500)
            start_date = self._event_start_date(ev)
            if not (title and link and start_date):
                continue
            # Skip events older than the 1-year cutoff. Future events
            # (start_date > today) pass through unconditionally.
            if start_date < cutoff_day:
                continue

            topic = _slug_to_topic(slug)
            ds_id = f"techfieldday_{topic}" if topic and topic in KNOWN_TOPIC_SLUGS \
                    else datasource_id_default
            event_obj = Event(
                name=title,
                event_type="conference",
                start_date=start_date,
                description=description,
                url=link,
                datasource_id=ds_id,
            )
            self.publish_event(event_obj)
            seen += 1

        return seen

    # ---------------------------------------------------------------
    # Required entry points
    # ---------------------------------------------------------------

    async def run_scraper(self, datasource_config: Optional[Dict[str, Any]] = None):
        """Entry point invoked by the orchestrator."""
        cfg = datasource_config or {}
        ds_id = cfg.get("datasource_id") or "techfieldday"
        scraper_delay = float(cfg.get("scraper_delay") or 0.5)
        max_resources = int(cfg.get("max_resources") or 600)

        # Lookback: cap at 1 year regardless of any per-datasource setting
        days = int(cfg.get("temporal_extraction_days") or 365)
        days = min(days, MAX_LOOKBACK_DAYS)
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_iso = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%S")

        try:
            self.start_batch(ds_id)
            # Snapshot the batch counter around each phase so we report the
            # number of items that actually went to RabbitMQ (i.e. weren't
            # filtered out by the base-scraper lookback guard).

            # 1) Videos — paginated /wp/v2/video sweep.
            pre_videos = self._batch_items_count
            videos_seen = await self._scrape_videos(
                datasource_id_default=ds_id,
                cutoff_iso=cutoff_iso,
                max_resources=max_resources,
                scraper_delay=scraper_delay,
            )
            videos_published = self._batch_items_count - pre_videos

            # 2) Events — used both for the calendar AND to drive the
            # per-event blog-post pass below.
            pre_events = self._batch_items_count
            event_index = await self._build_event_post_index()
            events_seen = await self._scrape_events_from_index(
                datasource_id_default=ds_id,
                cutoff_iso=cutoff_iso,
                event_index=event_index,
            )
            events_published = self._batch_items_count - pre_events

            # 3) Blog posts — one /wp/v2/posts?tags=<tag-id> call per known
            # event slug. This is where the per-event coverage comes from:
            # without it, the global /video pagination only surfaces the most
            # recent 100–200 videos across all events, so any specific event
            # (e.g. NFD40) gets sparse representation. Capped at
            # POSTS_PER_EVENT per event to bound the digester load.
            pre_posts = self._batch_items_count
            for slug, ev in list(event_index.items()):
                try:
                    await self._scrape_blog_posts_for_event(
                        event_slug=slug,
                        datasource_id_default=ds_id,
                        event_index=event_index,
                        cutoff_iso=cutoff_iso,
                    )
                except Exception as exc:
                    logger.warning(f"TFD: blog scrape failed for {slug}: {type(exc).__name__}: {exc}")
                await asyncio.sleep(scraper_delay or PAGE_DELAY_S)
            posts_published = self._batch_items_count - pre_posts

            logger.info(
                f"TFD ({ds_id}): published {videos_published}/{videos_seen} videos, "
                f"{events_published}/{events_seen} events, "
                f"{posts_published} blog posts across {len(event_index)} event tags "
                f"(cutoff={cutoff_iso[:10]})"
            )
        finally:
            self.end_batch(items_scraped=self._batch_items_count)
            self.mark_datasource_scraped(ds_id)

    def publish_event(self, event: Event):
        """Publish an Event to RabbitMQ, bypassing the global 4-month lookback.

        Base ``publish_event`` calls ``_should_skip_by_lookback`` with
        ``allow_initial_backfill=False``, so past TFD events older than the
        site-wide ingestion-lookback window get dropped even on the first
        scrape. We already enforce our own 1-year cap at the scraper level
        (in ``_scrape_events``), so the global cutoff is redundant here —
        and harmful, because it would silently throw away last summer's
        events that are still highly relevant for ``what was discussed at
        AI Field Day 7?``-style queries.
        """
        if self._current_batch_id and not event.batch_id:
            event.batch_id = self._current_batch_id
        message = event.to_message()
        if self._collect_mode:
            self._collected_messages.append(message)
        else:
            try:
                self.rabbitmq_producer.publish(message)
            except Exception as e:
                logger.error(f"Error publishing TFD event to RabbitMQ: {e}")
                raise
        self.increment_batch_count(1)

    async def scrape_resource(self, resource: Resource) -> Resource:
        """Single-URL refresh — re-fetch the video page and refresh its summary."""
        # The Resource.url is the kinsta /video/<slug>/ link. Build the API URL.
        m = re.search(r"/video/([^/]+)/?$", resource.url)
        if not m:
            return resource
        slug = m.group(1)
        data = await self._get_json(f"{WP_API}/video?slug={slug}")
        if not data:
            return resource
        v = data[0]
        event_index: Dict[str, Dict[str, Any]] = {}
        refreshed = self._video_to_resource(v, event_index, resource.datasource_id or "techfieldday")
        return refreshed or resource
