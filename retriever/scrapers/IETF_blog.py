import asyncio
import aiohttp
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, Resource

logger = logging.getLogger(__name__)


class IETFBlogScraper(BaseScraper):
    """
    Scraper for the IETF public blog at https://www.ietf.org/blog/.

    Runs in incremental mode — stops pagination once
    consecutive_duplicates_limit consecutive known URLs are encountered.

    Each blog post is published as a Resource with:
      - category = 'blog'
      - datasource_id = 'ietf_blog'
    """

    BASE_URL = "https://www.ietf.org"
    BLOG_PATH = "/blog/"
    scraper_name = "ietf_blog"

    def __init__(self):
        super().__init__()
        self.base_url = self.BASE_URL

    # ------------------------------------------------------------------
    # Page fetching helpers
    # ------------------------------------------------------------------

    async def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch a page and return its BeautifulSoup, or None on error."""
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    logger.warning(f"HTTP {resp.status} fetching {url}")
                    return None
                html = await resp.text()
                return BeautifulSoup(html, "html.parser")
        except Exception as exc:
            logger.error(f"Error fetching {url}: {exc}")
            return None

    # ------------------------------------------------------------------
    # Blog-post extraction
    # ------------------------------------------------------------------

    def _parse_blog_listing(self, soup: BeautifulSoup, datasource_id: str) -> List[Resource]:
        """Extract blog-post Resource objects from a listing page."""
        resources = []

        # IETF blog uses <article> or <div class="... blog ..."> cards
        cards = soup.find_all("article") or soup.find_all("div", class_=re.compile(r"post|blog|entry", re.I))

        for card in cards:
            try:
                # Title + URL
                link_tag = card.find("a", href=True)
                if not link_tag:
                    continue
                url = urljoin(self.base_url, link_tag["href"])
                title = link_tag.get_text(strip=True) or "Untitled"

                # Skip navigation / sidebar links
                if len(title) < 5 or url == self.base_url + self.BLOG_PATH:
                    continue

                # Date — look for <time> or a date-looking element
                date_str: Optional[str] = None
                time_tag = card.find("time")
                if time_tag:
                    date_str = time_tag.get("datetime") or time_tag.get_text(strip=True)
                if not date_str:
                    # Fallback: look for patterns like "March 2, 2026"
                    text = card.get_text(" ", strip=True)
                    m = re.search(
                        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
                        r"Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b",
                        text,
                        re.I,
                    )
                    if m:
                        date_str = m.group(0)

                # Normalise date to ISO-8601
                publish_date: Optional[str] = None
                if date_str:
                    try:
                        from dateutil.parser import parse as date_parse
                        publish_date = date_parse(date_str).date().isoformat()
                    except Exception:
                        pass

                # Summary — first <p> inside the card
                summary = ""
                p = card.find("p")
                if p:
                    summary = p.get_text(strip=True)[:500]

                resources.append(
                    Resource(
                        title=title,
                        url=url,
                        category="blog",
                        content=summary,
                        publish_date=publish_date,
                        datasource_id=datasource_id,
                    )
                )

            except Exception as exc:
                logger.warning(f"Error parsing blog card: {exc}")

        return resources

    def _next_page_url(self, soup: BeautifulSoup) -> Optional[str]:
        """Return the URL of the next page, or None if on the last page."""
        # Standard "next" pagination link
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            if text in ("next", "next page", "»", "›", "older", "older posts"):
                return urljoin(self.base_url, a["href"])
        # Django/IETF pagination: ?page=N
        current_page_link = soup.find("a", class_=re.compile(r"active|current", re.I), href=True)
        if current_page_link:
            current_href = current_page_link["href"]
            m = re.search(r"[?&]page=(\d+)", current_href)
            if m:
                next_page = int(m.group(1)) + 1
                base = re.sub(r"([?&]page=)\d+", rf"\g<1>{next_page}", current_href)
                return urljoin(self.base_url, base)
        return None

    # ------------------------------------------------------------------
    # Main scraper entry point
    # ------------------------------------------------------------------

    async def run_scraper(self, datasource_config: Dict[str, Any] = None):
        """
        Scrape IETF blog posts in incremental mode.

        Paginates through the blog listing until consecutive_duplicates_limit
        consecutive already-known URLs are seen.
        """
        if datasource_config is None:
            datasource_config = self.get_datasource_config("ietf_blog")

        datasource_id = datasource_config.get("datasource_id", "ietf_blog")
        scraper_delay = float(datasource_config.get("scraper_delay", 1.0))
        max_resources = int(datasource_config.get("max_resources", 100))
        consecutive_duplicates_limit = int(datasource_config.get("consecutive_duplicates_limit", 5))
        is_full_refresh = datasource_config.get("is_full_refresh", False)

        if is_full_refresh:
            consecutive_duplicates_limit = 0
            max_resources = -1

        logger.info(f"Starting IETFBlogScraper for {datasource_id}")

        batch_id = self.start_batch(datasource_id)

        total_published = 0
        consecutive_duplicates = 0
        current_url = f"{self.base_url}{self.BLOG_PATH}"

        try:
            while current_url:
                self.update_heartbeat()
                logger.info(f"Fetching blog listing: {current_url}")

                soup = await self._fetch_page(current_url)
                if soup is None:
                    break

                page_resources = self._parse_blog_listing(soup, datasource_id)
                if not page_resources:
                    logger.info("No posts found on page — stopping.")
                    break

                page_new = 0
                for res in page_resources:
                    res.batch_id = batch_id
                    self.update_current_processing(res.url, f"blog post ({total_published + 1})")

                    is_dup = self.url_exists_in_db(res.url)
                    if is_dup:
                        consecutive_duplicates += 1
                        if (
                            not is_full_refresh
                            and consecutive_duplicates_limit > 0
                            and consecutive_duplicates >= consecutive_duplicates_limit
                        ):
                            logger.info(
                                f"Stopping: {consecutive_duplicates} consecutive duplicates "
                                f"(limit={consecutive_duplicates_limit})"
                            )
                            break
                    else:
                        consecutive_duplicates = 0
                        self.publish_resource(res)
                        total_published += 1
                        page_new += 1

                    if max_resources > 0 and total_published >= max_resources:
                        logger.info(f"Reached max_resources={max_resources}")
                        break

                    await asyncio.sleep(scraper_delay)

                # Early exit on duplicate threshold or resource limit
                if (
                    (consecutive_duplicates_limit > 0 and consecutive_duplicates >= consecutive_duplicates_limit)
                    or (max_resources > 0 and total_published >= max_resources)
                ):
                    break

                if page_new == 0:
                    logger.info("No new posts on this page — stopping pagination.")
                    break

                current_url = self._next_page_url(soup) or None

            logger.info(f"IETFBlogScraper complete — published {total_published} posts")
            self.end_batch(total_published)

        except Exception as exc:
            logger.error(f"IETFBlogScraper error: {exc}", exc_info=True)
            self.end_batch(total_published)
            raise
