"""
ONF (Open Networking Foundation) scraper.

Covers two datasources:
  onf_blog  — blog posts  (https://opennetworking.org/news-and-events/blog/)
  onf_docs  — technical documents (https://opennetworking.org/technical-documents/)

Both pages use WordPress-style pagination (/page/N/).

Resource categories:
  "blog"               — blog posts (onf_blog)
  "technical_document" — technical specs and white papers (onf_docs)
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
    "onf_blog": {
        "base_url": "https://opennetworking.org",
        "listing_url": "https://opennetworking.org/news-and-events/blog/",
        "category": "blog",
    },
    "onf_docs": {
        "base_url": "https://opennetworking.org",
        "listing_url": "https://opennetworking.org/technical-documents/",
        "category": "technical_document",
    },
}


class ONFScraper(BaseScraper):
    """
    Scraper for ONF blog posts and technical documents.

    Uses standard WordPress <article> element parsing, matching the same
    pattern as the WBA newsroom scraper.
    """

    scraper_name = "onf"

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
                    logger.warning(f"ONF: HTTP {resp.status} for {url}")
                    return None
                html = await resp.text()
                return BeautifulSoup(html, "html.parser")
        except Exception as exc:
            logger.error(f"ONF: error fetching {url}: {exc}")
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
        Extract resources from an ONF listing page.

        Tries <article> elements first (WordPress standard), then falls back
        to generic div card patterns.
        """
        resources: List[Resource] = []

        items = soup.find_all("article")
        if not items:
            items = soup.find_all(
                "div", class_=re.compile(r"post|card|item|resource|document|entry", re.I)
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

                # Date — prefer <time datetime="...">
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

                # Excerpt
                summary = ""
                for cls in ("entry-content", "entry-summary", "post-content", "post-excerpt"):
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
                        category=category,
                        content=summary or None,
                        publish_date=publish_date,
                        datasource_id=datasource_id,
                    )
                )
            except Exception as exc:
                logger.warning(f"ONF: item parse error: {exc}")

        return resources

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run_scraper(self, datasource_config: Dict[str, Any] = None):
        """
        Scrape ONF blog or technical documents in incremental mode.

        Paginates using WordPress /page/N/ URLs until
        consecutive_duplicates_limit known URLs are seen.
        """
        if datasource_config is None:
            datasource_config = self.get_datasource_config("onf_blog")

        datasource_id = datasource_config.get("datasource_id", "onf_blog")
        scraper_delay = float(datasource_config.get("scraper_delay", 1.0))
        max_resources = int(datasource_config.get("max_resources", 200))
        consecutive_duplicates_limit = int(
            datasource_config.get("consecutive_duplicates_limit", 5)
        )
        is_full_refresh = datasource_config.get("is_full_refresh", False)

        if is_full_refresh:
            consecutive_duplicates_limit = 0
            max_resources = -1

        cfg = _DATASOURCE_CFG.get(datasource_id, _DATASOURCE_CFG["onf_blog"])
        base_url = cfg["base_url"]
        listing_url = cfg["listing_url"]
        category = cfg["category"]

        logger.info(f"Starting ONFScraper for {datasource_id} ({listing_url})")
        batch_id = self.start_batch(datasource_id)
        total_published = 0
        consecutive_duplicates = 0
        page = 1

        try:
            while True:
                current_url = listing_url if page == 1 else f"{listing_url.rstrip('/')}/page/{page}/"
                self.update_heartbeat()
                logger.info(f"ONF: fetching page {page}: {current_url}")

                soup = await self._fetch_page(current_url)
                if soup is None:
                    break

                page_resources = self._parse_listing_page(soup, base_url, datasource_id, category)
                if not page_resources:
                    logger.info(f"ONF: no items on page {page} — stopping")
                    break

                candidate_urls = [r.url for r in page_resources]
                existing = self.batch_check_urls_exist(candidate_urls)

                page_new = 0
                stop_early = False
                for res in page_resources:
                    res.batch_id = batch_id
                    self.update_current_processing(res, f"onf page {page}")

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
                                f"ONF: stopping after {consecutive_duplicates} consecutive duplicates"
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
                    logger.info(f"ONF: no new items on page {page} — stopping")
                    break

                page += 1

            logger.info(f"ONFScraper ({datasource_id}) complete — published {total_published}")
            self.end_batch(total_published)

        except Exception as exc:
            logger.error(f"ONFScraper ({datasource_id}) error: {exc}", exc_info=True)
            self.end_batch(total_published)
            raise
