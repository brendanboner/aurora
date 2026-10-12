"""
MEF (Metro Ethernet Forum) scraper.

Covers two datasources:
  mef_specs  — technical specifications  (https://www.mef.net/resources/technical-specifications/)
  mef_news   — news and updates          (https://www.mef.net/news-and-updates/)

Both pages use WordPress-style pagination (/page/N/).

Resource categories:
  "specification"  — technical specs (mef_specs)
  "news"           — newsroom articles (mef_news)
"""

import asyncio
import re
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup
from dateutil.parser import parse as date_parse

from .base import BaseScraper, Resource

logger = logging.getLogger(__name__)


_DATASOURCE_CFG: Dict[str, Dict[str, str]] = {
    "mef_specs": {
        "base_url": "https://www.mef.net",
        "listing_url": "https://www.mef.net/resources/technical-specifications/",
        "category": "specification",
    },
    "mef_news": {
        "base_url": "https://www.mef.net",
        "listing_url": "https://www.mef.net/news-and-updates/",
        "category": "news",
    },
}


class MEFScraper(BaseScraper):
    """
    Scraper for MEF technical specifications and news.

    Both datasources use the same WordPress-style paginated listing structure.
    """

    scraper_name = "mef"

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
                    return None  # end of pagination
                if resp.status != 200:
                    logger.warning(f"MEF: HTTP {resp.status} for {url}")
                    return None
                html = await resp.text()
                return BeautifulSoup(html, "html.parser")
        except Exception as exc:
            logger.error(f"MEF: error fetching {url}: {exc}")
            return None

    # ------------------------------------------------------------------
    # Page parsers
    # ------------------------------------------------------------------

    def _parse_listing_page(
        self,
        soup: BeautifulSoup,
        base_url: str,
        datasource_id: str,
        category: str,
    ) -> List[Resource]:
        """
        Extract resources from a MEF listing page.

        MEF uses WordPress <article> elements and also <div class="resource...">
        cards for the specs listing.  We try both.
        """
        resources: List[Resource] = []

        items = soup.find_all("article")
        if not items:
            # Try common resource/card div patterns
            items = soup.find_all(
                "div", class_=re.compile(r"resource|post|card|item|entry", re.I)
            )

        for item in items:
            try:
                # Title + URL — prefer heading tags
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

                # Spec number — look for patterns like "MEF 70.1", "MEF 55"
                spec_number: Optional[str] = None
                m = re.search(r"\bMEF\s+\d[\d.]*\b", title, re.I)
                if m:
                    spec_number = m.group(0)

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
                    # Fallback: text date pattern
                    text = item.get_text(" ", strip=True)
                    m2 = re.search(
                        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
                        r"Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b",
                        text, re.I,
                    )
                    if m2:
                        try:
                            publish_date = date_parse(m2.group(0)).date().isoformat()
                        except Exception:
                            pass

                # Excerpt
                summary = ""
                for cls in ("entry-content", "entry-summary", "post-content", "excerpt"):
                    div = item.find(class_=cls)
                    if div:
                        summary = div.get_text(" ", strip=True)[:500]
                        break
                if not summary:
                    p = item.find("p")
                    if p:
                        summary = p.get_text(strip=True)[:500]

                content = summary
                if spec_number and spec_number not in (content or ""):
                    content = f"{spec_number}. {summary}".strip(". ")

                resources.append(
                    Resource(
                        title=title,
                        url=url,
                        category=category,
                        content=content or "",
                        publish_date=publish_date,
                        datasource_id=datasource_id,
                    )
                )
            except Exception as exc:
                logger.warning(f"MEF: item parse error: {exc}")

        return resources

    def _next_page_url(
        self, soup: BeautifulSoup, current_page: int, base_listing: str
    ) -> Optional[str]:
        """
        Return the next pagination URL, or None if on the last page.

        Tries WordPress /page/N/ path first, then looks for a "next" link.
        """
        # Look for explicit next link
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            if text in ("next", "next page", "»", "›", "older posts", "load more"):
                href = a["href"]
                if not href.startswith("http"):
                    href = urljoin(base_listing, href)
                return href
        # WordPress /page/N/ pattern
        next_page = current_page + 1
        return f"{base_listing.rstrip('/')}/page/{next_page}/"

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run_scraper(self, datasource_config: Dict[str, Any] = None):
        """
        Scrape MEF specs or news in incremental mode.

        Paginates until consecutive_duplicates_limit known URLs in a row.
        """
        if datasource_config is None:
            datasource_config = self.get_datasource_config("mef_specs")

        datasource_id = datasource_config.get("datasource_id", "mef_specs")
        scraper_delay = float(datasource_config.get("scraper_delay", 1.0))
        max_resources = int(datasource_config.get("max_resources", 200))
        consecutive_duplicates_limit = int(
            datasource_config.get("consecutive_duplicates_limit", 5)
        )
        is_full_refresh = datasource_config.get("is_full_refresh", False)

        if is_full_refresh:
            consecutive_duplicates_limit = 0
            max_resources = -1

        cfg = _DATASOURCE_CFG.get(datasource_id, _DATASOURCE_CFG["mef_specs"])
        base_url = cfg["base_url"]
        listing_url = cfg["listing_url"]
        category = cfg["category"]

        logger.info(f"Starting MEFScraper for {datasource_id} ({listing_url})")
        batch_id = self.start_batch(datasource_id)
        total_published = 0
        consecutive_duplicates = 0
        page = 1

        try:
            while True:
                current_url = listing_url if page == 1 else f"{listing_url.rstrip('/')}/page/{page}/"
                self.update_heartbeat()
                logger.info(f"MEF: fetching page {page}: {current_url}")

                soup = await self._fetch_page(current_url)
                if soup is None:
                    break

                page_resources = self._parse_listing_page(soup, base_url, datasource_id, category)
                if not page_resources:
                    logger.info(f"MEF: no items on page {page} — stopping")
                    break

                candidate_urls = [r.url for r in page_resources]
                existing = self.batch_check_urls_exist(candidate_urls)

                page_new = 0
                stop_early = False
                for res in page_resources:
                    res.batch_id = batch_id
                    self.update_current_processing(res, f"mef page {page}")

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
                                f"MEF: stopping after {consecutive_duplicates} consecutive duplicates"
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

                if page_new == 0:
                    logger.info(f"MEF: no new items on page {page} — stopping")
                    break

                page += 1

            logger.info(f"MEFScraper ({datasource_id}) complete — published {total_published}")
            self.mark_datasource_scraped(datasource_id)
            self.end_batch(total_published)

        except Exception as exc:
            logger.error(f"MEFScraper ({datasource_id}) error: {exc}", exc_info=True)
            self.end_batch(total_published)
            raise
