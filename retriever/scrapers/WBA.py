import asyncio
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, urlparse
from typing import List, Optional, Dict, Any
import logging
from datetime import datetime

from .base import BaseScraper, Resource, Event
from settings import settings

logger = logging.getLogger(__name__)


class WBAScraper(BaseScraper):
    """
    Scraper for the Wireless Broadband Alliance (WBA) resources page.
    
    Configuration:
    The datasource config in database (system_configuration table) provides:
    - resource_url: URL path to scrape (e.g., '/resources/')
    - scrape_frequency, max_resources, scraper_delay, etc.
    
    Note: The resources listing is public, but document downloads require authentication.
    """
    
    DOCUMENT_EXTENSIONS = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']
    scraper_name = "wba"  # Used for JSON file naming
    
    # Base URLs
    BASE_URL = "https://wballiance.com"
    AUTH_URL = "https://wballiance.com/wp-login.php?wpe-login=true"  # WP Engine login
    RESOURCES_BASE = "https://wballiance.com/resources/"
    HOSTED_EVENTS_URL = "https://wballiance.com/wba-hosted-events/"
    EXTERNAL_EVENTS_URL = "https://wballiance.com/external-events/"
    
    # Year range for scraping
    START_YEAR = 2009
    
    # Browser headers to bypass Cloudflare bot detection
    # These mimic a real Chrome browser on macOS
    BROWSER_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Upgrade-Insecure-Requests': '1',
    }
    
    def __init__(self):
        super().__init__()
        self.base_url = self.BASE_URL
        self.resources_url = self.RESOURCES_BASE
        # Authentication credentials (to be configured from datasource config)
        self.username = None
        self.password = None
        self.is_authenticated = False

    def is_document_url(self, url: str) -> bool:
        """Check if URL points to a document file"""
        return any(ext in url.lower() for ext in self.DOCUMENT_EXTENSIONS)
    
    def is_youtube_url(self, url: str) -> bool:
        """Check if URL points to a YouTube video"""
        parsed = urlparse(url)
        host = parsed.hostname.lower() if parsed.hostname else ""
        # Accept main YouTube domains and common subdomains
        if host == "youtube.com" or host.endswith(".youtube.com"):
            return True
        if host == "youtu.be" or host.endswith(".youtu.be"):
            return True
        return False
    
    def is_zip_url(self, url: str) -> bool:
        """Check if URL points to a ZIP archive"""
        return '.zip' in url.lower()
    
    def get_headers(self, referer: str = None) -> Dict[str, str]:
        """
        Get browser headers with optional custom referer.
        
        Args:
            referer: Optional referer URL to include in headers
            
        Returns:
            Dictionary of HTTP headers
        """
        headers = self.BROWSER_HEADERS.copy()
        if referer:
            headers['Referer'] = referer
        return headers

    async def authenticate(self, username: str = None, password: str = None) -> bool:
        """
        Authenticate with WBA WordPress login.
        
        WordPress authentication flow:
        1. POST credentials to wp-login.php
        2. WordPress sets cookies (wordpress_logged_in_*, wordpress_sec_*)
        3. Session automatically stores and sends cookies on subsequent requests
        
        Args:
            username: WBA account username
            password: WBA account password
            
        Returns:
            True if authentication succeeded, False otherwise
        """
        if not username or not password:
            logger.warning("No authentication credentials provided - document downloads may fail")
            self.is_authenticated = False
            return False
        
        self.username = username
        self.password = password
        
        logger.info(f"Authenticating with WBA WordPress")
        logger.info(f"  Username: {username}")
        logger.info(f"  Auth URL: {self.AUTH_URL}")
        
        try:
            # WP Engine WordPress login form data
            # Must match the exact payload order and format from the browser
            login_data = {
                'wpe-login': 'true',      # WP Engine specific field
                'log': username,          # WordPress username field
                'pwd': password,          # WordPress password field
                'wp-submit': 'Log In',
                'redirect_to': 'https://wballiance.com/wp-admin/',  # Redirect to admin after login
                'testcookie': '1'
            }
            
            # Get headers with login-specific additions
            headers = self.get_headers(referer=self.AUTH_URL)
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
            headers['Origin'] = self.BASE_URL
            headers['Sec-Fetch-User'] = '?1'
            
            # Log only non-sensitive information about the login payload
            logger.debug("  Login data includes username, password, and form control fields")
            logger.debug(f"  Using browser-like headers to bypass Cloudflare")
            
            # POST to WordPress login
            logger.debug(f"  Posting credentials to {self.AUTH_URL}...")
            async with self.session.post(
                self.AUTH_URL,
                data=login_data,
                headers=headers,
                allow_redirects=True
            ) as response:
                
                logger.info(f"  Auth response: HTTP {response.status}")
                logger.debug(f"  Final URL after redirects: {response.url}")
                
                # Log response headers
                logger.debug(f"  Response headers: {dict(response.headers)}")
                
                # Check if authentication succeeded
                # WordPress typically redirects on success and sets cookies
                if response.status == 200:
                    # Check if we have WordPress auth cookies
                    cookies = self.session.cookie_jar.filter_cookies(self.BASE_URL)
                    cookie_names = [cookie.key for cookie in cookies.values()]
                    logger.debug(f"  Cookies received: {cookie_names}")
                    
                    has_auth_cookie = any(
                        'wordpress_logged_in' in cookie.key 
                        for cookie in cookies.values()
                    )
                    
                    if has_auth_cookie:
                        self.is_authenticated = True
                        logger.info("✓ Successfully authenticated with WBA WordPress")
                        return True
                    else:
                        # Check response for login error indicators
                        html = await response.text()
                        logger.debug(f"  Response body length: {len(html)} chars")
                        
                        # Log snippets of response for debugging
                        if 'login_error' in html:
                            logger.debug("  Found 'login_error' in response HTML")
                        if 'incorrect' in html.lower():
                            logger.debug("  Found 'incorrect' in response HTML")
                        
                        if 'login_error' in html or 'incorrect' in html.lower():
                            logger.error("✗ Authentication failed: Invalid credentials")
                            self.is_authenticated = False
                            return False
                        else:
                            logger.warning("⚠ Authentication uncertain: No auth cookie found, but no error detected")
                            logger.warning("  This may indicate Cloudflare protection or unusual WordPress configuration")
                            # Some sites don't set cookies immediately, try anyway
                            self.is_authenticated = True
                            return True
                else:
                    logger.error(f"✗ Authentication failed: HTTP {response.status}")
                    
                    # Try to get response body for more context
                    try:
                        response_text = await response.text()
                        logger.debug(f"  Response body (first 500 chars): {response_text[:500]}")
                    except:
                        logger.debug("  Could not read response body")
                    
                    self.is_authenticated = False
                    return False
                    
        except Exception as e:
            logger.error(f"✗ Error during authentication: {e}")
            logger.exception("  Full exception trace:")
            self.is_authenticated = False
            return False

    def _extract_resources_from_soup(
        self, 
        soup: BeautifulSoup, 
        year: int = None,
        datasource_id: str = None
    ) -> List[Resource]:
        """
        Extract resources from card/listing elements on the page.
        
        Each resource is in a div.wal-resource-item containing:
        - div.wal-item-content: h2 (title/link), p (description)
        - div.wal-item-dl-bar: button (download link), spans (date, category)
        
        Args:
            soup: BeautifulSoup object of the page
            year: Year being scraped (for categorization)
            datasource_id: Datasource ID to assign to resources
            
        Returns:
            List of Resource objects
        """
        resources = []
        
        # Find all resource items on the page
        resource_elements = soup.find_all('div', class_='wal-resource-item')
        
        logger.debug(f"Found {len(resource_elements)} resource elements on page")
        
        for element in resource_elements:
            try:
                # Extract content section
                content_div = element.find('div', class_='wal-item-content')
                if not content_div:
                    logger.debug("Skipping element: no wal-item-content found")
                    continue
                
                # Extract title and URL from h2 > a
                title_element = content_div.find('h2')
                if not title_element:
                    logger.debug("Skipping element: no h2 title found")
                    continue
                
                link = title_element.find('a', href=True)
                if not link:
                    logger.debug("Skipping element: no link in title")
                    continue
                
                title = link.get_text(strip=True)
                page_url = urljoin(self.base_url, link['href'])
                
                # Extract description from p tag
                description = None
                description_element = content_div.find('p')
                if description_element:
                    description = description_element.get_text(strip=True)
                
                # Extract download bar info
                dl_bar = element.find('div', class_='wal-item-dl-bar')
                
                # Extract download link from button onclick
                download_url = None
                if dl_bar:
                    download_button = dl_bar.find('button', class_='wal-download-link-resource')
                    if download_button and download_button.get('onclick'):
                        onclick = download_button.get('onclick')
                        # Extract URL from: openInNewTab('https://...')
                        match = re.search(r"openInNewTab\(['\"]([^'\"]+)['\"]\)", onclick)
                        if match:
                            download_url = match.group(1)
                            logger.debug(f"Found download URL: {download_url}")
                        else:
                            logger.debug(f"Could not parse onclick: {onclick}")
                
                # Extract date and category from spans
                publish_date = None
                category = "uncategorized"  # Default if not found
                
                if dl_bar:
                    spans = dl_bar.find_all('span', style=re.compile(r'white-space:\s*nowrap', re.I))
                    if len(spans) >= 2:
                        # First span is date (format: MM - DD - YY)
                        date_text = spans[0].get_text(strip=True)
                        try:
                            from dateutil.parser import parse as date_parse
                            # Handle format like "10 - 12 - 25"
                            parsed_date = date_parse(date_text)
                            publish_date = parsed_date.strftime('%Y-%m-%d')
                        except Exception as e:
                            logger.warning(f"Failed to parse date '{date_text}': {e}")
                        
                        # Second span contains category (may have link inside)
                        category_element = spans[1].find('a') or spans[1]
                        if category_element:
                            category_text = category_element.get_text(strip=True).lower()
                            if category_text:  # Only use if not empty
                                category = category_text
                
                # If no date found and we have a year, use the year
                if not publish_date and year:
                    publish_date = f"{year}-01-01"
                
                # Determine which URL to use as the primary URL
                # If there's a download URL (PDF/doc), use that, otherwise use the page URL
                if download_url:
                    primary_url = download_url
                else:
                    primary_url = page_url
                
                logger.debug(f"Extracted resource: title='{title}', url='{primary_url}', category='{category}'")
                
                # Create resource with download URL as primary if available
                resource = Resource(
                    title=title,
                    url=primary_url,
                    category=category,
                    publish_date=publish_date,
                    datasource_id=datasource_id or 'wba_resources'
                )
                
                # Store description in content if we have it and it's not a direct download
                # For direct downloads (PDFs), we'll extract content later
                if description and not self.is_document_url(primary_url):
                    resource.content = description
                
                resources.append(resource)
                
            except Exception as e:
                logger.error(f"Error extracting resource from element: {e}")
                logger.exception("Full traceback:")
                continue
        
        logger.debug(f"Extracted {len(resources)} resources from page")
        return resources

    async def get_newsroom_articles(
        self,
        datasource_id: str,
        max_articles: int = -1,
        consecutive_duplicates_limit: int = 5,
    ) -> List[Resource]:
        """
        Discover and collect articles from the WBA newsroom.

        The newsroom (wballiance.com/newsroom/) is a WordPress blog listing that
        is completely separate from the /resources/ section.  Articles include
        press releases, partner spotlights, trial reports, and product launches
        (e.g. Nicnet CX Suite, Wi-Fi HaLow readiness trials).

        Pagination: /newsroom/page/N/
        Each <article> element contains:
          - <h2>/<h3> with <a href="..."> — title and permalink
          - <time datetime="ISO8601"> — publication date (authoritative)
          - Optional excerpt div — short description

        Args:
            datasource_id: The datasource identifier to assign to resources.
            max_articles:  Maximum new articles to return (-1 = unlimited).
            consecutive_duplicates_limit: Stop pagination after this many
                already-known articles in a row (0 = no limit).

        Returns:
            List of Resource objects (new/unseen articles only).
        """
        import asyncio as _asyncio
        NEWSROOM_BASE = f"{self.BASE_URL}/newsroom/"
        resources: List[Resource] = []
        page = 1
        consecutive_dupes = 0
        seen_urls: set = set()

        logger.info(f"Discovering WBA newsroom articles from {NEWSROOM_BASE}")

        while True:
            if max_articles >= 0 and len(resources) >= max_articles:
                break

            page_url = NEWSROOM_BASE if page == 1 else f"{NEWSROOM_BASE}page/{page}/"

            try:
                self.update_heartbeat()
                self.update_current_processing(
                    Resource(title=f"Newsroom page {page}", url=page_url, category="discovery"),
                    f"scanning newsroom page {page}",
                )

                async with self.session.get(
                    page_url,
                    headers=self.get_headers(referer=NEWSROOM_BASE),
                ) as response:
                    if response.status == 404:
                        logger.debug(f"Newsroom page {page} returned 404 — stopping")
                        break
                    if response.status != 200:
                        logger.warning(f"Newsroom page {page} returned HTTP {response.status}")
                        break
                    html = await response.text()

            except Exception as exc:
                logger.error(f"Error fetching newsroom page {page}: {exc}")
                break

            soup = BeautifulSoup(html, "html.parser")
            articles = soup.find_all("article")

            if not articles:
                logger.debug(f"No <article> elements on newsroom page {page} — stopping")
                break

            # Parse all candidate articles on this page
            candidates: List[Dict[str, Any]] = []
            for article in articles:
                try:
                    heading = article.find(["h2", "h3"])
                    if not heading:
                        continue
                    link_el = heading.find("a", href=True)
                    if not link_el:
                        continue

                    url = link_el["href"]
                    if not url.startswith("http"):
                        url = urljoin(self.BASE_URL, url)

                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    title = link_el.get_text(strip=True)
                    if not title:
                        continue

                    # Publication date — prefer <time datetime="...">
                    publish_date: Optional[str] = None
                    time_el = article.find("time")
                    if time_el:
                        raw_dt = time_el.get("datetime") or time_el.get_text(strip=True)
                        if raw_dt:
                            try:
                                from dateutil.parser import parse as dp
                                parsed = dp(raw_dt)
                                publish_date = parsed.strftime("%Y-%m-%d")
                            except Exception:
                                pass

                    # Short excerpt
                    description: Optional[str] = None
                    for cls in ("post-content", "entry-content", "entry-summary", "fusion-post-content"):
                        div = article.find("div", class_=cls)
                        if div:
                            description = div.get_text(" ", strip=True)[:500]
                            break

                    candidates.append({"url": url, "title": title,
                                       "publish_date": publish_date, "description": description})
                except Exception as exc:
                    logger.error(f"Error parsing newsroom article element: {exc}")

            if not candidates:
                break

            # Batch-check which URLs are already in the database
            candidate_urls = [c["url"] for c in candidates]
            existing = self.batch_check_urls_exist(candidate_urls)

            page_new = 0
            for c in candidates:
                if existing.get(c["url"], False):
                    consecutive_dupes += 1
                    if consecutive_duplicates_limit > 0 and consecutive_dupes >= consecutive_duplicates_limit:
                        logger.debug(
                            f"Reached {consecutive_dupes} consecutive known articles — stopping newsroom scan"
                        )
                        return resources
                    continue

                consecutive_dupes = 0
                resource = Resource(
                    title=c["title"],
                    url=c["url"],
                    category="newsroom",
                    publish_date=c["publish_date"],
                    datasource_id=datasource_id,
                )
                if c["description"]:
                    resource.content = c["description"]

                resources.append(resource)
                page_new += 1

                if max_articles >= 0 and len(resources) >= max_articles:
                    return resources

            logger.debug(f"Newsroom page {page}: {page_new} new articles found")
            page += 1
            await _asyncio.sleep(0.5)

        logger.info(f"Newsroom discovery complete: {len(resources)} new articles found")
        return resources

    async def get_resources_for_year(
        self, 
        year: int,
        datasource_id: str, 
        max_resources: int = -1,
        discovery_mode: str = "incremental",
        consecutive_duplicates_limit: int = 5,
        initial_consecutive_count: int = 0,
        is_full_refresh: bool = False,
        check_content_hash: bool = True
    ) -> tuple[List[Resource], int]:
        """
        Extract resource links for a specific year with pagination.
        
        Handles pagination within a year (e.g., /resources/2020/page/2/).
        In incremental mode, stops after finding consecutive duplicates.
        In full refresh mode with content checking, re-scrapes existing resources
        to detect content changes.
        
        Args:
            year: Year to scrape (e.g., 2020)
            datasource_id: The datasource identifier for config lookups
            max_resources: Maximum number of new items to collect for this year (-1 = unlimited)
            discovery_mode: 'incremental' (stop after consecutive dups) or 'full'
            consecutive_duplicates_limit: Stop after this many consecutive duplicates (default 5)
            initial_consecutive_count: Starting count of consecutive duplicates from previous years
            is_full_refresh: Whether this is a full refresh run (re-checks content hashes)
            check_content_hash: Whether to check content hashes for changed resources
            
        Returns:
            Tuple of (List of Resource objects, final consecutive duplicate count)
        """
        new_items = []
        page = 1
        duplicates_skipped = 0
        consecutive_duplicates = initial_consecutive_count
        
        while True:
            # Build year-specific URL with pagination
            # /resources/2020/page/1/, /resources/2020/page/2/, etc.
            page_url = f"{self.RESOURCES_BASE}{year}/page/{page}/"
            
            logger.debug(f"Fetching resources for year {year}, page {page}: {page_url}")
            
            self.update_heartbeat()
            self.update_current_processing(
                Resource(title=f"Fetching {year} resources", url=page_url, category="discovery"),
                f"loading year {year}, page {page}"
            )
            
            try:
                async with self.session.get(page_url, headers=self.get_headers(referer=self.resources_url)) as response:
                    if response.status == 404:
                        logger.debug(f"Year {year} page {page} not found (404), stopping pagination for this year")
                        break
                    elif response.status != 200:
                        logger.warning(f"Failed to fetch {page_url}: HTTP {response.status}")
                        break
                    
                    html = await response.text()
            except Exception as e:
                logger.error(f"Error fetching {page_url}: {e}")
                break
            
            soup = BeautifulSoup(html, 'html.parser')
            page_items = self._extract_resources_from_soup(soup, year=year, datasource_id=datasource_id)
            
            if not page_items:
                logger.debug(f"No resources on {year} page {page}, stopping pagination for this year")
                break
            
            # Batch check which URLs already exist in the database
            urls_to_check = [item.url for item in page_items]
            existing_urls = self.batch_check_urls_exist(urls_to_check)
            
            for item in page_items:
                if max_resources >= 0 and len(new_items) >= max_resources:
                    break
                
                try:
                    self.update_heartbeat()
                    
                    # Check if URL already exists in database
                    url_exists = existing_urls.get(item.url, False)
                    
                    if url_exists:
                        # In full refresh mode with content checking, re-scrape to check for changes
                        if is_full_refresh and check_content_hash:
                            logger.debug(f"Full refresh: Re-scraping existing resource to check content: {item.url}")
                            
                            # Scrape the resource to get its current content
                            scraped_item = await self.scrape_resource(item)
                            
                            # Check if content has changed
                            if scraped_item.content and self.has_content_changed(item.url, scraped_item.content):
                                logger.info(f"Content changed for {item.url}, will republish")
                                new_items.append(scraped_item)
                                consecutive_duplicates = 0  # Reset on content change
                            else:
                                logger.debug(f"Content unchanged for {item.url}, skipping")
                                duplicates_skipped += 1
                                consecutive_duplicates += 1
                        else:
                            # Incremental mode: skip duplicate resources
                            duplicates_skipped += 1
                            consecutive_duplicates += 1
                        
                        # In incremental mode, stop after hitting consecutive duplicate limit
                        if (discovery_mode == "incremental" and 
                            consecutive_duplicates_limit > 0 and 
                            consecutive_duplicates >= consecutive_duplicates_limit):
                            logger.info(
                                f"Stopping scrape after {consecutive_duplicates} consecutive duplicates "
                                f"(year {year}, found {len(new_items)} new resources total)"
                            )
                            return new_items, consecutive_duplicates
                        
                        if not (is_full_refresh and check_content_hash):
                            # Skip to next item if not doing content check
                            continue
                    else:
                        # New URL - always include
                        consecutive_duplicates = 0
                        new_items.append(item)
                    
                except Exception as e:
                    logger.error(f"Error processing item {item.url}: {e}")
                    continue
            
            if max_resources >= 0 and len(new_items) >= max_resources:
                break
            
            await asyncio.sleep(self.get_scraper_delay(datasource_id))
            page += 1
        
        logger.info(
            f"Year {year}: Found {len(new_items)} new resources "
            f"({duplicates_skipped} duplicates skipped, {consecutive_duplicates} consecutive at end)"
        )
        return new_items, consecutive_duplicates

    async def get_resources(
        self, 
        datasource_id: str, 
        max_resources: int = -1,
        discovery_mode: str = "incremental",
        consecutive_duplicates_limit: int = 5,
        is_full_refresh: bool = False,
        check_content_hash: bool = True
    ) -> List[Resource]:
        """
        Discover and collect resources across all years (2009 to current year).
        
        Iterates through years in reverse order (newest first) to prioritize
        recent content. In incremental mode, stops after finding consecutive duplicates
        across all years (not per-year).
        
        In full refresh mode with content checking, re-scrapes existing resources
        to detect content changes and only republishes if content has changed.
        
        Args:
            datasource_id: The datasource identifier for config lookups
            max_resources: Maximum number of new items to collect total (-1 = unlimited)
            discovery_mode: 'incremental' (stop after consecutive dups) or 'full'
            consecutive_duplicates_limit: Stop after this many consecutive duplicates across all years
            is_full_refresh: Whether this is a full refresh run (re-checks content hashes)
            check_content_hash: Whether to check content hashes for changed resources
            
        Returns:
            List of Resource objects
        """
        all_resources = []
        current_year = datetime.now().year
        consecutive_count = 0  # Track consecutive duplicates across all years
        
        # Scrape years in reverse order (newest first)
        years_to_scrape = list(range(current_year, self.START_YEAR - 1, -1))
        
        logger.info(f"Scraping WBA resources from {self.START_YEAR} to {current_year} (mode: {discovery_mode})")
        
        for year in years_to_scrape:
            if max_resources >= 0 and len(all_resources) >= max_resources:
                logger.info(f"Reached max_resources limit ({max_resources}), stopping")
                break
            
            # Calculate remaining resource budget for this year
            remaining = max_resources - len(all_resources) if max_resources >= 0 else -1
            
            year_resources, consecutive_count = await self.get_resources_for_year(
                year=year,
                datasource_id=datasource_id,
                max_resources=remaining,
                discovery_mode=discovery_mode,
                consecutive_duplicates_limit=consecutive_duplicates_limit,
                initial_consecutive_count=consecutive_count,
                is_full_refresh=is_full_refresh,
                check_content_hash=check_content_hash
            )
            
            all_resources.extend(year_resources)
            
            # In incremental mode, if we hit the consecutive limit, stop entirely
            if (discovery_mode == "incremental" and 
                consecutive_duplicates_limit > 0 and 
                consecutive_count >= consecutive_duplicates_limit):
                logger.info(f"Stopping all scraping after {consecutive_count} consecutive duplicates")
                break
            
            # Small delay between years
            await asyncio.sleep(self.get_scraper_delay(datasource_id))
        
        logger.info(f"Total resources discovered: {len(all_resources)}")
        return all_resources

    async def _scrape_wba_events(
        self,
        event_links: List,
        datasource_id: str,
        today
    ) -> List[Event]:
        """
        Extract event details from WBA event links (wballiance.com).
        
        These events are hosted on the WBA website and require navigating to the event
        detail page to extract full information.
        
        Event inclusion logic:
        - Future events: Always included (to capture updates)
        - Past events: Only included if not already in database
        
        Args:
            event_links: List of BeautifulSoup link elements with wballiance.com URLs
            datasource_id: Datasource identifier
            today: Current date for future/past comparison
            
        Returns:
            List of Event objects
        """
        events = []
        
        # Build list of event URLs for batch checking
        event_urls = [link['href'] for link in event_links]
        existing_urls = self.batch_check_urls_exist(event_urls)
        
        for link in event_links:
            event_url = link['href']
            
            logger.debug(f"Fetching WBA-hosted event page: {event_url}")
            
            try:
                # Fetch the event detail page
                async with self.session.get(
                    event_url,
                    headers=self.get_headers(referer=self.HOSTED_EVENTS_URL)
                ) as response:
                    if response.status != 200:
                        logger.error(f"Failed to fetch WBA event page: HTTP {response.status}")
                        continue
                    
                    html = await response.text()
                
                soup = BeautifulSoup(html, 'html.parser')
                
                # Extract event name from div.fusion-title-1
                event_name = None
                title_div = soup.find('div', class_=lambda x: x and 'fusion-title-1' in x)
                if title_div:
                    # Try h2 first (more common for actual event name)
                    h2_title = title_div.find('h2')
                    if h2_title:
                        # Use separator=' ' to insert space where <br> tags are
                        event_name = h2_title.get_text(separator=' ', strip=True)
                        # Remove extra whitespace and clean up
                        event_name = ' '.join(event_name.split())
                        # Convert to title case
                        event_name = event_name.title()
                        if event_name:
                            logger.debug(f"Found event name in fusion-title-1 h2: {event_name}")
                    
                    # Fall back to h1 if h2 is empty or not found
                    if not event_name:
                        h1_title = title_div.find('h1')
                        if h1_title:
                            # Use separator=' ' to insert space where <br> tags are
                            event_name = h1_title.get_text(separator=' ', strip=True)
                            # Remove extra whitespace and clean up
                            event_name = ' '.join(event_name.split())
                            # Convert to title case
                            event_name = event_name.title()
                            if event_name:
                                logger.debug(f"Found event name in fusion-title-1 h1: {event_name}")
                
                # Fallback if no title found
                if not event_name:
                    event_name = "WBA Hosted Event"
                    logger.warning(f"Could not find event title for {event_url}, using default")
                
                # Extract event date - search all headings for the date pattern
                # Look for patterns like "Next Event:", "Next Meeting:", etc.
                event_date_str = None
                for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                    heading_text = heading.get_text(strip=True)
                    # Match "Next [word(s)]: [date]"
                    date_match = re.search(r'Next\s+\w+(?:\s+\w+)?:\s*(.+?)$', heading_text, re.IGNORECASE)
                    if date_match:
                        event_date_str = date_match.group(1).strip()
                        # Remove anything in parentheses (e.g., "(WGC Americas Day 2)")
                        # This handles cases where the date and subtitle are combined
                        event_date_str = re.sub(r'\s*\([^)]*\)\s*', '', event_date_str).strip()
                        logger.debug(f"Found event date: {event_date_str}")
                        break
                
                if not event_date_str:
                    logger.debug("Could not find event date on page")
                
                # Set location and description (no additional details available on page)
                location = "Unknown"
                description = "View link for more info"
                
                logger.debug(f"Processing WBA-hosted event: {event_url}")
                
                # Parse event date to determine if it's in the future
                is_future_event = True  # Default to future if we can't parse
                start_date_iso = None
                
                if event_date_str:
                    try:
                        from dateutil.parser import parse as date_parse
                        event_date = date_parse(event_date_str).date()
                        is_future_event = event_date >= today
                        start_date_iso = event_date.strftime('%Y-%m-%d')
                        logger.debug(f"Parsed event date: {start_date_iso} ({'future' if is_future_event else 'past'})")
                    except Exception as e:
                        logger.warning(f"Could not parse event date '{event_date_str}': {e}")
                        # Keep defaults: treat as future event with placeholder date
                
                # Determine if we should include this event
                # Future events: Always include (to capture updates)
                # Past events: Only include if not in database
                should_include = is_future_event or not existing_urls.get(event_url, False)
                
                if should_include:
                    # Only include event if we have a valid date
                    if start_date_iso:
                        status = "future" if is_future_event else "past (new)"
                        logger.debug(f"WBA event ({status}): {event_name}")
                        events.append(Event(
                            name=event_name,
                            event_type="forum",  # WBA-hosted forum
                            start_date=start_date_iso,
                            location=location,
                            description=description,
                            url=event_url,
                            status="scheduled",
                            datasource_id=datasource_id
                        ))
                    else:
                        logger.warning(f"Skipping WBA event without valid date: {event_name} ({event_url})")
                else:
                    logger.debug(f"WBA event (past, already exists): {event_name}")
                
            except Exception as e:
                logger.error(f"Error fetching WBA event page {event_url}: {e}")
                continue
        
        return events

    async def _scrape_wgc_events(
        self,
        event_links: List,
        datasource_id: str,
        today
    ) -> List[Event]:
        """
        Extract event details from WGC event links (wirelessglobalcongress.com and others).
        
        These events are hosted on external websites (e.g., wirelessglobalcongress.com).
        We extract basic info from the listing row and may need to scrape external pages
        for full details.
        
        Event inclusion logic:
        - Future events: Always included (to capture updates)
        - Past events: Only included if not already in database
        
        Args:
            event_links: List of BeautifulSoup link elements with external URLs
            datasource_id: Datasource identifier
            today: Current date for future/past comparison
            
        Returns:
            List of Event objects
        """
        events = []
        
        # Build list of event URLs for batch checking
        event_urls = [link['href'] for link in event_links]
        existing_urls = self.batch_check_urls_exist(event_urls)
        
        for link in event_links:
            event_url = link['href']
            
            logger.debug(f"Fetching WGC event page: {event_url}")
            
            try:
                # Fetch the external event page
                async with self.session.get(
                    event_url,
                    headers=self.get_headers(referer=self.HOSTED_EVENTS_URL)
                ) as response:
                    if response.status != 200:
                        logger.error(f"Failed to fetch WGC event page: HTTP {response.status}")
                        continue
                    
                    html = await response.text()
                
                soup = BeautifulSoup(html, 'html.parser')
                
                # Extract event name from h1 nested in div.fusion-title-1
                event_name = None
                title_div = soup.find('div', class_=lambda x: x and 'fusion-title-1' in x)
                if title_div:
                    h1_title = title_div.find('h1')
                    if h1_title:
                        # Use separator=' ' to insert space where <br> tags are
                        event_name = h1_title.get_text(separator=' ', strip=True)
                        # Remove extra whitespace and clean up
                        event_name = ' '.join(event_name.split())
                        # Convert to title case
                        event_name = event_name.title()
                        if event_name:
                            logger.debug(f"Found event name in fusion-title-1 h1: {event_name}")
                
                # Fallback if no title found
                if not event_name:
                    event_name = "WGC Event"
                    logger.warning(f"Could not find event title for {event_url}, using default")
                
                # Extract date and location from fusion-button element
                # Format: "LOCATION • DATE_RANGE" (e.g., "DALLAS, USA • MAY 18 – MAY 21")
                event_date_str = None
                location = "Unknown"
                
                button = soup.find('a', class_='fusion-button')
                if button:
                    button_text_elem = button.find('span', class_='fusion-button-text')
                    if button_text_elem:
                        button_text = button_text_elem.get_text(strip=True)
                        # Split on bullet point (•) to separate location and date
                        parts = button_text.split('•')
                        if len(parts) == 2:
                            location = parts[0].strip()
                            event_date_str = parts[1].strip()
                            logger.debug(f"Found location: {location}, date: {event_date_str}")
                        else:
                            logger.debug(f"Button text format unexpected: {button_text}")
                
                # Extract description from fusion-builder-row-3
                description = ""
                row_3 = soup.find('div', class_=lambda x: x and 'fusion-builder-row-3' in x)
                if row_3:
                    # Find all fusion-text divs within this row
                    text_divs = row_3.find_all('div', class_=lambda x: x and 'fusion-text' in x)
                    if text_divs:
                        # Extract and combine text from all fusion-text divs
                        description_parts = []
                        for text_div in text_divs:
                            text = text_div.get_text(strip=True)
                            if text:
                                description_parts.append(text)
                        
                        if description_parts:
                            description = '\n\n'.join(description_parts)
                            logger.debug(f"Found description with {len(description_parts)} text sections")
                
                if not description:
                    description = "View link for more info"
                    logger.debug("No description found, using default")
                
                logger.debug(f"Processing WGC event: {event_url}")
                
                # Parse event date to determine if it's in the future
                is_future_event = True  # Default to future if we can't parse
                start_date_iso = None
                
                if event_date_str:
                    try:
                        from dateutil.parser import parse as date_parse
                        # Handle date ranges like "MAY 18 – MAY 21"
                        # Extract the start date (first date in range)
                        date_parts = event_date_str.split('–')  # Split on en-dash
                        if not date_parts or len(date_parts) == 1:
                            date_parts = event_date_str.split('-')  # Try regular dash
                        
                        # Parse the first date
                        start_date_text = date_parts[0].strip()
                        event_date = date_parse(start_date_text).date()
                        is_future_event = event_date >= today
                        start_date_iso = event_date.strftime('%Y-%m-%d')
                        logger.debug(f"Parsed event date: {start_date_iso} ({'future' if is_future_event else 'past'})")
                    except Exception as e:
                        logger.warning(f"Could not parse event date '{event_date_str}': {e}")
                        # Keep defaults: treat as future event without date
                
                # Determine if we should include this event
                # Future events: Always include (to capture updates)
                # Past events: Only include if not in database
                should_include = is_future_event or not existing_urls.get(event_url, False)
                
                if should_include:
                    # Only include event if we have a valid date
                    if start_date_iso:
                        status = "future" if is_future_event else "past (new)"
                        logger.debug(f"External event ({status}): {event_name}")
                        events.append(Event(
                            name=event_name,
                            event_type="conference",  # External industry conference
                            start_date=start_date_iso,
                            location=location,
                            description=description,
                            url=event_url,
                            status="scheduled",
                            datasource_id=datasource_id
                        ))
                    else:
                        logger.warning(f"Skipping external event without valid date: {event_name} ({event_url})")
                else:
                    logger.debug(f"External event (past, already exists): {event_name}")
                
            except Exception as e:
                logger.error(f"Error fetching WGC event page {event_url}: {e}")
                continue
        
        return events

    async def get_hosted_events(
        self,
        datasource_id: str
    ) -> List[Event]:
        """
        Discover and collect WBA hosted events.
        
        Event ingestion strategy:
        - Future events: Always included (to capture updates)
        - Past events: Only included if not already in database
        - Always processes all event links on the page
        
        Hosted events require two-phase scraping:
        1. Extract event listing links from the hosted events page
        2. Navigate to each event detail page to scrape full content
        
        Args:
            datasource_id: The datasource identifier for config lookups
            
        Returns:
            List of Event objects (future events only)
        """
        events = []
        today = datetime.now().date()
        
        logger.info(f"Discovering WBA hosted events from {self.HOSTED_EVENTS_URL}")
        logger.info(f"  Strategy: Future events always included, past events only if new")
        
        try:
            self.update_heartbeat()
            self.update_current_processing(
                Resource(title="Fetching hosted events", url=self.HOSTED_EVENTS_URL, category="event"),
                "loading hosted events page"
            )
            
            async with self.session.get(
                self.HOSTED_EVENTS_URL, 
                headers=self.get_headers(referer=self.base_url)
            ) as response:
                if response.status != 200:
                    logger.error(f"Failed to fetch hosted events page: HTTP {response.status}")
                    return events
                
                html = await response.text()
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # Extract event links from the page
            # Each event row contains nested columns with event info and a registration link
            # We're looking for <a> tags with class "fusion-button" that contain "REGISTER" text
            all_buttons = soup.find_all('a', class_='fusion-button', href=True)
            event_links = []
            for button in all_buttons:
                button_text_elem = button.find('span', class_='fusion-button-text')
                if button_text_elem and 'REGISTER' in button_text_elem.get_text(strip=True).upper():
                    event_links.append(button)
            
            logger.info(f"Found {len(event_links)} event registration links on hosted events page")
            
            if not event_links:
                logger.warning("No event links found on hosted events page")
                return events
            
            # Separate events into WBA links and WGC links based on URL
            wba_links = []
            wgc_links = []
            seen_urls = set()  # Track URLs to avoid duplicates
            
            for link in event_links:
                event_url = link['href']
                
                # Skip if we've already seen this URL
                if event_url in seen_urls:
                    logger.debug(f"Skipping duplicate event URL: {event_url}")
                    continue
                seen_urls.add(event_url)
                
                parsed = urlparse(event_url)
                host = parsed.hostname.lower() if parsed.hostname else ""
                if host == "wballiance.com" or host.endswith(".wballiance.com"):
                    wba_links.append(link)
                else:
                    wgc_links.append(link)
            
            logger.info(f"  Categorized: {len(wba_links)} WBA events, {len(wgc_links)} WGC events (after deduplication)")
            
            # Process WBA events
            if wba_links:
                logger.debug(f"Processing {len(wba_links)} WBA events")
                wba_events = await self._scrape_wba_events(
                    wba_links, 
                    datasource_id, 
                    today
                )
                events.extend(wba_events)
            
            # Process WGC events
            if wgc_links:
                logger.debug(f"Processing {len(wgc_links)} WGC events")
                wgc_events = await self._scrape_wgc_events(
                    wgc_links,
                    datasource_id,
                    today
                )
                events.extend(wgc_events)
            
        except Exception as e:
            logger.error(f"Error fetching hosted events: {e}")
            logger.exception("Full traceback:")
        
        return events

    async def get_external_events(
        self,
        datasource_id: str
    ) -> List[Event]:
        """
        Discover and collect external events.
        
        Event ingestion strategy:
        - Future events: Always included (to capture updates)
        - Past events: Only included if not already in database
        - Always processes all event links on the page
        
        External events are simpler - all information is on a single page.
        No need to navigate to detail pages.
        
        Args:
            datasource_id: The datasource identifier for config lookups
            
        Returns:
            List of Event objects (future events only)
        """
        events = []
        today = datetime.now().date()
        
        logger.info(f"Discovering external events from {self.EXTERNAL_EVENTS_URL}")
        logger.info(f"  Strategy: Future events always included, past events only if new")
        
        try:
            self.update_heartbeat()
            self.update_current_processing(
                Resource(title="Fetching external events", url=self.EXTERNAL_EVENTS_URL, category="event"),
                "loading external events page"
            )
            
            async with self.session.get(
                self.EXTERNAL_EVENTS_URL, 
                headers=self.get_headers(referer=self.base_url)
            ) as response:
                if response.status != 200:
                    logger.error(f"Failed to fetch external events page: HTTP {response.status}")
                    return events
                
                html = await response.text()
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # Find the container with equal-height columns
            container = soup.find('div', class_=lambda x: x and 'fusion-equal-height-columns' in x)
            if not container:
                logger.warning("No fusion-equal-height-columns container found on external events page")
                return events
            
            # Find all fusion-builder-row elements within the container (there may be multiple rows)
            # Only search direct children to avoid nested rows
            builder_rows = container.find_all('div', class_=lambda x: x and 'fusion-builder-row' in x and 'fusion-row' in x, recursive=False)
            if not builder_rows:
                logger.warning("No fusion-builder-row found in external events container")
                return events
            
            logger.info(f"Found {len(builder_rows)} event row(s) in external events container")
            
            # Collect event columns from all rows
            event_columns = []
            for builder_row in builder_rows:
                # Find all event columns within this row (direct children only to avoid nested columns)
                # Look for div.fusion-layout-column.fusion-builder-column-X that are direct children
                for child in builder_row.children:
                    if hasattr(child, 'attrs') and child.name == 'div':
                        classes = child.get('class', [])
                        # Check if it has both fusion-layout-column and fusion-builder-column-X classes
                        if any('fusion-layout-column' in c for c in classes) and any('fusion-builder-column-' in c for c in classes):
                            event_columns.append(child)
            
            logger.info(f"Found {len(event_columns)} event columns on external events page")
            
            if not event_columns:
                logger.warning("No event columns found in external events container")
                return events
            
            # Build list of event URLs for batch checking
            event_urls = []
            for column in event_columns:
                # Extract registration link
                register_link = column.find('a', class_='fusion-button', href=True)
                if register_link:
                    event_url = register_link['href']
                    event_urls.append(event_url)
            
            # Batch check which event URLs already exist in the database
            existing_urls = self.batch_check_urls_exist(event_urls)
            
            # Process each event column
            for column in event_columns:
                try:
                    # Extract event title from h4
                    event_name = None
                    h4_title = column.find('h4')
                    if h4_title:
                        event_name = h4_title.get_text(strip=True)
                        logger.debug(f"Found event title: {event_name}")
                    
                    if not event_name:
                        logger.warning("No event title found in column, skipping")
                        continue
                    
                    # Extract date and location from h2
                    event_date_str = None
                    location = "Unknown"
                    h2_date = column.find('h2')
                    if h2_date:
                        date_text = h2_date.get_text(strip=True)
                        # Format: "20 January 2026, Webinar" or similar
                        # Split on comma to separate date from location/type
                        parts = date_text.split(',')
                        if len(parts) >= 2:
                            event_date_str = parts[0].strip()
                            location = parts[1].strip()
                            logger.debug(f"Found date: {event_date_str}, location: {location}")
                        else:
                            event_date_str = date_text
                            logger.debug(f"Found date (no location): {event_date_str}")
                    
                    # Extract description from h6 elements
                    description_parts = []
                    h6_elements = column.find_all('h6')
                    for h6 in h6_elements:
                        text = h6.get_text(strip=True)
                        if text:
                            description_parts.append(text)
                    
                    description = '\n\n'.join(description_parts) if description_parts else "View link for more info"
                    logger.debug(f"Found description with {len(description_parts)} parts")
                    
                    # Extract registration link (event URL)
                    event_url = None
                    register_link = column.find('a', class_='fusion-button', href=True)
                    if register_link:
                        event_url = register_link['href']
                        logger.debug(f"Found registration URL: {event_url}")
                    
                    if not event_url:
                        logger.warning(f"No registration URL found for event: {event_name}, skipping")
                        continue
                    
                    # Parse event date to determine if it's in the future
                    is_future_event = True  # Default to future if we can't parse
                    start_date_iso = None
                    
                    if event_date_str:
                        try:
                            from dateutil.parser import parse as date_parse
                            event_date = date_parse(event_date_str).date()
                            is_future_event = event_date >= today
                            start_date_iso = event_date.strftime('%Y-%m-%d')
                            logger.debug(f"Parsed event date: {start_date_iso} ({'future' if is_future_event else 'past'})")
                        except Exception as e:
                            logger.warning(f"Could not parse event date '{event_date_str}': {e}")
                            # Keep defaults: treat as future event without date
                    
                    # Determine if we should include this event
                    # Future events: Always include (to capture updates)
                    # Past events: Only include if not in database
                    should_include = is_future_event or not existing_urls.get(event_url, False)
                    
                    if should_include:
                        # Only include event if we have a valid date
                        if start_date_iso:
                            status = "future" if is_future_event else "past (new)"
                            logger.debug(f"External event ({status}): {event_name}")
                            events.append(Event(
                                name=event_name,
                                event_type="external",  # External industry event
                                start_date=start_date_iso,
                                location=location,
                                description=description,
                                url=event_url,
                                status="scheduled",
                                datasource_id=datasource_id
                            ))
                        else:
                            logger.warning(f"Skipping external event without valid date: {event_name} ({event_url})")
                    else:
                        logger.debug(f"External event (past, already exists): {event_name}")
                
                except Exception as e:
                    logger.error(f"Error processing external event column: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"Error fetching external events: {e}")
            logger.exception("Full traceback:")
        
        return events

    async def scrape_resource(self, resource: Resource) -> Resource:
        """
        Scrape a resource's content (PDF, HTML page, or metadata-only).
        
        NOTE: Events are NOT processed through this method. Events use publish_event()
        directly since they already have all their data from the listing pages.
        
        Handles:
        - PDF documents: Downloads and extracts text content
        - YouTube videos: Stores metadata only (title, URL)
        - ZIP archives: Stores metadata only (title, URL)
        - HTML pages: Extracts page content
        
        Uses the authenticated session if available.
        """
        try:
            self.update_heartbeat()
            self.update_current_processing(resource, "extracting content")
            
            # YouTube videos - metadata only
            if self.is_youtube_url(resource.url):
                logger.info(f"YouTube video detected (metadata only): {resource.url}")
                resource.content = f"YouTube video: {resource.url}"
                if not resource.title:
                    resource.title = "YouTube Video"
                return resource
            
            # ZIP archives - metadata only
            if self.is_zip_url(resource.url):
                logger.info(f"ZIP archive detected (metadata only): {resource.url}")
                resource.content = f"ZIP archive available for download: {resource.url}"
                if not resource.title:
                    resource.title = "ZIP Archive"
                return resource
            
            # Document files (PDF, DOCX, etc.)
            if self.is_document_url(resource.url):
                # Document download (PDF, DOCX, etc.)
                if not self.is_authenticated:
                    logger.warning(
                        f"Document requires authentication but not logged in: {resource.url}"
                    )
                
                # Try to download and extract (session has auth cookies if authenticated)
                try:
                    async with self.session.get(
                        resource.url, 
                        headers=self.get_headers(referer=self.resources_url), 
                        allow_redirects=True
                    ) as response:
                        if response.status == 200:
                            # Successfully downloaded
                            if resource.url.lower().endswith('.pdf'):
                                pdf_bytes = await response.read()
                                pdf_text = self.extract_pdf_text_from_bytes(pdf_bytes, include_page_markers=False)
                                resource.content = pdf_text
                            else:
                                # Other document types (.docx, .xlsx, etc.)
                                # For now, just note the document type
                                doc_type = resource.url.split('.')[-1].upper()
                                resource.content = f"[{doc_type} document - extraction not yet implemented]"
                        elif response.status == 401 or response.status == 403:
                            logger.error(f"Access denied for document (HTTP {response.status}): {resource.url}")
                            resource.content = f"Access denied - authentication may have failed or insufficient permissions"
                        else:
                            logger.error(f"Failed to download document (HTTP {response.status}): {resource.url}")
                            resource.content = f"Error downloading document: HTTP {response.status}"
                except Exception as e:
                    logger.error(f"Error downloading document {resource.url}: {e}")
                    resource.content = f"Error downloading document: {str(e)}"
            else:
                # HTML page
                async with self.session.get(resource.url, headers=self.get_headers(referer=self.resources_url)) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        await self.extract_html_content(resource, soup)
                    elif response.status == 401 or response.status == 403:
                        resource.content = f"Access denied: HTTP {response.status}"
                    else:
                        resource.content = f"Error: HTTP {response.status}"
                
        except Exception as e:
            logger.error(f"Error scraping {resource.url}: {e}")
            resource.content = f"Error: {str(e)}"

        return resource

    async def extract_html_content(self, resource: Resource, soup: BeautifulSoup):
        """
        Extract content from HTML page.
        
        Placeholder implementation - HTML page extraction not yet implemented for WBA.
        """
        logger.info(f"HTML page detected but extraction not implemented: {resource.url}")
        resource.content = f"HTML page (extraction not yet implemented): {resource.url}"

    async def run_scraper(self, datasource_config: Dict[str, Any]):
        """
        Scrape content from the Wireless Broadband Alliance website.
        
        Scraping order:
        1. WBA Hosted Events (/wba-hosted-events/)
        2. External Events (/external-events/)
        3. Resources (/resources/) - only if resource_url points to /resources/
        
        Supports two modes:
        - Incremental (daily): Scrapes newest content first, stops after finding duplicates
        - Full refresh: Scans all content and re-scrapes updated items
        
        Authentication credentials are read from environment variables:
        - WBA_USERNAME: WBA account username
        - WBA_PASSWORD: WBA account password
        
        Args:
            datasource_config: Configuration dict from database containing:
                - datasource_id: Unique identifier
                - resource_url: URL path to scrape (e.g., '/resources/', '/wba-hosted-events/')
                - scrape_frequency, max_resources, scraper_delay, etc.
        """
        datasource_id = datasource_config.get('datasource_id', 'wba_resources')
        resource_url = datasource_config.get('resource_url', '/resources/')
        
        # Update base resources URL if custom path provided
        if resource_url != '/resources/':
            self.resources_url = f"{self.base_url}{resource_url}"

        max_resources = datasource_config.get('max_resources', -1)  # Default to unlimited
        scraper_delay = datasource_config.get('scraper_delay', 0.5)
        
        # Get discovery mode settings
        discovery_mode = datasource_config.get('discovery_mode', 'incremental')
        consecutive_duplicates_limit = datasource_config.get('consecutive_duplicates_limit', 5)
        is_full_refresh = datasource_config.get('is_full_refresh', False)
        check_content_hash = datasource_config.get('check_content_hash', True)
        
        # If full refresh is requested, disable limits to scan everything
        if is_full_refresh:
            logger.info("  FULL REFRESH mode - disabling consecutive duplicate limit and max resources")
            logger.info(f"    Content hash checking: {'enabled' if check_content_hash else 'disabled'}")
            consecutive_duplicates_limit = 0
            max_resources = -1  # Unlimited
        
        logger.info(f"Starting WBA scraper for {datasource_id}")
        logger.info(f"  Target URL: {resource_url}, max={max_resources}, delay={scraper_delay}s")
        logger.info(f"  Discovery: mode={discovery_mode}, consecutive_dup_limit={consecutive_duplicates_limit}, full_refresh={is_full_refresh}")
        
        # Attempt authentication if credentials are configured in environment
        auth_success = False
        if settings.wba_username and settings.wba_password:
            auth_success = await self.authenticate(settings.wba_username, settings.wba_password)
            
            if not auth_success:
                error_msg = f"WBA scraper authentication failed for {datasource_id}. Cannot proceed with scraping."
                logger.error(error_msg)
                # Don't create a batch if we can't authenticate
                raise Exception(error_msg)
        else:
            logger.warning(f"No WBA credentials configured. Scraping will proceed but document downloads will fail.")
        
        # Start ingestion batch for tracking
        batch_id = self.start_batch(datasource_id)
        logger.debug(f"  Batch ID: {batch_id}")
        
        resources_processed = 0
        events = []
        resources = []
        
        try:
            # ===========================================
            # Phase 1: Discover Content (Events First, Then Resources)
            # ===========================================
            logger.info("Phase 1: Discovering content")
            
            # 1.1: Discover Hosted Events
            logger.info("  1.1: Discovering WBA hosted events")
            hosted_events = await self.get_hosted_events(datasource_id=datasource_id)
            events.extend(hosted_events)
            logger.info(f"Found {len(hosted_events)} future hosted events")
            
            # 1.2: Discover External Events
            logger.info("  1.2: Discovering external events")
            external_events = await self.get_external_events(datasource_id=datasource_id)
            events.extend(external_events)
            logger.info("Found {len(external_events)} future external events")
            
            # 1.3: Discover Resources (only if resource_url points to /resources/)
            if resource_url == '/resources/' or '/resources/' in resource_url:
                logger.info(f"  1.3: Discovering resources (year range: {self.START_YEAR} to {datetime.now().year})")
                remaining = max_resources - len(events) - len(resources) if max_resources >= 0 else -1
                discovered_resources = await self.get_resources(
                    datasource_id=datasource_id,
                    max_resources=remaining,
                    discovery_mode=discovery_mode,
                    consecutive_duplicates_limit=consecutive_duplicates_limit,
                    is_full_refresh=is_full_refresh,
                    check_content_hash=check_content_hash
                )
                resources.extend(discovered_resources)
                
                # Log summary based on mode
                if is_full_refresh and check_content_hash:
                    logger.info(f"    Found {len(discovered_resources)} resources (new + changed content)")
                else:
                    logger.info(f"    Found {len(discovered_resources)} new resources")
            elif '/newsroom/' in resource_url or resource_url == '/newsroom/':
                logger.info("  1.3: Discovering WBA newsroom articles")
                remaining = max_resources - len(events) - len(resources) if max_resources >= 0 else -1
                newsroom_articles = await self.get_newsroom_articles(
                    datasource_id=datasource_id,
                    max_articles=remaining,
                    consecutive_duplicates_limit=consecutive_duplicates_limit,
                )
                resources.extend(newsroom_articles)
                logger.info(f"    Found {len(newsroom_articles)} new newsroom articles")
            else:
                logger.info(f"  1.3: Skipping resources (resource_url is not /resources/ or /newsroom/)")
            
            total_items = len(events) + len(resources)
            logger.info(f"Phase 1 complete: {total_items} total items discovered ({len(events)} events, {len(resources)} resources)")
            
            # ===========================================
            # Phase 2: Scrape & Publish Content
            # ===========================================

            # Phase 2.1: Scrape & Publish Hosted Events (need detail page scraping)
            if events:
                logger.info(f"Phase 2a: Scraping and publishing {len(events)} events")
                for i, event in enumerate(events, 1):
                    try:
                        self.update_heartbeat()
                        self.update_current_processing(
                            event, 
                            f"scraping event ({i}/{len(events)})"
                        )
                        
                        # Events already have full content from listing pages
                        self.publish_event(event)
                        resources_processed += 1
                        
                        await asyncio.sleep(scraper_delay)
                        
                    except Exception as e:
                        logger.error(f"Error processing event {event.name}: {e}")
                        continue

            # Phase 2.2: Scrape & Publish Resources
            if resources:
                logger.info(f"Phase 2b: Scraping and publishing {len(resources)} resources")
                
                for i, item in enumerate(resources, 1):
                    try:
                        self.update_heartbeat()
                        self.update_current_processing(
                            item, 
                            f"publishing resource ({i}/{len(resources)})"
                        )
                        
                        logger.debug(f"Processing resource {i}/{len(resources)}: {item.title}")
                        
                        # In full refresh mode with content checking, resources are already scraped
                        # In incremental mode, we need to scrape them
                        if is_full_refresh and check_content_hash and item.content:
                            # Already scraped during discovery phase
                            scraped_item = item
                        else:
                            # Need to scrape the content
                            scraped_item = await self.scrape_resource(item)
                        
                        self.publish_resource(scraped_item)
                        resources_processed += 1
                        
                        await asyncio.sleep(scraper_delay)
                        
                    except Exception as e:
                        logger.error(f"Error processing resource {item.title}: {e}")
                        continue
            
            if not events and not resources:
                logger.info("No new content found")

            self.mark_datasource_scraped(datasource_id)
            
            # End batch and signal completion
            self.end_batch(resources_processed)
            
            logger.info(f"Scraping completed: {resources_processed} resources processed")
            
        except Exception as e:
            logger.error(f"Error running WBA scraper for {datasource_id}: {e}")
            
            # End batch with error (items sent so far)
            if self.get_current_batch_id():
                self.end_batch(self._batch_items_count)
            
            raise
        finally:
            self.clear_current_processing()
