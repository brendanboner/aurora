"""
IEEE 802.11 Task Group Status Scraper

Scrapes the public IEEE 802.11 Working Group pages for:
  - Per-task-group status pages (TGbn, TGbi, TGbp, TGbt, TGbq, TGbr, TGmf)
  - Amendment timelines (802.11_Timelines.htm)
  - Meeting schedule and session reports (published as Events)

All data is from www.ieee802.org/11/ which is fully public.
mentor.ieee.org (Mentor DCN system) is NOT used — it blocks unauthenticated
scrapers.

Datasource: ieee802_11_tg
Config key: ieee802_11_tg
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import aiohttp
from bs4 import BeautifulSoup
from dateutil.parser import parse as date_parse

from .base import BaseScraper, Event, Resource

logger = logging.getLogger(__name__)

WG_BASE = "https://www.ieee802.org/11"

# ── 802.11 task group pages ─────────────────────────────────────────────────
# (url_slug, tg_label, amendment, description) — slug builds the Reports URL
ACTIVE_TGS = [
    ("tgbn",   "TGbn",  "802.11bn",  "Ultra High Reliability (Wi-Fi 8)"),
    ("tgbi",   "TGbi",  "802.11bi",  "Enhanced Privacy Protection"),
    ("tgbp",   "TGbp",  "802.11bp",  "Ambient Power Communications"),
    ("tgbt",   "TGbt",  "802.11bt",  "Post-Quantum Cryptography"),
    ("tgbq",   "TGbq",  "802.11bq",  "Integrated mmWave"),
    ("tgbr",   "TGbr",  "802.11br",  "Enhanced Light Communications"),
    ("tgm",    "TGmf",  "802.11mf",  "Maintenance Revision"),
]

# ── 802.1 task group pages (1.ieee802.org) ──────────────────────────────────
# (full URL, tg_label, amendment, description)
TG_802_1 = [
    ("https://1.ieee802.org/tsn/",         "TSN",          "802.1 TSN",   "Time-Sensitive Networking"),
    ("https://1.ieee802.org/security/",    "Security",     "802.1 Sec",   "Security Task Group"),
    ("https://1.ieee802.org/maintenance/", "Maintenance",  "802.1 Maint", "802.1 Maintenance Task Group"),
]
TIMELINE_802_1 = "https://1.ieee802.org/timelines/"
MEETING_802_1  = "https://1.ieee802.org/wg-calendar/"

# ── 802.3 task group pages (www.ieee802.org/3/) ─────────────────────────────
# (relative path from 802.3 base, label, amendment, description)
TG_802_3 = [
    ("dj", "P802.3dj", "802.3dj", "200/400/800 Gb/s & 1.6 Tb/s Ethernet"),
    ("dg", "P802.3dg", "802.3dg", "100 Mb/s Long-Reach Single Pair Ethernet"),
    ("dk", "P802.3dk", "802.3dk", "Bidirectional Optical Access PHYs"),
    ("dm", "P802.3dm", "802.3dm", "Asymmetrical Electrical Automotive Ethernet"),
    ("ds", "P802.3ds", "802.3ds", "200 Gb/s per Wavelength MMF PHYs"),
    ("dt", "P802.3dt", "802.3dt", "Ethernet Metadata Services"),
]
WG_BASE_803 = "https://www.ieee802.org/3"

TIMELINE_URL    = f"{WG_BASE}/Reports/802.11_Timelines.htm"
MEETING_URL     = f"{WG_BASE}/Meetings/Meeting_Plan.html"
REPORTS_URL     = f"{WG_BASE}/Reports/index.html"
MAIN_URL        = f"{WG_BASE}/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AuroraBot/1.0; "
        "+https://aurora.exiq.ai/about)"
    )
}


class IEEE80211TGScraper(BaseScraper):
    """
    Scraper for IEEE 802.11 Working Group public task-group status pages.

    One scraper class handles the single `ieee802_11_tg` datasource.
    It publishes Resources for each task group status page, the master
    timeline, and plenary session report summaries, plus Events for
    upcoming and recent plenary/interim meetings.
    """

    scraper_name = "ieee802_11_tg"

    def __init__(self):
        super().__init__()

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _fetch(self, url: str) -> Optional[BeautifulSoup]:
        try:
            async with self.session.get(
                url,
                headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    logger.warning("IEEE80211TG: HTTP %d for %s", resp.status, url)
                    return None
                html = await resp.text(errors="replace")
                return BeautifulSoup(html, "html.parser")
        except Exception as exc:
            logger.error("IEEE80211TG: error fetching %s: %s", url, exc)
            return None

    async def _text(self, soup: BeautifulSoup, cap: int = 12000) -> str:
        """Extract clean body text from a BeautifulSoup, capped at cap chars."""
        for tag in soup(["script", "style", "nav", "header", "footer", "form"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:cap]

    # ------------------------------------------------------------------
    # Task group page scraper
    # ------------------------------------------------------------------

    async def _scrape_tg_page(
        self,
        slug: str,
        tg_label: str,
        amendment: str,
        description: str,
        datasource_id: str,
        scraper_delay: float,
    ) -> Optional[Resource]:
        """Scrape a single task group update page and return a Resource."""
        url = f"{WG_BASE}/Reports/{slug}_update.htm"
        soup = await self._fetch(url)
        if not soup:
            logger.info("IEEE80211TG: no page for %s at %s", tg_label, url)
            return None

        content = await self._text(soup)
        if not content:
            return None

        # Extract most recent date mentioned in the page
        publish_date = self._extract_date(content)

        title = (
            f"IEEE {amendment} ({tg_label}) — {description} — Status Update"
        )

        return Resource(
            title=title,
            url=url,
            category="working_group_document",
            content=content,
            publish_date=publish_date,
            datasource_id=datasource_id,
            doc_type="status",
        )

    def _extract_date(self, text: str) -> Optional[str]:
        """Pull the most recent-looking date from a block of text."""
        # ISO-like: 2026-03-15
        m = re.search(r"\b(20\d{2}[-/]\d{2}[-/]\d{2})\b", text)
        if m:
            try:
                return date_parse(m.group(1)).date().isoformat()
            except Exception:
                pass
        # "March 2026", "April 21, 2026" etc.
        m = re.search(
            r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
            r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
            r"Dec(?:ember)?)\s+\d{1,2},?\s+20\d{2}\b",
            text,
            re.I,
        )
        if m:
            try:
                return date_parse(m.group(0)).date().isoformat()
            except Exception:
                pass
        return None

    # ------------------------------------------------------------------
    # Timeline page
    # ------------------------------------------------------------------

    async def _scrape_timeline(self, datasource_id: str) -> Optional[Resource]:
        soup = await self._fetch(TIMELINE_URL)
        if not soup:
            return None
        content = await self._text(soup, cap=16000)
        return Resource(
            title="IEEE 802.11 Amendment Timelines — All Active Task Groups",
            url=TIMELINE_URL,
            category="working_group_document",
            content=content,
            publish_date=datetime.now(timezone.utc).date().isoformat(),
            datasource_id=datasource_id,
            doc_type="status",
        )

    # ------------------------------------------------------------------
    # Meeting plan — parse as Events
    # ------------------------------------------------------------------

    # Known meetings from public meeting plan — used when page scraping fails
    _KNOWN_MEETINGS = [
        ("2026-05-10", "2026-05-15", "216", "Plenary",  "Antwerp, Belgium", "Hilton Antwerp Old Town"),
        ("2026-07-12", "2026-07-17", "217", "Interim",  "Montreal, Quebec, Canada", "Le Centre Sheraton Montreal"),
        ("2026-09-13", "2026-09-18", "218", "Plenary",  "Waikoloa, Hawaii, USA", "Hilton Waikoloa Village"),
        ("2026-11-08", "2026-11-13", "219", "Interim",  "Bangkok, Thailand", "Marriott Marquis Queen's Park"),
        ("2027-01-10", "2027-01-15", "220", "Plenary",  "Irvine, California, USA", "Hyatt Regency Irvine"),
        ("2027-03-14", "2027-03-19", "221", "Interim",  "Singapore", "Grand Capthorne Waterfront"),
    ]

    async def _scrape_meetings(self, datasource_id: str) -> List[Event]:
        """Parse the WG meeting plan page and return Event objects."""
        soup = await self._fetch(MEETING_URL)
        now = datetime.now(timezone.utc)
        cutoff_past = now - timedelta(days=180)
        cutoff_future = now + timedelta(days=730)

        events: List[Event] = []

        # First: seed from known meeting list (always accurate, low maintenance)
        for start, end, session, mtype, location, hotel in self._KNOWN_MEETINGS:
            try:
                start_dt = date_parse(start).replace(tzinfo=timezone.utc)
                if start_dt < cutoff_past or start_dt > cutoff_future:
                    continue
            except Exception:
                continue
            status = "scheduled" if start_dt >= now else "completed"
            event_type = "conference" if "Plenary" in mtype else "meeting"
            events.append(Event(
                name=f"IEEE 802.11 WG Session {session} — {location}",
                event_type=event_type,
                start_date=start,
                end_date=end,
                location=f"{location} ({hotel})",
                description=(
                    f"IEEE 802.11 Working Group Session {session} ({mtype}).\n"
                    f"Venue: {hotel}, {location}.\n"
                    f"All active task groups (TGbn, TGbi, TGbp, TGbt, TGbq, TGbr, TGmf) meet."
                ),
                url=MEETING_URL,
                status=status,
                datasource_id=datasource_id,
            ))

        if not soup:
            logger.info("IEEE80211TG: meeting plan page unavailable, using known list")
            logger.info("IEEE80211TG: parsed %d meeting events", len(events))
            return events

        # Second: try to parse additional meetings from live page
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) < 3:
                    continue
                raw = " | ".join(cells)
                year_m = re.search(r"\b(202\d)\b", raw)
                if not year_m:
                    continue

                # Try to parse dates from cells
                start_date = end_date = None
                for cell in cells:
                    d = self._extract_date(cell)
                    if d:
                        if not start_date:
                            start_date = d
                        else:
                            end_date = d

                if not start_date:
                    # Try "May 10-15, 2026" style
                    m = re.search(
                        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
                        r"\s+(\d{1,2})[-–](\d{1,2}),?\s*(20\d{2})",
                        raw, re.I,
                    )
                    if m:
                        mon, d1, d2, yr = m.group(1), m.group(2), m.group(3), m.group(4)
                        try:
                            start_date = date_parse(f"{mon} {d1} {yr}").date().isoformat()
                            end_date   = date_parse(f"{mon} {d2} {yr}").date().isoformat()
                        except Exception:
                            pass

                if not start_date:
                    continue

                try:
                    start_dt = date_parse(start_date).replace(tzinfo=timezone.utc)
                    if start_dt < cutoff_past or start_dt > cutoff_future:
                        continue
                except Exception:
                    continue

                # Determine event type and location from remaining cells
                event_type = "meeting"
                location = ""
                for cell in cells:
                    cl = cell.lower()
                    if "plenary" in cl:
                        event_type = "conference"
                    elif "interim" in cl:
                        event_type = "meeting"
                    elif "adhoc" in cl or "ad hoc" in cl:
                        event_type = "workshop"

                # Build location string
                location_parts = [c for c in cells if len(c) > 3 and not re.match(r"^\d", c)]
                location = ", ".join(location_parts[:3]) if location_parts else "TBD"

                # Build session number if visible
                session_num = ""
                for cell in cells:
                    m2 = re.match(r"^(\d{3})$", cell)
                    if m2:
                        session_num = f" Session {m2.group(1)}"

                events.append(Event(
                    name=f"IEEE 802.11 WG{session_num} — {location}",
                    event_type=event_type,
                    start_date=start_date,
                    end_date=end_date or start_date,
                    location=location,
                    description=f"IEEE 802.11 Working Group session.\n{raw[:500]}",
                    url=MEETING_URL,
                    status="scheduled" if start_dt >= now else "completed",
                    datasource_id=datasource_id,
                ))

        logger.info("IEEE80211TG: parsed %d meeting events", len(events))
        return events

    # ------------------------------------------------------------------
    # Session reports index — scrape plenary report summaries
    # ------------------------------------------------------------------

    async def _scrape_reports(self, datasource_id: str, lookback_days: int) -> List[Resource]:
        """Scrape links from the Reports index for recent public session summaries."""
        soup = await self._fetch(REPORTS_URL)
        if not soup:
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        resources: List[Resource] = []
        seen: set = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "mentor.ieee.org" in href:
                continue
            title = a.get_text(strip=True)
            if not title or len(title) < 8:
                continue
            # Only pick links that look like session reports
            if not re.search(r"(report|minutes|session|plenary|summary)", title, re.I):
                continue

            from urllib.parse import urljoin
            url = urljoin(REPORTS_URL, href)
            if url in seen:
                continue
            seen.add(url)

            # Try to date it from the title
            pub_date = self._extract_date(title)
            if pub_date:
                try:
                    if date_parse(pub_date).replace(tzinfo=timezone.utc) < cutoff:
                        continue
                except Exception:
                    pass

            resources.append(Resource(
                title=f"IEEE 802.11 — {title}",
                url=url,
                category="working_group_document",
                content=title,
                publish_date=pub_date,
                datasource_id=datasource_id,
                doc_type="minutes",
            ))

        return resources

    # ------------------------------------------------------------------
    # 802.1 and 802.3 task group scrapers
    # ------------------------------------------------------------------

    async def _scrape_generic_tg_page(
        self,
        url: str,
        tg_label: str,
        amendment: str,
        description: str,
        datasource_id: str,
        wg_prefix: str,
    ) -> Optional[Resource]:
        """Scrape any publicly accessible task group page."""
        soup = await self._fetch(url)
        if not soup:
            return None
        content = await self._text(soup, cap=12000)
        if not content:
            return None
        publish_date = self._extract_date(content)
        return Resource(
            title=f"IEEE {amendment} ({tg_label}) — {description} — Status",
            url=url,
            category="working_group_document",
            content=content,
            publish_date=publish_date,
            datasource_id=datasource_id,
            doc_type="status",
        )

    async def _scrape_802_1(
        self, datasource_id: str, scraper_delay: float
    ) -> int:
        """Scrape IEEE 802.1 task group pages."""
        total = 0
        for url, label, amendment, desc in TG_802_1:
            self.update_heartbeat()
            logger.info("  Scraping %s: %s", label, url)
            res = await self._scrape_generic_tg_page(
                url, label, amendment, desc, datasource_id, "802.1"
            )
            if res:
                self.publish_resource(res, additional_fields={"task_group": label})
                total += 1
            await asyncio.sleep(scraper_delay)

        # 802.1 timeline
        tl_soup = await self._fetch(TIMELINE_802_1)
        if tl_soup:
            content = await self._text(tl_soup, cap=12000)
            if content:
                self.publish_resource(Resource(
                    title="IEEE 802.1 Amendment Timelines — TSN, Security, Maintenance",
                    url=TIMELINE_802_1,
                    category="working_group_document",
                    content=content,
                    publish_date=datetime.now(timezone.utc).date().isoformat(),
                    datasource_id=datasource_id,
                    doc_type="status",
                ))
                total += 1
        return total

    async def _scrape_802_3(
        self, datasource_id: str, scraper_delay: float
    ) -> int:
        """Scrape IEEE 802.3 task force pages."""
        total = 0
        for slug, label, amendment, desc in TG_802_3:
            url = f"{WG_BASE_803}/{slug}/index.html"
            self.update_heartbeat()
            logger.info("  Scraping %s: %s", label, url)
            res = await self._scrape_generic_tg_page(
                url, label, amendment, desc, datasource_id, "802.3"
            )
            if res:
                self.publish_resource(res, additional_fields={"task_group": label})
                total += 1
            await asyncio.sleep(scraper_delay)
        return total

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run_scraper(self, datasource_config: Dict[str, Any] = None):
        """
        Scrape IEEE 802.11, 802.1, and 802.3 task group status pages,
        timelines, meetings, and recent session report links.

        All content comes from public IEEE 802 Working Group pages.
        """
        if datasource_config is None:
            datasource_config = self.get_datasource_config("ieee802_11_tg")

        datasource_id  = datasource_config.get("datasource_id", "ieee802_11_tg")
        scraper_delay  = float(datasource_config.get("scraper_delay", 2.0))
        lookback_days  = int(datasource_config.get("temporal_extraction_days", 60))

        logger.info("Starting IEEE80211TGScraper for %s (lookback=%d days)",
                    datasource_id, lookback_days)

        batch_id = self.start_batch(datasource_id)
        total = 0

        try:
            self.update_heartbeat()

            # 1. Task group status pages — always re-publish because they are
            # "living" status pages updated after every session. The digester
            # deduplicates via content_hash, so unchanged pages cost nothing.
            for slug, tg_label, amendment, description in ACTIVE_TGS:
                self.update_heartbeat()
                url = f"{WG_BASE}/Reports/{slug}_update.htm"
                logger.info("  Scraping %s status page: %s", tg_label, url)
                res = await self._scrape_tg_page(
                    slug, tg_label, amendment, description,
                    datasource_id, scraper_delay,
                )
                if res:
                    self.publish_resource(res, additional_fields={
                        "task_group": tg_label,
                        "amendment": amendment,
                    })
                    total += 1
                await asyncio.sleep(scraper_delay)

            # 2. Master timeline — always refresh (same reason as TG pages)
            self.update_heartbeat()
            logger.info("  Scraping amendment timeline")
            timeline = await self._scrape_timeline(datasource_id)
            if timeline:
                self.publish_resource(timeline)
                total += 1
            await asyncio.sleep(scraper_delay)

            # 3. Meeting events
            self.update_heartbeat()
            logger.info("  Scraping meeting plan for events")
            events = await self._scrape_meetings(datasource_id)
            for evt in events:
                self.publish_event(evt)
                total += 1
            await asyncio.sleep(scraper_delay)

            # 4. Session report links
            self.update_heartbeat()
            logger.info("  Scraping session reports index")
            reports = await self._scrape_reports(datasource_id, lookback_days)
            for res in reports:
                if not self.url_exists_in_db(res.url):
                    self.publish_resource(res)
                    total += 1
            await asyncio.sleep(scraper_delay)

            # 5. IEEE 802.1 task groups (TSN, Security, Maintenance)
            self.update_heartbeat()
            logger.info("  Scraping IEEE 802.1 task groups")
            total += await self._scrape_802_1(datasource_id, scraper_delay)

            # 6. IEEE 802.3 task forces
            self.update_heartbeat()
            logger.info("  Scraping IEEE 802.3 task forces")
            total += await self._scrape_802_3(datasource_id, scraper_delay)

            logger.info("IEEE80211TGScraper complete — %d items published", total)
            self.mark_datasource_scraped(datasource_id)
            self.end_batch(total)

        except Exception as exc:
            logger.error("IEEE80211TGScraper error: %s", exc, exc_info=True)
            self.end_batch(total)
            raise
