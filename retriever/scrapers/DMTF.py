"""
DMTF scraper.

Covers two datasources:
  dmtf_news     — press releases / news  (https://www.dmtf.org/about/news)
  dmtf_redfish  — Redfish specifications (https://www.dmtf.org/standards/redfish)

The news listing paginates with ?page=N.
The Redfish page is a single document listing with version numbers.

Resource categories:
  "news"          — press releases and announcements (dmtf_news)
  "specification" — Redfish spec documents with DSP numbers (dmtf_redfish)
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


_DATASOURCE_CFG: Dict[str, Dict[str, str]] = {
    "dmtf_news": {
        "base_url": "https://www.dmtf.org",
        "listing_url": "https://www.dmtf.org/about/news",
        "category": "news",
        "pagination": "query",  # ?page=N
    },
    "dmtf_redfish": {
        "base_url": "https://www.dmtf.org",
        "listing_url": "https://www.dmtf.org/standards/redfish",
        "category": "specification",
        "pagination": "none",
    },
}


class DMTFScraper(BaseScraper):
    """
    Scraper for DMTF news and Redfish specifications.

    News uses query-string pagination (?page=N).
    Redfish is a single page listing all spec documents.
    """

    scraper_name = "dmtf"

    def __init__(self):
        super().__init__()

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch *url* and return a BeautifulSoup, or None on error."""
        try:
            async with self.session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 404:
                    return None
                if resp.status != 200:
                    logger.warning(f"DMTF: HTTP {resp.status} for {url}")
                    return None
                html = await resp.text()
                return BeautifulSoup(html, "html.parser")
        except Exception as exc:
            logger.error(f"DMTF: error fetching {url}: {exc}")
            return None

    # ------------------------------------------------------------------
    # News listing parser
    # ------------------------------------------------------------------

    def _parse_news_page(
        self, soup: BeautifulSoup, base_url: str, datasource_id: str
    ) -> List[Resource]:
        """
        Parse the DMTF news listing page.

        DMTF news uses Drupal-style article lists:
          <article> or <div class="views-row"> / <div class="node--type-news">
        """
        resources: List[Resource] = []

        items = soup.find_all("article")
        if not items:
            items = soup.find_all(
                "div",
                class_=re.compile(r"views-row|node--type-news|news-item|post|item", re.I),
            )

        for item in items:
            try:
                heading = item.find(["h2", "h3", "h4"])
                link_el = None
                if heading:
                    link_el = heading.find("a", href=True)
                if not link_el:
                    link_el = item.find("a", href=True)
                if not link_el:
                    continue

                url = link_el["href"]
                if not url.startswith("http"):
                    url = urljoin(base_url, url)

                title = link_el.get_text(strip=True)
                if not title and heading:
                    title = heading.get_text(strip=True)
                if not title or len(title) < 4:
                    continue

                # Date
                publish_date: Optional[str] = None
                time_el = item.find("time")
                if time_el:
                    raw = time_el.get("datetime") or time_el.get_text(strip=True)
                    try:
                        publish_date = date_parse(raw).date().isoformat()
                    except Exception:
                        pass
                if not publish_date:
                    text = item.get_text(" ", strip=True)
                    m = re.search(
                        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
                        r"Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b",
                        text, re.I,
                    )
                    if m:
                        try:
                            publish_date = date_parse(m.group(0)).date().isoformat()
                        except Exception:
                            pass

                # Summary
                summary = ""
                for cls in ("field--name-body", "views-field-body", "summary", "teaser"):
                    div = item.find(class_=cls)
                    if div:
                        summary = div.get_text(" ", strip=True)[:500]
                        break
                if not summary:
                    p = item.find("p")
                    if p:
                        summary = p.get_text(strip=True)[:500]

                resources.append(
                    Resource(
                        title=title,
                        url=url,
                        category="news",
                        content=summary or "",
                        publish_date=publish_date,
                        datasource_id=datasource_id,
                    )
                )
            except Exception as exc:
                logger.warning(f"DMTF news: item parse error: {exc}")

        return resources

    def _has_next_page(self, soup: BeautifulSoup) -> bool:
        """Return True if a pager 'next' link exists on the page."""
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            if text in ("next", "next page", "»", "›"):
                return True
            # Drupal pager rel="next"
            if a.get("rel") == ["next"] or a.get("rel") == "next":
                return True
        # Also check aria-label
        next_link = soup.find("a", attrs={"aria-label": re.compile(r"next", re.I)})
        if next_link:
            return True
        return False

    # ------------------------------------------------------------------
    # Redfish specs parser
    # ------------------------------------------------------------------

    def _parse_redfish_page(
        self, soup: BeautifulSoup, base_url: str, datasource_id: str
    ) -> List[Resource]:
        """
        Parse the DMTF Redfish standards page.

        The page lists spec documents with DSP numbers (DSP0266, DSP0268, etc.),
        version numbers, and links to downloads/detail pages.
        """
        resources: List[Resource] = []
        seen: set = set()

        # Try table rows first
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                try:
                    link = row.find("a", href=True)
                    if not link:
                        continue
                    href = link["href"]
                    if not href.startswith("http"):
                        href = urljoin(base_url, href)
                    if href in seen:
                        continue
                    seen.add(href)

                    title = " ".join(c.get_text(strip=True) for c in cells[:3])[:200].strip()
                    if not title or len(title) < 4:
                        title = link.get_text(strip=True)

                    # DSP number pattern
                    dsp_match = re.search(r"\bDSP\d{4}\b", title, re.I)
                    if not dsp_match:
                        # Also check the href
                        dsp_match = re.search(r"\bDSP\d{4}\b", href, re.I)

                    # Extract version
                    ver_match = re.search(r"\bv?\d+\.\d+[\.\d]*\b", title)
                    version = ver_match.group(0) if ver_match else None

                    content = None
                    if dsp_match or version:
                        parts = []
                        if dsp_match:
                            parts.append(dsp_match.group(0))
                        if version:
                            parts.append(f"version {version}")
                        content = ", ".join(parts)

                    resources.append(
                        Resource(
                            title=title,
                            url=href,
                            category="specification",
                            content=content,
                            datasource_id=datasource_id,
                        )
                    )
                except Exception as exc:
                    logger.debug(f"DMTF Redfish row parse error: {exc}")

        # Fallback: scan links for DSP-numbered specs
        if not resources:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                title = a.get_text(strip=True)
                # Must look like a spec link
                if not (re.search(r"\bDSP\d{4}\b", title + href, re.I) or
                        re.search(r"\bredfish\b", title, re.I)):
                    continue
                if not href.startswith("http"):
                    href = urljoin(base_url, href)
                if href in seen or not title or len(title) < 4:
                    continue
                seen.add(href)
                resources.append(
                    Resource(
                        title=title,
                        url=href,
                        category="specification",
                        datasource_id=datasource_id,
                    )
                )

        return resources

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run_scraper(self, datasource_config: Dict[str, Any] = None):
        """
        Scrape DMTF news or Redfish specifications.

        News paginates with ?page=N; Redfish is a single page.
        Stops early when consecutive_duplicates_limit known URLs are seen.
        """
        if datasource_config is None:
            datasource_config = self.get_datasource_config("dmtf_news")

        datasource_id = datasource_config.get("datasource_id", "dmtf_news")
        scraper_delay = float(datasource_config.get("scraper_delay", 1.0))
        max_resources = int(datasource_config.get("max_resources", 200))
        consecutive_duplicates_limit = int(
            datasource_config.get("consecutive_duplicates_limit", 5)
        )
        is_full_refresh = datasource_config.get("is_full_refresh", False)

        if is_full_refresh:
            consecutive_duplicates_limit = 0
            max_resources = -1

        cfg = _DATASOURCE_CFG.get(datasource_id, _DATASOURCE_CFG["dmtf_news"])
        base_url = cfg["base_url"]
        listing_url = cfg["listing_url"]
        pagination = cfg["pagination"]

        logger.info(f"Starting DMTFScraper for {datasource_id} ({listing_url})")
        batch_id = self.start_batch(datasource_id)
        total_published = 0
        consecutive_duplicates = 0

        try:
            if datasource_id == "dmtf_redfish":
                # Single page — no pagination
                self.update_heartbeat()
                soup = await self._fetch_page(listing_url)
                if soup:
                    redfish_resources = self._parse_redfish_page(soup, base_url, datasource_id)
                    candidate_urls = [r.url for r in redfish_resources]
                    existing = self.batch_check_urls_exist(candidate_urls)

                    for res in redfish_resources:
                        res.batch_id = batch_id
                        self.update_current_processing(res, "dmtf redfish")

                        if self._should_skip_by_lookback(
                            "resource", datasource_id, res.publish_date,
                            res.title, res.url, allow_initial_backfill=True
                        ):
                            continue

                        if not existing.get(res.url, False):
                            self.publish_resource(res)
                            total_published += 1

                        if max_resources > 0 and total_published >= max_resources:
                            break

                        await asyncio.sleep(scraper_delay)

            else:
                # News — paginate with ?page=N (Drupal style, 0-indexed)
                page = 0
                while True:
                    current_url = listing_url if page == 0 else f"{listing_url}?page={page}"
                    self.update_heartbeat()
                    logger.info(f"DMTF: fetching news page {page}: {current_url}")

                    soup = await self._fetch_page(current_url)
                    if soup is None:
                        break

                    page_resources = self._parse_news_page(soup, base_url, datasource_id)
                    if not page_resources:
                        logger.info(f"DMTF: no items on page {page} — stopping")
                        break

                    candidate_urls = [r.url for r in page_resources]
                    existing = self.batch_check_urls_exist(candidate_urls)

                    page_new = 0
                    stop_early = False
                    for res in page_resources:
                        res.batch_id = batch_id
                        self.update_current_processing(res, f"dmtf news page {page}")

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
                                    f"DMTF: stopping after {consecutive_duplicates} consecutive duplicates"
                                )
                                stop_early = True
                                break
                        else:
                            consecutive_duplicates = 0
                            self.publish_resource(res)
                            total_published += 1
                            page_new += 1

                        if max_resources > 0 and total_published >= max_resources:
                            stop_early = True
                            break

                        await asyncio.sleep(scraper_delay)

                    if stop_early:
                        break

                    if page_new == 0 or not self._has_next_page(soup):
                        logger.info(f"DMTF: no more pages after page {page}")
                        break

                    page += 1

            logger.info(f"DMTFScraper ({datasource_id}) complete — published {total_published}")
            self.mark_datasource_scraped(datasource_id)
            self.end_batch(total_published)

        except Exception as exc:
            logger.error(f"DMTFScraper ({datasource_id}) error: {exc}", exc_info=True)
            self.end_batch(total_published)
            raise
