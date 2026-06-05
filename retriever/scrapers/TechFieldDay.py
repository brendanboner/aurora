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

# The Kinsta staging site is the canonical source for the WP REST API —
# techfieldday.com itself blocks scrapers (403 from any non-browser UA).
WP_API = "https://stg-techfielddayq-staging.kinsta.cloud/wp-json/wp/v2"

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

# WP per_page max is usually 100
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
                    logger.warning(f"TFD: HTTP {resp.status} for {url}")
                    return None
                return await resp.json(content_type=None)
        except Exception as exc:
            logger.error(f"TFD: error fetching {url}: {exc}")
            return None

    # ---------------------------------------------------------------
    # Lookup tables
    # ---------------------------------------------------------------

    async def _build_event_post_index(self) -> Dict[str, Dict[str, Any]]:
        """Build a slug→event-post lookup for the event custom post type.

        We only need it to resolve which TFD event series a video belongs
        to if the event-prefix shortcut fails. We page only as many event
        posts as we need (most recent first); after 1y back we stop.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_LOOKBACK_DAYS)
        out: Dict[str, Dict[str, Any]] = {}
        for page in range(1, 25):
            url = (
                f"{WP_API}/event"
                f"?per_page={PER_PAGE}&page={page}"
                f"&orderby=date&order=desc"
            )
            data = await self._get_json(url)
            if not data or isinstance(data, dict):
                break
            for ev in data:
                slug = ev.get("slug") or ""
                if slug:
                    out[slug.lower()] = ev
            # Stop once the page is fully older than cutoff
            try:
                last_date = ev.get("date") or ""
                if last_date:
                    last_dt = datetime.fromisoformat(last_date.replace("Z", "+00:00"))
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    if last_dt < cutoff:
                        break
            except Exception:
                pass
            await asyncio.sleep(PAGE_DELAY_S)
        logger.info(f"TFD: indexed {len(out)} event posts")
        return out

    # ---------------------------------------------------------------
    # Term extraction
    # ---------------------------------------------------------------

    @staticmethod
    def _extract_embedded_terms(video: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """Return a {taxonomy: [terms]} mapping from a `?_embed=wp:term` response.

        WP's `_embedded.wp:term` is a list of lists (one per taxonomy attached
        to the post). Each inner list contains term objects with name/slug/
        taxonomy. We bucket them by taxonomy for easier lookup downstream.
        """
        out: Dict[str, List[Dict[str, Any]]] = {}
        emb = (video.get("_embedded") or {}).get("wp:term") or []
        for terms_group in emb:
            for t in terms_group or []:
                if not t:
                    continue
                tax = t.get("taxonomy") or "?"
                out.setdefault(tax, []).append(t)
        return out

    @classmethod
    def _resolve_topic_datasource(
        cls,
        video: Dict[str, Any],
        event_index: Dict[str, Dict[str, Any]],
    ) -> Tuple[str, Optional[str], Optional[str]]:
        """Return (datasource_id, event_slug, event_name) for a video.

        Falls back to the parent `techfieldday` datasource for partner events
        (KubeCon, RSAC, Cisco Live, …) that don't follow the *FD<num> pattern.
        """
        terms = cls._extract_embedded_terms(video)
        # The first 'event' term on a video is the primary one (WP orders by
        # term creation; the canonical event for the video is the most recent
        # one tagged on it — but in our observed data the first slug matches
        # the link path, so we use that).
        # Robust approach: pick the event term whose slug is a known TFD
        # event-series prefix; otherwise fall through.
        event_terms = terms.get("event") or terms.get("?", [])  # Sometimes taxonomy field is absent
        # Filter only term objects that look like 'event' taxonomy entries —
        # they're the ones with slug matching the event's own slug regex.
        topic = None
        event_slug = None
        event_name = None
        # Strategy A: iterate event terms; first one with a topic prefix wins
        for term in event_terms:
            slug = (term.get("slug") or "").lower()
            mapped = _slug_to_topic(slug)
            if mapped:
                topic = mapped
                event_slug = slug
                event_name = term.get("name") or slug
                break
        # Strategy B: still no topic — try the event POST index via the
        # video's own slug pattern or the first event term slug
        if topic is None and event_terms:
            first = event_terms[0]
            event_slug = (first.get("slug") or "").lower()
            event_name = first.get("name") or event_slug
            post = event_index.get(event_slug)
            if post:
                # Map post.topic[term_id] to a topic slug via the embedded
                # taxonomy terms on the post — but we don't fetch those for
                # every event. Skip for now: fall through to parent.
                pass
        # Default: parent datasource
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

        terms = cls._extract_embedded_terms(video)
        personnel = terms.get("personnel") or []
        sponsors = terms.get("sponsor") or []
        configurations = terms.get("configuration") or []

        presenter = ", ".join(t.get("name") or "" for t in personnel[:3] if t.get("name"))
        sponsor = ", ".join(t.get("name") or "" for t in sponsors[:3] if t.get("name"))
        kind = (configurations[0].get("name") if configurations else "video") or "video"

        # toolset-meta carries youtube / vimeo IDs
        tm = video.get("toolset-meta") or {}
        vi = (tm.get("video-information") or {})
        youtube_id = (vi.get("youtube-id") or {}).get("raw") or ""
        vimeo_id = (vi.get("vimeo-id") or {}).get("raw") or ""

        ds_id, event_slug, event_name = cls._resolve_topic_datasource(video, event_index)
        if ds_id == "techfieldday" and datasource_id_default:
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
        """Fetch /wp/v2/video pages until older than cutoff. Returns count published."""
        event_index = await self._build_event_post_index()
        published = 0
        consecutive_dupes = 0
        max_dupes = 20  # stop pagination early if every recent video is unchanged

        for page in range(1, 50):
            if max_resources and published >= max_resources:
                break
            url = (
                f"{WP_API}/video"
                f"?per_page={PER_PAGE}&page={page}"
                f"&orderby=date&order=desc"
                f"&after={cutoff_iso}"
                f"&_embed=wp:term"
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
                        return published
                    continue
                consecutive_dupes = 0
                self.publish_resource(res)
                published += 1
                if max_resources and published >= max_resources:
                    return published

            await asyncio.sleep(scraper_delay or PAGE_DELAY_S)

        return published

    # ---------------------------------------------------------------
    # Events (for the calendar / Event nodes)
    # ---------------------------------------------------------------

    async def _scrape_events(self, datasource_id_default: str, cutoff_iso: str) -> int:
        """Pull the event POST type and publish them as calendar Events.

        Upcoming events get start_date in the future; past events from the
        last year get historical Event entries (useful for "what was
        discussed at AI Field Day 8?" queries).
        """
        published = 0
        # Cover future events too (some posts have future dates)
        # WP REST orderby=date with order=desc gives newest first.
        for page in range(1, 8):
            url = (
                f"{WP_API}/event"
                f"?per_page={PER_PAGE}&page={page}"
                f"&orderby=date&order=desc"
                f"&_embed=wp:term"
            )
            data = await self._get_json(url)
            if not data or isinstance(data, dict) or len(data) == 0:
                break

            done_window = False
            for ev in data:
                slug = (ev.get("slug") or "").lower()
                title = unescape(ev.get("title", {}).get("rendered") or "").strip()
                link = ev.get("link") or ""
                content_html = ev.get("content", {}).get("rendered") or ""
                description = _strip_html(content_html, max_chars=2500)
                date_iso = ev.get("date") or ev.get("date_gmt") or ""
                if not (title and link and date_iso):
                    continue
                # 1-year lookback ceiling — older events get dropped
                if date_iso < cutoff_iso:
                    done_window = True
                    continue

                topic = _slug_to_topic(slug)
                ds_id = f"techfieldday_{topic}" if topic and topic in KNOWN_TOPIC_SLUGS \
                        else datasource_id_default
                event_obj = Event(
                    name=title,
                    event_type="conference",
                    start_date=date_iso[:10],
                    description=description,
                    url=link,
                    datasource_id=ds_id,
                )
                self.publish_event(event_obj)
                published += 1
            if done_window:
                break
            await asyncio.sleep(PAGE_DELAY_S)

        return published

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
            videos_published = await self._scrape_videos(
                datasource_id_default=ds_id,
                cutoff_iso=cutoff_iso,
                max_resources=max_resources,
                scraper_delay=scraper_delay,
            )
            events_published = await self._scrape_events(
                datasource_id_default=ds_id,
                cutoff_iso=cutoff_iso,
            )
            logger.info(
                f"TFD ({ds_id}): published {videos_published} videos, "
                f"{events_published} events (cutoff={cutoff_iso[:10]})"
            )
        finally:
            self.end_batch(items_scraped=self._batch_items_count)
            self.mark_datasource_scraped(ds_id)

    async def scrape_resource(self, resource: Resource) -> Resource:
        """Single-URL refresh — re-fetch the video page and refresh its summary."""
        # The Resource.url is the kinsta /video/<slug>/ link. Build the API URL.
        m = re.search(r"/video/([^/]+)/?$", resource.url)
        if not m:
            return resource
        slug = m.group(1)
        data = await self._get_json(f"{WP_API}/video?slug={slug}&_embed=wp:term")
        if not data:
            return resource
        v = data[0]
        event_index: Dict[str, Dict[str, Any]] = {}
        refreshed = self._video_to_resource(v, event_index, resource.datasource_id or "techfieldday")
        return refreshed or resource
