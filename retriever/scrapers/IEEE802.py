"""
IEEE 802 Working Group scraper.

Covers three datasources:
  ieee802_11  — 802.11 / Wi-Fi working group  (https://www.ieee802.org/11/)
  ieee802_1   — 802.1 Bridging & Security WG  (https://www.ieee802.org/1/)
  ieee802_3   — 802.3 Ethernet WG             (https://www.ieee802.org/3/)

Each datasource also pulls published-standard abstracts from
https://standards.ieee.org/search/ for its respective 802.x family.

Resource categories
  "working_group_document"  — anything found on the WG listing pages
  "standard"                — published IEEE standards from the search portal
"""

import asyncio
import re
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlencode

import aiohttp
from bs4 import BeautifulSoup
from dateutil.parser import parse as date_parse

from .base import BaseScraper, Resource

logger = logging.getLogger(__name__)


# Per-datasource configuration constants
_DATASOURCE_CFG: Dict[str, Dict[str, str]] = {
    "ieee802_11": {
        "wg_url": "https://www.ieee802.org/11/",
        "standards_query": "802.11",
    },
    "ieee802_1": {
        "wg_url": "https://www.ieee802.org/1/",
        "standards_query": "802.1",
    },
    "ieee802_3": {
        "wg_url": "https://www.ieee802.org/3/",
        "standards_query": "802.3",
    },
}

_STANDARDS_SEARCH_BASE = "https://standards.ieee.org/search/"


class IEEE802Scraper(BaseScraper):
    """
    Scraper for IEEE 802 working-group pages and the IEEE standards search portal.

    One scraper class handles all three datasources (ieee802_11, ieee802_1,
    ieee802_3); the datasource_id in the config selects the correct target URL.
    """

    scraper_name = "ieee802"

    def __init__(self):
        super().__init__()

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch *url* and return a BeautifulSoup, or None on any error."""
        try:
            async with self.session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"IEEE802: HTTP {resp.status} for {url}")
                    return None
                html = await resp.text()
                return BeautifulSoup(html, "html.parser")
        except Exception as exc:
            logger.error(f"IEEE802: error fetching {url}: {exc}")
            return None

    # ------------------------------------------------------------------
    # WG page parsers
    # ------------------------------------------------------------------

    def _parse_wg_page(
        self, soup: BeautifulSoup, base_url: str, datasource_id: str
    ) -> List[Resource]:
        """
        Extract working-group documents from an 802.x WG page.

        Looks for:
          1. <table> rows that appear to list drafts / approved amendments.
          2. Fallback: any <a href> whose text looks like a document title.
        """
        resources: List[Resource] = []
        seen: set = set()

        # --- Strategy 1: parse tables -----------------------------------------
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows[1:]:  # skip header row
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                try:
                    # Find a link inside this row
                    link = row.find("a", href=True)
                    if not link:
                        continue
                    href = link["href"]
                    # Skip links to Mentor (login required) and mailto
                    if "mentor.ieee.org" in href or href.startswith("mailto"):
                        continue
                    url = urljoin(base_url, href)
                    if url in seen:
                        continue
                    seen.add(url)

                    title = link.get_text(strip=True)
                    if not title or len(title) < 4:
                        # Fall back to full row text
                        title = " ".join(c.get_text(strip=True) for c in cells[:3])
                        title = title[:200].strip()
                    if not title:
                        continue

                    # Look for a date in the row
                    publish_date = self._extract_date_from_cells(cells)

                    resources.append(
                        Resource(
                            title=title,
                            url=url,
                            category="working_group_document",
                            publish_date=publish_date,
                            datasource_id=datasource_id,
                        )
                    )
                except Exception as exc:
                    logger.debug(f"IEEE802: row parse error: {exc}")

        # --- Strategy 2: anchor scan (fallback or supplement) -----------------
        # Only run if tables yielded nothing meaningful
        if len(resources) < 3:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "mentor.ieee.org" in href or href.startswith("mailto"):
                    continue
                # Only include links that look like document references (PDF / doc pages)
                if not re.search(r"\.(pdf|docx?|htm|html)$", href, re.I) and \
                        not re.search(r"\d{3,}", href):
                    continue
                url = urljoin(base_url, href)
                if url in seen or url == base_url:
                    continue
                seen.add(url)
                title = a.get_text(strip=True)
                if not title or len(title) < 5:
                    continue
                resources.append(
                    Resource(
                        title=title,
                        url=url,
                        category="working_group_document",
                        datasource_id=datasource_id,
                    )
                )

        return resources

    def _extract_date_from_cells(self, cells) -> Optional[str]:
        """Try to parse a date string from table cells."""
        for cell in cells:
            text = cell.get_text(strip=True)
            # Match patterns like "2024-03-11", "March 2024", "11 Mar 2024"
            if re.match(r"\d{4}-\d{2}-\d{2}", text):
                return text[:10]
            m = re.search(
                r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b",
                text,
                re.I,
            )
            if m:
                try:
                    return date_parse(m.group(0)).date().isoformat()
                except Exception:
                    pass
            m2 = re.search(r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b", text)
            if m2:
                try:
                    return date_parse(m2.group(1)).date().isoformat()
                except Exception:
                    pass
        return None

    # ------------------------------------------------------------------
    # IEEE standards search portal
    # ------------------------------------------------------------------

    def _parse_standards_search(
        self, soup: BeautifulSoup, datasource_id: str
    ) -> List[Resource]:
        """
        Parse the IEEE standards search results page.

        The page renders standard cards with title, status badge, and date.
        """
        resources: List[Resource] = []

        # Cards are either <article> or <div class="...result...">
        cards = soup.find_all("article") or soup.find_all(
            "div", class_=re.compile(r"result|card|item|standard", re.I)
        )

        for card in cards:
            try:
                link = card.find("a", href=True)
                if not link:
                    continue
                href = link["href"]
                if not href.startswith("http"):
                    href = urljoin("https://standards.ieee.org", href)
                title = link.get_text(strip=True) or card.get_text(" ", strip=True)[:150]
                if not title or len(title) < 5:
                    continue

                # Status badge
                status_el = card.find(class_=re.compile(r"status|badge|label", re.I))
                status_text = status_el.get_text(strip=True).lower() if status_el else ""
                category = "standard" if "active" in status_text or "approved" in status_text else "working_group_document"

                # Date
                publish_date: Optional[str] = None
                time_el = card.find("time")
                if time_el:
                    raw = time_el.get("datetime") or time_el.get_text(strip=True)
                    try:
                        publish_date = date_parse(raw).date().isoformat()
                    except Exception:
                        pass

                resources.append(
                    Resource(
                        title=title,
                        url=href,
                        category=category,
                        publish_date=publish_date,
                        datasource_id=datasource_id,
                    )
                )
            except Exception as exc:
                logger.debug(f"IEEE802 standards card parse error: {exc}")

        return resources

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run_scraper(self, datasource_config: Dict[str, Any] = None):
        """
        Scrape one IEEE 802 datasource (ieee802_11, ieee802_1, or ieee802_3).

        Paginates the WG listing page then fetches standards search results.
        Stops early when consecutive_duplicates_limit known URLs are seen.
        """
        if datasource_config is None:
            datasource_config = self.get_datasource_config("ieee802_11")

        datasource_id = datasource_config.get("datasource_id", "ieee802_11")
        scraper_delay = float(datasource_config.get("scraper_delay", 1.0))
        max_resources = int(datasource_config.get("max_resources", 200))
        consecutive_duplicates_limit = int(
            datasource_config.get("consecutive_duplicates_limit", 5)
        )
        is_full_refresh = datasource_config.get("is_full_refresh", False)

        if is_full_refresh:
            consecutive_duplicates_limit = 0
            max_resources = -1

        cfg = _DATASOURCE_CFG.get(datasource_id, _DATASOURCE_CFG["ieee802_11"])
        wg_url = cfg["wg_url"]
        standards_query = cfg["standards_query"]

        logger.info(f"Starting IEEE802Scraper for {datasource_id} ({wg_url})")
        batch_id = self.start_batch(datasource_id)
        total_published = 0
        consecutive_duplicates = 0

        try:
            # ---- 1. Scrape the WG page ----------------------------------------
            self.update_heartbeat()
            soup = await self._fetch_page(wg_url)
            if soup:
                wg_resources = self._parse_wg_page(soup, wg_url, datasource_id)
                candidate_urls = [r.url for r in wg_resources]
                existing = self.batch_check_urls_exist(candidate_urls)

                for res in wg_resources:
                    res.batch_id = batch_id
                    self.update_current_processing(res, "ieee802 wg page")

                    if self._should_skip_by_lookback(
                        "resource", datasource_id, res.publish_date,
                        res.title, res.url, allow_initial_backfill=True
                    ):
                        continue

                    if existing.get(res.url, False):
                        consecutive_duplicates += 1
                        if (
                            not is_full_refresh
                            and consecutive_duplicates_limit > 0
                            and consecutive_duplicates >= consecutive_duplicates_limit
                        ):
                            logger.info(
                                f"IEEE802: stopping WG page after "
                                f"{consecutive_duplicates} consecutive duplicates"
                            )
                            break
                    else:
                        consecutive_duplicates = 0
                        self.publish_resource(res)
                        total_published += 1

                    if max_resources > 0 and total_published >= max_resources:
                        break

                    await asyncio.sleep(scraper_delay)

            # ---- 2. Scrape IEEE standards search ------------------------------
            if max_resources <= 0 or total_published < max_resources:
                await asyncio.sleep(scraper_delay)
                self.update_heartbeat()
                params = urlencode({"q": standards_query, "status": "active"})
                search_url = f"{_STANDARDS_SEARCH_BASE}?{params}"
                std_soup = await self._fetch_page(search_url)
                if std_soup:
                    std_resources = self._parse_standards_search(std_soup, datasource_id)
                    std_urls = [r.url for r in std_resources]
                    std_existing = self.batch_check_urls_exist(std_urls)

                    for res in std_resources:
                        res.batch_id = batch_id
                        self.update_current_processing(res, "ieee standards search")

                        if self._should_skip_by_lookback(
                            "resource", datasource_id, res.publish_date,
                            res.title, res.url, allow_initial_backfill=True
                        ):
                            continue

                        if not std_existing.get(res.url, False):
                            self.publish_resource(res)
                            total_published += 1

                        if max_resources > 0 and total_published >= max_resources:
                            break

                        await asyncio.sleep(scraper_delay)

            logger.info(f"IEEE802Scraper ({datasource_id}) complete — published {total_published}")
            self.end_batch(total_published)

        except Exception as exc:
            logger.error(f"IEEE802Scraper ({datasource_id}) error: {exc}", exc_info=True)
            self.end_batch(total_published)
            raise
