"""
NIST CSRC scraper.

Covers two datasources:
  nist_sp800  — NIST Special Publication 800 series  (https://csrc.nist.gov/publications/sp800)
  nist_fips   — FIPS (Federal Information Processing Standards)
                                                       (https://csrc.nist.gov/publications/fips)

NIST is a critical source for security and compliance standards. Final publications
are prioritised; Draft publications are also collected for awareness.

Resource categories:
  "standard"        — status Final / Approved
  "draft_standard"  — status Draft / Preliminary
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
    "nist_sp800": {
        # Both old (/publications/sp800) and new (/pubs/sp) listing URLs — NIST CSRC
        # migrated to /pubs/ format in 2024. We use the canonical listing which still
        # returns all publications, but also recognise /pubs/ in link scanning.
        "listing_url": "https://csrc.nist.gov/publications/sp800",
        "listing_url_alt": "https://csrc.nist.gov/pubs/sp",
        "detail_base": "https://csrc.nist.gov/publications/detail/sp/",
        "detail_base_new": "https://csrc.nist.gov/pubs/sp/",  # new URL format
        "label": "SP 800",
    },
    "nist_fips": {
        "listing_url": "https://csrc.nist.gov/publications/fips",
        "listing_url_alt": "https://csrc.nist.gov/pubs/fips",
        "detail_base": "https://csrc.nist.gov/publications/detail/fips/",
        "detail_base_new": "https://csrc.nist.gov/pubs/fips/",
        "label": "FIPS",
    },
}

_BASE_URL = "https://csrc.nist.gov"


class NISTScraper(BaseScraper):
    """
    Scraper for NIST CSRC SP 800 and FIPS publication listings.

    Parses the HTML listing table at csrc.nist.gov, optionally follows
    individual publication detail pages for abstracts.
    """

    scraper_name = "nist"

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
                if resp.status != 200:
                    logger.warning(f"NIST: HTTP {resp.status} for {url}")
                    return None
                html = await resp.text()
                return BeautifulSoup(html, "html.parser")
        except Exception as exc:
            logger.error(f"NIST: error fetching {url}: {exc}")
            return None

    # ------------------------------------------------------------------
    # Listing page parsers
    # ------------------------------------------------------------------

    def _parse_listing(
        self, soup: BeautifulSoup, datasource_id: str, label: str
    ) -> List[Dict]:
        """
        Parse the CSRC listing page.

        The page renders a table or a list of publication cards.  We try both.
        Returns a list of dicts with: title, url, status, publish_date.
        """
        candidates = []
        seen: set = set()

        # --- Try <table> structure first ------------------------------------
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows[1:]:  # skip header
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                try:
                    # Find the link — usually in the first or second cell
                    link = row.find("a", href=True)
                    if not link:
                        continue
                    href = link["href"]
                    if not href.startswith("http"):
                        href = urljoin(_BASE_URL, href)
                    if href in seen:
                        continue
                    seen.add(href)

                    title = link.get_text(strip=True)
                    if not title:
                        title = " ".join(c.get_text(strip=True) for c in cells[:3])[:200]
                    if not title:
                        continue

                    # Status from row text
                    row_text = row.get_text(" ", strip=True).lower()
                    if any(w in row_text for w in ("withdrawn", "superseded")):
                        status = "withdrawn"
                    elif any(w in row_text for w in ("draft", "preliminary", "ipd")):
                        status = "draft"
                    else:
                        status = "final"

                    # Date — look for ISO date or month-year pattern in cells
                    publish_date = self._extract_date(cells)

                    candidates.append(
                        {
                            "title": title,
                            "url": href,
                            "status": status,
                            "publish_date": publish_date,
                        }
                    )
                except Exception as exc:
                    logger.debug(f"NIST: row parse error: {exc}")

        # --- Fallback: div/article cards -----------------------------------
        if not candidates:
            items = soup.find_all(
                ["article", "div"],
                class_=re.compile(r"publication|result|item|pub-item", re.I),
            )
            for item in items:
                try:
                    link = item.find("a", href=True)
                    if not link:
                        continue
                    href = link["href"]
                    if not href.startswith("http"):
                        href = urljoin(_BASE_URL, href)
                    if href in seen:
                        continue
                    seen.add(href)

                    title = link.get_text(strip=True)
                    if not title or len(title) < 4:
                        continue

                    item_text = item.get_text(" ", strip=True).lower()
                    if any(w in item_text for w in ("withdrawn", "superseded")):
                        status = "withdrawn"
                    elif any(w in item_text for w in ("draft", "preliminary", "ipd")):
                        status = "draft"
                    else:
                        status = "final"

                    time_el = item.find("time")
                    publish_date = None
                    if time_el:
                        raw = time_el.get("datetime") or time_el.get_text(strip=True)
                        try:
                            publish_date = date_parse(raw).date().isoformat()
                        except Exception:
                            pass

                    candidates.append(
                        {
                            "title": title,
                            "url": href,
                            "status": status,
                            "publish_date": publish_date,
                        }
                    )
                except Exception as exc:
                    logger.debug(f"NIST: card parse error: {exc}")

        # --- Last resort: scan all publication-looking links ---------------
        if not candidates:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                # CSRC detail URLs: old format /publications/detail/sp/800/207/final
                # New format (2024+): /pubs/sp/800/238/final
                if not re.search(r"/publications/detail/|/pubs/(sp|fips)/", href):
                    continue
                if not href.startswith("http"):
                    href = urljoin(_BASE_URL, href)
                if href in seen:
                    continue
                seen.add(href)
                title = a.get_text(strip=True)
                if not title or len(title) < 4:
                    continue
                status = "draft" if "draft" in href.lower() else "final"
                candidates.append(
                    {"title": title, "url": href, "status": status, "publish_date": None}
                )

        return candidates

    def _extract_date(self, cells) -> Optional[str]:
        """Extract a date string from table cells."""
        for cell in cells:
            text = cell.get_text(strip=True)
            if re.match(r"\d{4}-\d{2}-\d{2}", text):
                return text[:10]
            m = re.search(
                r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)[,\s]+\d{1,2},?\s+\d{4}\b",
                text, re.I,
            )
            if m:
                try:
                    return date_parse(m.group(0)).date().isoformat()
                except Exception:
                    pass
            # "MM/YYYY" or "YYYY" patterns common on CSRC
            m2 = re.search(r"\b(\d{1,2}/\d{4})\b", text)
            if m2:
                try:
                    return date_parse(m2.group(1)).date().isoformat()
                except Exception:
                    pass
        return None

    async def _fetch_detail(self, url: str) -> dict:
        """Fetch the publication detail page and return abstract + publication date.

        Handles both old CSRC URL format (/publications/detail/sp/800/N/final)
        and new format (/pubs/sp/800/N/final) introduced by NIST CSRC in 2024.

        Returns:
            dict with 'abstract' (str|None) and 'publish_date' (str|None)
        """
        soup = await self._fetch_page(url)
        # If old-format URL fails, try the equivalent /pubs/ URL
        if soup is None and "/publications/detail/" in url:
            alt_url = url.replace(
                "/publications/detail/sp/", "/pubs/sp/"
            ).replace(
                "/publications/detail/fips/", "/pubs/fips/"
            )
            logger.debug(f"NIST: retrying detail with alt URL {alt_url}")
            soup = await self._fetch_page(alt_url)
        if soup is None:
            return {"abstract": None, "publish_date": None}

        abstract = None
        publish_date = None

        try:
            # --- Abstract -------------------------------------------------------
            abstract_el = soup.find(id=re.compile(r"abstract", re.I)) or \
                soup.find(class_=re.compile(r"abstract", re.I))
            if abstract_el:
                abstract = abstract_el.get_text(" ", strip=True)[:1000]
            if not abstract:
                for cls in ("pub-abstract", "publication-abstract", "summary"):
                    el = soup.find(class_=re.compile(cls, re.I))
                    if el:
                        abstract = el.get_text(" ", strip=True)[:1000]
                        break
            if not abstract:
                for p in soup.find_all("p"):
                    text = p.get_text(strip=True)
                    if len(text) > 100:
                        abstract = text[:1000]
                        break

            # --- Publication date -----------------------------------------------
            # CSRC detail pages show "Published: Month DD, YYYY" or "Date Published: ..."
            page_text = soup.get_text(" ", strip=True)
            for pat in [
                r"(?:date\s+published|published)[:\s]+([A-Za-z]+\.?\s+\d{1,2},?\s+\d{4})",
                r"(?:date\s+published|published)[:\s]+(\d{4}-\d{2}-\d{2})",
                r"(?:date\s+published|published)[:\s]+(\d{1,2}/\d{4})",
            ]:
                m = re.search(pat, page_text, re.I)
                if m:
                    try:
                        publish_date = date_parse(m.group(1)).date().isoformat()
                        break
                    except Exception:
                        pass

            # Look inside <time> tags (newer CSRC pages)
            if not publish_date:
                for time_el in soup.find_all("time"):
                    raw = time_el.get("datetime") or time_el.get_text(strip=True)
                    try:
                        publish_date = date_parse(raw).date().isoformat()
                        break
                    except Exception:
                        pass

        except Exception as exc:
            logger.debug(f"NIST: detail parse error for {url}: {exc}")

        return {"abstract": abstract, "publish_date": publish_date}

    async def _fetch_abstract(self, url: str) -> Optional[str]:
        """Fetch the publication detail page and return the abstract text.

        Handles both old CSRC URL format (/publications/detail/sp/800/N/final)
        and new format (/pubs/sp/800/N/final) introduced by NIST CSRC in 2024.
        """
        soup = await self._fetch_page(url)
        # If old-format URL fails, try the equivalent /pubs/ URL
        if soup is None and "/publications/detail/" in url:
            alt_url = url.replace(
                "/publications/detail/sp/", "/pubs/sp/"
            ).replace(
                "/publications/detail/fips/", "/pubs/fips/"
            )
            logger.debug(f"NIST: retrying abstract with alt URL {alt_url}")
            soup = await self._fetch_page(alt_url)
        if soup is None:
            return None
        try:
            # CSRC abstract is usually in a div with id/class containing "abstract"
            abstract_el = soup.find(id=re.compile(r"abstract", re.I)) or \
                soup.find(class_=re.compile(r"abstract", re.I))
            if abstract_el:
                return abstract_el.get_text(" ", strip=True)[:1000]
            # New /pubs/ pages use a "pub-abstract" class or similar
            for cls in ("pub-abstract", "publication-abstract", "summary"):
                el = soup.find(class_=re.compile(cls, re.I))
                if el:
                    return el.get_text(" ", strip=True)[:1000]
            # Fallback: first substantial <p>
            for p in soup.find_all("p"):
                text = p.get_text(strip=True)
                if len(text) > 100:
                    return text[:1000]
        except Exception as exc:
            logger.debug(f"NIST: abstract parse error for {url}: {exc}")
        return None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run_scraper(self, datasource_config: Dict[str, Any] = None):
        """
        Scrape NIST SP 800 or FIPS publication listings.

        Fetches the listing page, then optionally follows each publication's
        detail page to collect abstracts.  Stops early when
        consecutive_duplicates_limit known URLs are seen.
        """
        if datasource_config is None:
            datasource_config = self.get_datasource_config("nist_sp800")

        datasource_id = datasource_config.get("datasource_id", "nist_sp800")
        scraper_delay = float(datasource_config.get("scraper_delay", 1.0))
        max_resources = int(datasource_config.get("max_resources", 200))
        # Increased default from 5 → 20: NIST listings are sorted by SP number
        # so new publications can appear after several already-known ones. With limit=5
        # the scraper stopped before reaching newly published documents like SP 800-238.
        consecutive_duplicates_limit = int(
            datasource_config.get("consecutive_duplicates_limit", 20)
        )
        is_full_refresh = datasource_config.get("is_full_refresh", False)

        if is_full_refresh:
            consecutive_duplicates_limit = 0
            max_resources = -1

        cfg = _DATASOURCE_CFG.get(datasource_id, _DATASOURCE_CFG["nist_sp800"])
        listing_url = cfg["listing_url"]
        listing_url_alt = cfg.get("listing_url_alt")
        label = cfg["label"]

        logger.info(f"Starting NISTScraper for {datasource_id} ({listing_url})")
        batch_id = self.start_batch(datasource_id)
        total_published = 0
        consecutive_duplicates = 0

        try:
            self.update_heartbeat()
            soup = await self._fetch_page(listing_url)

            # If primary listing fails or returns no candidates, try the alternative
            # /pubs/ URL that NIST CSRC introduced in 2024
            candidates_primary = self._parse_listing(soup, datasource_id, label) if soup else []
            if not candidates_primary and listing_url_alt:
                logger.info(f"NIST: primary listing empty, trying alt URL {listing_url_alt}")
                soup = await self._fetch_page(listing_url_alt)

            if soup is None:
                logger.warning(f"NIST: could not fetch listing page {listing_url}")
                self.end_batch(total_published)
                return

            candidates = self._parse_listing(soup, datasource_id, label)
            if not candidates:
                logger.warning(f"NIST: no publications found on {listing_url}")
                self.end_batch(total_published)
                return

            logger.info(f"NIST: found {len(candidates)} candidate publications for {datasource_id}")

            # Batch dedup
            candidate_urls = [c["url"] for c in candidates]
            existing = self.batch_check_urls_exist(candidate_urls)

            for c in candidates:
                url = c["url"]
                status = c["status"]
                publish_date = c["publish_date"]

                # Skip withdrawn publications
                if status == "withdrawn":
                    continue

                category = "standard" if status == "final" else "draft_standard"

                self.update_heartbeat()
                self.update_current_processing(
                    Resource(title=c["title"], url=url, category=category),
                    f"nist {label}",
                )

                if self._should_skip_by_lookback(
                    "resource", datasource_id, publish_date,
                    c["title"], url, allow_initial_backfill=True
                ):
                    continue

                if existing.get(url, False):
                    consecutive_duplicates += 1
                    if (
                        not is_full_refresh
                        and consecutive_duplicates_limit > 0
                        and consecutive_duplicates >= consecutive_duplicates_limit
                    ):
                        logger.info(
                            f"NIST: stopping after {consecutive_duplicates} consecutive duplicates"
                        )
                        break
                    continue

                consecutive_duplicates = 0

                # Fetch detail page for Final publications (abstract + exact date)
                content: Optional[str] = None
                if status == "final":
                    await asyncio.sleep(scraper_delay)
                    detail = await self._fetch_detail(url)
                    content = detail.get("abstract")
                    # Use the date from the detail page if the listing didn't have one
                    if not publish_date and detail.get("publish_date"):
                        publish_date = detail["publish_date"]
                        logger.debug(
                            f"NIST: extracted publish_date {publish_date} from detail page for {c['title'][:50]}"
                        )

                res = Resource(
                    title=c["title"],
                    url=url,
                    category=category,
                    content=content,
                    publish_date=publish_date,
                    datasource_id=datasource_id,
                    batch_id=batch_id,
                )
                self.publish_resource(res)
                total_published += 1

                if max_resources > 0 and total_published >= max_resources:
                    logger.info(f"NIST: reached max_resources={max_resources}")
                    break

                await asyncio.sleep(scraper_delay)

            logger.info(f"NISTScraper ({datasource_id}) complete — published {total_published}")
            self.mark_datasource_scraped(datasource_id)
            self.end_batch(total_published)

        except Exception as exc:
            logger.error(f"NISTScraper ({datasource_id}) error: {exc}", exc_info=True)
            self.end_batch(total_published)
            raise
