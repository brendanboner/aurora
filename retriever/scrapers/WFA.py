import asyncio
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
from typing import List, Optional, Union, Dict, Any
import logging
import json

from .base import BaseScraper, Resource, Event
from settings import settings

logger = logging.getLogger(__name__)


class WFAScraper(BaseScraper):
    """
    Scraper for the public Wi-Fi Alliance website.
    
    Configuration:
    The datasource config in database (system_configuration table) provides:
    - resource_url: URL path to scrape (e.g., '/resource-center')
    - scrape_frequency, max_resources, scraper_delay, etc.
    """
    
    DOCUMENT_EXTENSIONS = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']
    scraper_name = "wfa"  # Used for JSON file naming
    
    # Base URL for the WFA public website (domain only, resource paths come from database)
    BASE_URL = "https://www.wi-fi.org"

    # Media/logo download blacklist — zero Q&A value, should never be ingested.
    # URL patterns that match binary-asset or brand-kit download pages.
    MEDIA_BLACKLIST_URL_PATTERNS = [
        r'/wi-fi-download/\d+',          # WFA download-ID redirect pages
        r'\.zip(\?|$)',                   # ZIP archives
        r'\.(png|jpg|jpeg|svg|gif|ico|webp)(\?|$)',  # Image files
        r'\.(mp4|mov|avi|webm)(\?|$)',   # Video files (not transcripts)
    ]
    # Scraper-assigned categories that are exclusively media/branding content.
    MEDIA_BLACKLIST_CATEGORIES = frozenset({
        'branding and media', 'media kit', 'logos and graphics',
    })
    # Title keywords that — combined with a media category — confirm a brand asset.
    MEDIA_BLACKLIST_TITLE_KEYWORDS = (
        'logo', 'graphic', 'icon', 'branding', 'ui visual', 'logo package',
        'media kit', 'brand asset', 'visual guide',
    )

    def _is_media_blacklisted(self, url: str, category: str, title: str) -> bool:
        """Return True if this resource is a media/brand asset with no Q&A value."""
        for pattern in self.MEDIA_BLACKLIST_URL_PATTERNS:
            if re.search(pattern, url, re.IGNORECASE):
                return True
        cat_lower = category.lower().strip()
        if cat_lower in self.MEDIA_BLACKLIST_CATEGORIES:
            title_lower = (title or '').lower()
            if any(kw in title_lower for kw in self.MEDIA_BLACKLIST_TITLE_KEYWORDS):
                return True
        return False
    
    def __init__(self):
        super().__init__()
        self.base_url = self.BASE_URL
        self.resource_center_url = None  # Set from config in run_scraper

    def is_document_url(self, url: str) -> bool:
        """Check if URL points to a document file"""
        return any(ext in url.lower() for ext in self.DOCUMENT_EXTENSIONS)

    def _extract_resources_from_soup(
        self, 
        soup: BeautifulSoup, 
        item_type: str = "all",
        datasource_id: str = None
    ) -> List[Union[Resource, Event]]:
        """
        Extract resources and/or events from card elements on the page.
        
        Args:
            soup: BeautifulSoup object of the page
            item_type: Filter type - 'resources' (exclude events), 'events' (only events), or 'all'
            datasource_id: Datasource ID to assign to items
            
        Returns:
            List of Resource and/or Event objects based on item_type filter
        """
        items = []
        card_elements = soup.find_all('div', class_=lambda x: x and 'card' in str(x).lower())
        
        for card in card_elements:
            link = next((a for a in card.find_all('a') if a.get('href')), None)
            if not link:
                continue
                
            url = urljoin(self.base_url, link['href'])
            
            # Extract title (skip truncated titles ending with '..')
            title = None
            title_element = card.find('h5')
            if title_element:
                extracted_title = title_element.get_text(strip=True)
                if not extracted_title.endswith('..'):
                    title = extracted_title
            
            category_element = card.find('span', class_='resources-type')
            category = category_element.get_text(strip=True).lower() if category_element else ''
            
            is_event = category == 'event'
            
            # Apply filter based on item_type
            if item_type == 'resources' and is_event:
                continue  # Skip events when only collecting resources
            elif item_type == 'events' and not is_event:
                continue  # Skip non-events when only collecting events
            
            if is_event:
                items.append(Event(
                    name=title or 'Event name to be extracted',
                    event_type='other',
                    start_date='',
                    url=url,
                    datasource_id=datasource_id or 'wfa_events'
                ))
            else:
                if self._is_media_blacklisted(url, category, title or ''):
                    logger.info(f"Skipping media/brand asset (blacklisted): {url}")
                    continue
                items.append(Resource(
                    title=title or 'Title to be extracted',
                    url=url,
                    category=category,
                    datasource_id=datasource_id or 'wfa_resource_page'
                ))
        
        return items
    
    async def get_resource_links(
        self, 
        datasource_id: str, 
        max_resources: int = -1,
        discovery_mode: str = "incremental",
        consecutive_duplicates_limit: int = 5
    ) -> List[Resource]:
        """
        Extract resource links from the resource center (excludes events).
        Resolves redirects and checks for duplicates.
        
        In incremental mode, stops pagination after finding consecutive_duplicates_limit
        consecutive URLs that already exist in the database.
        
        Args:
            datasource_id: The datasource identifier for config lookups
            max_resources: Maximum number of new items to collect (-1 = unlimited)
            discovery_mode: 'incremental' (stop after consecutive dups) or other modes
            consecutive_duplicates_limit: Stop after this many consecutive duplicates (default 5)
            
        Returns:
            List of Resource objects (events are excluded - use get_event_links instead)
        """
        new_items = []
        page = 0
        duplicates_skipped = 0
        consecutive_duplicates = 0
        
        while True:
            page_url = f"{self.resource_center_url}?page={page}" if page > 0 else self.resource_center_url
            logger.debug(f"Fetching resources page {page + 1}")
            
            self.update_heartbeat()
            self.update_current_processing(
                Resource(title="Fetching resource list", url=page_url, category="discovery"),
                f"loading page {page + 1}"
            )
            
            async with self.session.get(page_url) as response:
                html = await response.text()
            
            soup = BeautifulSoup(html, 'html.parser')
            # Filter to resources only (exclude events)
            page_items = self._extract_resources_from_soup(soup, item_type="resources", datasource_id=datasource_id)
            
            if not page_items:
                logger.debug(f"No resources on page {page + 1}, stopping")
                break
            
            for item in page_items:
                if max_resources >= 0 and len(new_items) >= max_resources:
                    break
                
                try:
                    self.update_heartbeat()
                    final_url = await self.follow_redirect_chain(item.url, datasource_id)
                    
                    # Skip duplicate resources
                    if self.url_exists_in_db(final_url):
                        duplicates_skipped += 1
                        consecutive_duplicates += 1
                        
                        # In incremental mode, stop after hitting consecutive duplicate limit
                        # (limit of 0 means disabled/no limit)
                        if (discovery_mode == "incremental" and 
                            consecutive_duplicates_limit > 0 and 
                            consecutive_duplicates >= consecutive_duplicates_limit):
                            logger.debug(
                                f"Stopping pagination: reached {consecutive_duplicates} consecutive duplicates "
                                f"(limit: {consecutive_duplicates_limit})"
                            )
                            # Return early with what we have
                            logger.info(f"Found {len(new_items)} new resources ({duplicates_skipped} duplicates skipped)")
                            return new_items
                        
                        continue
                    
                    # Reset consecutive counter when we find a new item
                    consecutive_duplicates = 0
                    
                    item.url = final_url
                    new_items.append(item)
                    
                except Exception as e:
                    logger.error(f"Error processing item {item.url}: {e}")
                    continue
            
            if max_resources >= 0 and len(new_items) >= max_resources:
                break
            
            await asyncio.sleep(self.get_scraper_delay(datasource_id))
            page += 1
        
        logger.info(f"Found {len(new_items)} new resources ({duplicates_skipped} duplicates skipped)")
        return new_items
    
    async def get_event_links(
        self, 
        datasource_id: str,
        max_events: int = -1,
        max_pages: int = 100
    ) -> List[Event]:
        """
        Extract all event links from the events-filtered resource center URL.
        
        Uses the events-only filter URL to get a dedicated list of events.
        Paginates through all pages (up to max_pages) since events are not
        posted in chronological order - a future event may be buried behind
        recently-posted short-term events.
        
        Args:
            datasource_id: The datasource identifier for config lookups
            max_events: Maximum number of events to collect (-1 = unlimited)
            max_pages: Maximum pages to scrape (safety limit, default 100)
            
        Returns:
            List of Event objects (filtering for new/future is done later via filter_events)
        """
        # Events-only URL filter (resource_type 472 = events in WFA Drupal)
        events_url = f"{self.resource_center_url}?resource_type%5B472%5D=472"
        
        events = []
        page = 0
        total_events_found = 0
        
        logger.info(f"Fetching events from: {events_url}")
        if max_events >= 0:
            logger.debug(f"  Max events limit: {max_events}")
        
        while page < max_pages:
            # Check if we've hit the max events limit
            if max_events >= 0 and len(events) >= max_events:
                logger.info(f"Reached max events limit ({max_events}), stopping pagination")
                break
            
            page_url = f"{events_url}&page={page}" if page > 0 else events_url
            logger.debug(f"Fetching events page {page + 1}")
            
            self.update_heartbeat()
            self.update_current_processing(
                Event(name="Fetching event list", event_type="discovery", start_date="", datasource_id=datasource_id),
                f"loading events page {page + 1}"
            )
            
            try:
                async with self.session.get(page_url) as response:
                    if response.status != 200:
                        logger.warning(f"Failed to fetch events page {page + 1}: HTTP {response.status}")
                        break
                    html = await response.text()
            except Exception as e:
                logger.error(f"Error fetching events page {page + 1}: {e}")
                break
            
            soup = BeautifulSoup(html, 'html.parser')
            # Extract events only
            page_events = self._extract_resources_from_soup(soup, item_type="events", datasource_id=datasource_id)
            
            if not page_events:
                logger.debug(f"No events on page {page + 1}, stopping pagination")
                break
            
            total_events_found += len(page_events)
            
            # Resolve redirects for each event URL
            for event in page_events:
                # Check max_events limit before adding
                if max_events >= 0 and len(events) >= max_events:
                    break
                    
                try:
                    self.update_heartbeat()
                    final_url = await self.follow_redirect_chain(event.url, datasource_id)
                    event.url = final_url
                    events.append(event)
                except Exception as e:
                    logger.error(f"Error processing event {event.url}: {e}")
                    continue
            
            await asyncio.sleep(self.get_scraper_delay(datasource_id))
            page += 1
        
        # Warn if we hit the page limit
        if page >= max_pages:
            logger.warning(f"Reached max pages limit ({max_pages}) while fetching events")
        
        # Warn if no events found at all (potential URL/selector issue)
        if total_events_found == 0:
            logger.warning(
                f"No events found across all pages from {events_url}. "
                f"This may indicate an issue with the events filter URL (resource_type=472) or card selectors."
            )
        else:
            logger.info(f"Found {len(events)} events across {page} pages")
        
        return events
    
    async def scrape_resource(self, resource: Resource) -> Resource:
        """Scrape a resource's content (PDF or HTML page)."""
        try:
            self.update_heartbeat()
            self.update_current_processing(resource, "extracting content")
            
            if self.is_document_url(resource.url):
                pdf_text = await self.extract_pdf_text(resource.url)
                resource.content = pdf_text if pdf_text else "PDF document - text extraction failed"
            else:
                async with self.session.get(resource.url) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        await self.extract_html_content(resource, soup)
                    else:
                        resource.content = f"Error: HTTP {response.status}"
                
        except Exception as e:
            logger.error(f"Error scraping {resource.url}: {e}")
            resource.content = f"Error: {str(e)}"

        return resource
    
    async def scrape_event(self, event: Event) -> Event:
        """Scrape event details from an event page."""
        try:
            self.update_heartbeat()
            self.update_current_processing(event, "extracting event details")
            
            async with self.session.get(event.url) as response:
                if response.status != 200:
                    logger.error(f"Failed to fetch event page: HTTP {response.status}")
                    event.description = f"Error: HTTP {response.status}"
                    return event
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Extract full title if it was truncated
                if event.name == 'Event name to be extracted':
                    title_element = soup.find('h1') or soup.find(class_='title')
                    if title_element:
                        event.name = title_element.get_text(strip=True)
                
                # Extract dates from <time datetime="..."> elements
                time_elements = soup.find_all('time', class_='datetime', attrs={'datetime': True})
                if time_elements:
                    from dateutil import parser as date_parser
                    if len(time_elements) >= 1:
                        start_datetime = time_elements[0].get('datetime')
                        if start_datetime:
                            event.start_date = date_parser.parse(start_datetime).strftime('%Y-%m-%d')
                    
                    if len(time_elements) >= 2:
                        end_datetime = time_elements[1].get('datetime')
                        if end_datetime:
                            event.end_date = date_parser.parse(end_datetime).strftime('%Y-%m-%d')
                else:
                    logger.warning(f"No <time> elements found for event: {event.url}")
                
                # Extract location from h2 elements (skip the one containing date/time)
                for h2 in soup.find_all('h2'):
                    if h2.find('time'):
                        continue
                    text = h2.get_text(strip=True)
                    if text:
                        event.location = text
                        break
                
                # Check for virtual indicators if no location found
                if not event.location:
                    if soup.find(string=re.compile(r'Virtual|Online|Webinar', re.IGNORECASE)):
                        event.location = "Virtual"
                
                event.event_type = "other"  # Default type
                
                # Extract description from main content section
                content_area = soup.find('section')
                if content_area:
                    for unwanted in content_area.find_all(['nav', 'aside', 'footer', 'header']):
                        unwanted.decompose()
                    event.description = content_area.get_text(strip=True, separator='\n')
                
        except Exception as e:
            logger.error(f"Error scraping event {event.url}: {e}")
            event.description = f"Error: {str(e)}"
        
        return event
    
    def _parse_event_dates(self, date_text: str) -> Optional[dict]:
        """Parse event date text into structured dates."""
        try:
            from dateutil import parser as date_parser
            
            # Check for date range: "Month DD-DD, YYYY"
            range_match = re.search(r'(\w+)\s+(\d{1,2})-(\d{1,2}),?\s+(\d{4})', date_text)
            if range_match:
                month, start_day, end_day, year = range_match.groups()
                return {
                    'start_date': date_parser.parse(f"{month} {start_day}, {year}").strftime('%Y-%m-%d'),
                    'end_date': date_parser.parse(f"{month} {end_day}, {year}").strftime('%Y-%m-%d')
                }
            
            return {'start_date': date_parser.parse(date_text).strftime('%Y-%m-%d')}
            
        except Exception as e:
            logger.warning(f"Failed to parse event date '{date_text}': {e}")
            from datetime import datetime
            return {'start_date': datetime.now().strftime('%Y-%m-%d')}
    
    async def follow_redirect_chain(self, url: str, datasource_id: str, max_redirects: int = None) -> str:
        """Follow server redirects, then check for client-side redirects."""
        if max_redirects is None:
            max_redirects = self.get_max_redirects(datasource_id)
        
        current_url = url
        redirect_count = 0
        
        while redirect_count < max_redirects:
            async with self.session.get(current_url, allow_redirects=False) as response:
                if response.status in [301, 302, 303, 307, 308]:
                    location = response.headers.get('Location')
                    if location:
                        current_url = urljoin(current_url, location)
                        redirect_count += 1
                        continue
                break
        
        if redirect_count >= max_redirects:
            logger.warning(f"Max redirects ({max_redirects}) reached for URL: {current_url}")
            return current_url
        
        return await self.check_for_client_side_redirect_url(current_url)
    
    async def check_for_client_side_redirect_url(self, url: str) -> str:
        """Check for Drupal client-side redirects to document files."""
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    content_type = response.headers.get('content-type', '').lower()
                    
                    if 'text/html' in content_type:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Look for filePath in Drupal scripts
                        drupal_scripts = soup.find_all('script', attrs={'data-drupal-selector': True})
                        for script in drupal_scripts:
                            if script.string:
                                filepath_pattern = r'["\']?filePath["\']?\s*:\s*["\']([^"\']+)["\']'
                                matches = re.findall(filepath_pattern, script.string, re.IGNORECASE)
                                
                                for match in matches:
                                    clean_match = match.replace('\\/', '/')
                                    if self.is_document_url(clean_match):
                                        return urljoin(self.base_url, clean_match)
        
        except Exception as e:
            logger.error(f"Error checking for client-side redirect: {e}")
        
        return url
    
    async def extract_pdf_text(self, pdf_url: str) -> Optional[str]:
        """Extract text from PDF URL. Uses base class implementation."""
        return await self.fetch_and_extract_pdf(pdf_url, include_page_markers=False)

    async def extract_html_content(self, resource: Resource, soup: BeautifulSoup):
        """Extract content from HTML page."""
        if resource.title is None or resource.title == 'Title to be extracted':
            title_element = soup.find('h1') or soup.find(class_='title')
            if title_element:
                resource.title = title_element.get_text(strip=True)
        
        # Try multiple date selectors
        date_element = (
            soup.find('span', class_='asset-date') or 
            soup.find(class_='date-meta-data')
        )
        if date_element:
            raw_date = date_element.get_text(strip=True)
            # Parse and normalize the date to ISO 8601 format
            try:
                from dateutil.parser import parse as date_parse
                parsed_date = date_parse(raw_date)
                resource.publish_date = parsed_date.isoformat()
            except Exception as e:
                logger.warning(f"Failed to parse publish date '{raw_date}': {e}")
                resource.publish_date = None
            # Parse and normalize date to ISO 8601 format
            try:
                from dateutil.parser import parse as date_parse
                parsed_date = date_parse(date_text)
                resource.publish_date = parsed_date.isoformat()
            except Exception as e:
                logger.warning(f"Failed to parse date '{date_text}': {e}")
                resource.publish_date = None
        
        content_area = soup.find('div', id='block-wfb-content')
        if content_area:
            for unwanted in content_area.find_all(['nav', 'aside', 'footer', 'header']):
                unwanted.decompose()
            resource.content = content_area.get_text(strip=True, separator='\n')
    
    async def run_scraper(self, datasource_config: Dict[str, Any] = None):
        """
        Scrape resources and events from the Wi-Fi Alliance resource center.
        
        Resources and events are scraped separately:
        - Resources: From /resource-center with incremental duplicate detection
        - Events: From /resource-center?resource_type[472]=472 with full pagination
        
        Args:
            datasource_config: Configuration dict from database containing:
                - datasource_id: Unique identifier
                - resource_url: URL path to scrape (e.g., '/resource-center')
                - scrape_frequency, max_resources, scraper_delay, etc.
        """
        # Support legacy mode (no config passed) for backwards compatibility
        if datasource_config is None:
            datasource_config = self.get_datasource_config('wfa_resource_page')
        
        datasource_id = datasource_config.get('datasource_id', 'wfa_resource_page')
        resource_url = datasource_config.get('resource_url', '/resource-center')
        
        # Set the resource center URL from config
        self.resource_center_url = f"{self.base_url}{resource_url}"

        max_resources = datasource_config.get('max_resources', 150)
        scraper_delay = datasource_config.get('scraper_delay', 0.5)
        
        # Get discovery mode settings
        discovery_mode = datasource_config.get('discovery_mode', 'incremental')
        consecutive_duplicates_limit = datasource_config.get('consecutive_duplicates_limit', 5)
        is_full_refresh = datasource_config.get('is_full_refresh', False)
        
        # If full refresh is requested, disable limits to scan everything
        if is_full_refresh:
            logger.info("  FULL REFRESH mode - disabling consecutive duplicate limit and max resources")
            consecutive_duplicates_limit = 0
            max_resources = -1  # Unlimited
        
        logger.info(f"Starting Wi-Fi Alliance scraper for {datasource_id}")
        logger.info(f"  Resource URL: {self.resource_center_url}, max={max_resources}, delay={scraper_delay}s")
        logger.info(f"  Discovery: mode={discovery_mode}, consecutive_dup_limit={consecutive_duplicates_limit}, full_refresh={is_full_refresh}")
        
        # Start ingestion batch for tracking
        batch_id = self.start_batch(datasource_id)
        logger.debug(f"  Batch ID: {batch_id}")
        
        events_processed = 0
        resources_processed = 0
        
        try:
            # ===========================================
            # Phase 1: Scrape Events (separate URL with full pagination)
            # ===========================================
            logger.info("Phase 1: Scraping events from events-filtered URL")
            
            events = await self.get_event_links(datasource_id, max_events=max_resources)
            
            if events:
                logger.info(f"Discovered {len(events)} event links, scraping details...")
                
                # Scrape event details
                scraped_events = []
                for i, event in enumerate(events, 1):
                    try:
                        self.update_heartbeat()
                        self.update_current_processing(event, f"scraping event ({i}/{len(events)})")
                        
                        logger.debug(f"Scraping event {i}/{len(events)}: {event.name}")
                        
                        scraped_event = await self.scrape_event(event)
                        scraped_events.append(scraped_event)
                        
                        await asyncio.sleep(scraper_delay)
                        
                    except Exception as e:
                        logger.error(f"Error scraping event {event.name}: {e}")
                        continue
                
                # Filter events: only publish new events or future events
                events_to_publish = self.filter_events(scraped_events)
                logger.info(f"After filtering: {len(events_to_publish)} events to publish (of {len(scraped_events)} scraped)")
                
                for i, event in enumerate(events_to_publish, 1):
                    try:
                        logger.debug(f"Publishing event {i}/{len(events_to_publish)}: {event.name}")
                        self.publish_event(event)
                        events_processed += 1
                        
                    except Exception as e:
                        logger.error(f"Error publishing event {event.name}: {e}")
                        continue
            else:
                logger.info("No events found")
            
            # ===========================================
            # Phase 2: Scrape Resources (incremental with duplicate detection)
            # ===========================================
            logger.info("Phase 2: Scraping resources from resource center")
            
            resources = await self.get_resource_links(
                datasource_id, 
                max_resources=max_resources,
                discovery_mode=discovery_mode,
                consecutive_duplicates_limit=consecutive_duplicates_limit
            )
            
            if resources:
                logger.info(f"Found {len(resources)} new resources to process")
                
                # Process resources
                for i, resource in enumerate(resources, 1):
                    try:
                        self.update_heartbeat()
                        self.update_current_processing(resource, f"scraping resource ({i}/{len(resources)})")
                        
                        logger.debug(f"Processing resource {i}/{len(resources)}: {resource.title}")
                        scraped_resource = await self.scrape_resource(resource)
                        
                        self.publish_resource(scraped_resource)
                        resources_processed += 1
                        
                        await asyncio.sleep(scraper_delay)
                        
                    except Exception as e:
                        logger.error(f"Error processing resource {resource.title}: {e}")
                        continue
            else:
                logger.info("No new resources found")

            self.mark_datasource_scraped(datasource_id)
            
            # End batch and signal completion
            total_items = events_processed + resources_processed
            self.end_batch(total_items)
            
            logger.info(f"Scraping completed: {events_processed} events, {resources_processed} resources")
            
        except Exception as e:
            logger.error(f"Error running WFA scraper for {datasource_id}: {e}")
            
            # End batch with error (items sent so far)
            if self.get_current_batch_id():
                self.end_batch(self._batch_items_count)
            
            raise
        finally:
            self.clear_current_processing()