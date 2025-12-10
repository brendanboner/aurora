"""
WFA Causeway Portal Scraper

Scrapes documents from the Wi-Fi Alliance internal Causeway portal.
This portal requires member authentication and doesn't provide an API.

Features:
- Form-based authentication
- HTML parsing for document discovery
- PDF and document download
- Session management

Configuration:
    WFA_CAUSEWAY_USERNAME: Causeway account username/email (env var)
    WFA_CAUSEWAY_PASSWORD: Causeway account password (env var)
    
    Per-datasource config in database (system_configuration table):
    - resource_url: URL path for the working group (e.g., '/wg/WiFi7MTG/document')
    - folders: JSONB array of folder paths to scrape
    - scrape_frequency, max_resources, scraper_delay, etc.
"""

import asyncio
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, urlparse
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone
import logging
import io
from docx import Document
from pptx import Presentation
from openpyxl import load_workbook

from .base import BaseScraper, Resource, Event
from settings import settings

logger = logging.getLogger(__name__)


class WFACausewayScraper(BaseScraper):
    """
    Scraper for Wi-Fi Alliance Causeway internal portal.
    
    Handles:
    - Form-based authentication with session cookies
    - Multiple working groups with hierarchical folder structures
    - Configurable folder selection per working group
    - Document discovery from portal pages
    - PDF and other document downloads
    - Metadata extraction from portal HTML
    
    Configuration:
    Each working group is a separate datasource_id in system_configuration.
    The database configuration includes:
    - resource_url: URL path for the working group (e.g., '/wg/WiFi7MTG/document')
    - folders: JSONB array of folder paths to scrape
    - scrape_frequency, max_resources, scraper_delay, etc.
    
    If folders list is empty or not specified, scrapes entire group.
    """
    
    scraper_name = "wfa_causeway"  # Used for JSON file naming
    
    # Base URL for the Causeway portal (domain only, resource paths come from database)
    BASE_URL = "https://groups.wi-fi.org"
    
    def __init__(self):
        super().__init__()
        
        # Causeway portal base URL
        self.base_url = self.BASE_URL
        
        # Authentication state
        self.is_authenticated = False
        
    async def __aenter__(self):
        """Async context manager entry - authenticate on session start"""
        await super().__aenter__()
        
        # Authenticate when the session is created
        if hasattr(settings, 'wfa_causeway_username') and hasattr(settings, 'wfa_causeway_password'):
            await self.authenticate()
        else:
            logger.error("WFA Causeway credentials not configured!")
            raise ValueError("WFA_CAUSEWAY_USERNAME and WFA_CAUSEWAY_PASSWORD must be set")
        
        return self
    
    async def authenticate(self):
        """
        Authenticate with the WFA Causeway portal.
        
        Complete SAML SSO flow:
        1. Access base URL → redirects to Salesforce login
        2. Submit AJAX login form → returns SAML redirect
        3. Follow SAML redirect → lands on frontdoor.jsp
        4. Access base URL with session cookies → SAML assertion form
        5. Submit SAML form → lands on authenticated portal page
        """
        logger.info("Authenticating with WFA Causeway portal...")
        
        try:
            # Step 1: Access base URL - redirects to login if not authenticated
            async with self.session.get(self.base_url, allow_redirects=True) as response:
                if response.status != 200:
                    raise Exception(f"Failed to access portal: {response.status}")
                
                html = await response.text()
                login_url = str(response.url)
                
                # Check if already authenticated
                if 'logout' in html.lower() or 'sign out' in html.lower():
                    logger.info("Already authenticated")
                    self.is_authenticated = True
                    return
            
            # Step 2: Parse login form
            soup = BeautifulSoup(html, 'html.parser')
            login_form = soup.find('form', {'id': re.compile('j_id')})
            
            if login_form:
                form_id = login_form.get('id')
                form_action_path = login_form.get('action', '/signin/NewLogin')
            else:
                # Fallback: extract form ID from JavaScript
                form_id_match = re.search(r"A4J\.AJAX\.Submit\('([^']+)'", html)
                if not form_id_match:
                    raise Exception("Could not find login form")
                form_id = form_id_match.group(1)
                form_action_path = '/signin/NewLogin'
            
            form_action = urljoin(login_url, form_action_path)
            
            # Get similarity grouping ID from JavaScript (if present)
            similarity_match = re.search(r"'similarityGroupingId'\s*:\s*'([^']+)'", html)
            similarity_id = similarity_match.group(1) if similarity_match else None
            
            # Step 3: Build login payload with all required Salesforce Visualforce fields
            login_data = {
                'AJAXREQUEST': '_viewRoot',
                form_id: form_id,
                'username': settings.wfa_causeway_username,
                'password': settings.wfa_causeway_password,
            }
            
            if similarity_id:
                login_data[similarity_id] = similarity_id
            
            # Add all hidden fields (ViewState, ViewStateVersion, ViewStateMAC, etc.)
            for hidden in soup.find_all('input', {'type': 'hidden'}):
                field_name = hidden.get('name')
                field_value = hidden.get('value')
                if field_name and field_value is not None and field_name not in login_data:
                    login_data[field_name] = field_value
            
            # Step 4: Submit AJAX login form
            headers = {
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/xml, text/xml, */*; q=0.01',
            }
            
            async with self.session.post(form_action, data=login_data, headers=headers, allow_redirects=False) as response:
                response_text = await response.text()
                
                # Check for login errors
                if any(err in response_text.lower() for err in ['invalid credentials', 'incorrect password', 'login failed']):
                    raise Exception("Login failed - invalid credentials")
                
                # Step 5: Follow SAML redirect to frontdoor
                if 'location' not in response.headers:
                    raise Exception("No SAML redirect received after login")
                
                redirect_url = response.headers['location']
                logger.info("Following SAML redirect...")
                
                async with self.session.get(redirect_url, allow_redirects=True) as redirect_response:
                    final_url = str(redirect_response.url)
                    response_text = await redirect_response.text()
                    
                    if redirect_response.status != 200:
                        raise Exception(f"SAML redirect failed: {redirect_response.status}")
                    
                    # Step 6: Should land on frontdoor - now access base URL with session cookies
                    if 'frontdoor.jsp' not in final_url:
                        raise Exception(f"Unexpected URL after SAML redirect: {final_url[:100]}")
                    
                    logger.info("Reached frontdoor - session cookies set")
                    
                    # Step 7: Access base URL which triggers SAML assertion
                    async with self.session.get(self.base_url, allow_redirects=True) as portal_response:
                        final_url = str(portal_response.url)
                        response_text = await portal_response.text()
                        
                        # Step 8: If we get SAML request, submit the auto-post form
                        if 'SAMLRequest' in final_url or 'idp/login' in final_url:
                            logger.info("Submitting SAML assertion...")
                            soup = BeautifulSoup(response_text, 'html.parser')
                            form = soup.find('form')
                            
                            if not form:
                                raise Exception("SAML form not found")
                            
                            form_action = form.get('action')
                            form_data = {inp.get('name'): inp.get('value', '') 
                                       for inp in form.find_all('input') if inp.get('name')}
                            
                            async with self.session.post(form_action, data=form_data, allow_redirects=True) as saml_response:
                                final_url = str(saml_response.url)
                                response_text = await saml_response.text()
                
                # Verify authentication succeeded
                parsed_url = urlparse(final_url)
                host = (parsed_url.hostname or '').lower().strip()
                on_portal = host == 'groups.wi-fi.org'
                path_lower = (parsed_url.path or '').lower()
                not_on_login = 'signin' not in path_lower and 'login' not in path_lower
                
                if not (on_portal and not_on_login):
                    raise Exception(f"Authentication failed - unexpected final URL: {final_url[:100]}")
                
                self.is_authenticated = True
                logger.info(f"Successfully authenticated - landed at: {final_url[:80]}...")
                    
        except Exception as e:
            logger.error(f"WFA Causeway authentication failed: {e}")
            raise

    
    async def get_resource_links(
        self, 
        group_url: str, 
        datasource_id: str, 
        allowed_folders: List[str] = None, 
        max_resources: int = -1,
        last_scraped_at: Optional[datetime] = None,
        discovery_mode: str = "date_based"
    ) -> List[Resource]:
        """
        Discover and return links to documents from a working group's folder structure.
        
        Args:
            group_url: Base URL for the working group's document page
            datasource_id: Identifier for the datasource
            allowed_folders: List of folder paths to scrape (None = all folders)
            max_resources: Maximum number of resources to collect (-1 = unlimited)
            last_scraped_at: For date_based mode, only collect docs newer than this
            discovery_mode: 'date_based' or 'incremental'
            
        Returns:
            List of Resource objects to scrape
        """
        resources = []
        visited_urls = set()
        
        logger.info(f"Discovering documents from: {group_url}")
        logger.info(f"  Discovery mode: {discovery_mode}")
        if last_scraped_at:
            logger.info(f"  Last scraped: {last_scraped_at.isoformat()}")
        if allowed_folders:
            logger.debug(f"Allowed folders: {allowed_folders}")
        
        try:
            await self._scrape_folder_recursive(
                folder_url=group_url,
                current_path="",
                datasource_id=datasource_id,
                allowed_folders=allowed_folders,
                resources=resources,
                visited_urls=visited_urls,
                max_resources=max_resources,
                last_scraped_at=last_scraped_at,
                discovery_mode=discovery_mode
            )
            
            logger.info(f"Discovery complete: found {len(resources)} new documents")
            
        except Exception as e:
            logger.error(f"Error during resource discovery: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        
        return resources
    
    async def _scrape_folder_recursive(
        self,
        folder_url: str,
        current_path: str,
        datasource_id: str,
        allowed_folders: Optional[List[str]],
        resources: List[Resource],
        visited_urls: set,
        max_resources: int,
        last_scraped_at: Optional[datetime] = None,
        discovery_mode: str = "date_based"
    ):
        """
        Recursively scrape folders and collect documents.
        
        For date_based mode:
        - Skip folders where folder_mod_date < last_scraped_at
        - For documents in recent folders, stop when doc_mod_date < last_scraped_at
        - Always recurse into subfolders (they have independent mod dates)
        
        For incremental mode:
        - Check url_exists_in_db() for each document (original behavior)
        """
        if max_resources > 0 and len(resources) >= max_resources:
            return
        
        if folder_url in visited_urls:
            return
        visited_urls.add(folder_url)
        
        logger.debug(f"Scanning folder: {current_path or '(root)'}")
        
        # Update monitoring
        self.update_heartbeat()
        self.update_current_processing(
            Resource(title=f"Scanning folder: {current_path or 'root'}", url=folder_url, category="discovery"),
            "discovering documents"
        )
        
        # Add pageSize to bypass default pagination
        request_url = folder_url
        if '?' in request_url:
            request_url += "&pageSize=500000"
        else:
            request_url += "?pageSize=500000"

        async with self.session.get(request_url) as response:
            if response.status != 200:
                logger.error(f"Failed to fetch folder {current_path}: HTTP {response.status}")
                return
            
            html = await response.text()
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Parse folder page with date-based filtering if in date_based mode
        filter_date = last_scraped_at if discovery_mode == "date_based" else None
        subfolders, documents_with_dates = self._parse_folder_page(
            soup, folder_url, last_scraped_at=filter_date
        )
        
        logger.debug(f"Folder '{current_path or 'root'}': {len(subfolders)} subfolders, {len(documents_with_dates)} documents (after filtering)")
        
        # Process documents based on discovery mode
        if discovery_mode == "date_based":
            # Date-based mode: documents are already filtered by _parse_folder_page
            for doc, doc_mod_date in documents_with_dates:
                if max_resources > 0 and len(resources) >= max_resources:
                    logger.info(f"Reached max_resources limit ({max_resources})")
                    break
                
                doc.category = current_path or "root"
                resources.append(doc)
                logger.debug(f"Added document: {doc.title} (mod: {doc_mod_date})")
        else:
            # Incremental mode: use url_exists_in_db check (original behavior)
            for doc, doc_mod_date in documents_with_dates:
                if max_resources > 0 and len(resources) >= max_resources:
                    logger.info(f"Reached max_resources limit ({max_resources})")
                    break
                
                if self.url_exists_in_db(doc.url):
                    logger.debug(f"Skipping duplicate: {doc.title}")
                    continue
                
                doc.category = current_path or "root"
                resources.append(doc)
                logger.debug(f"Added document: {doc.title}")
        
        # Always recurse into subfolders
        for subfolder_name, subfolder_url in subfolders:
            if max_resources > 0 and len(resources) >= max_resources:
                logger.info(f"Reached max_resources limit ({max_resources})")
                break
            
            subfolder_path = f"{current_path}/{subfolder_name}" if current_path else subfolder_name
            
            # Check if this folder is allowed (case-insensitive)
            if allowed_folders is not None and len(allowed_folders) > 0:
                is_allowed = False
                subfolder_path_lower = subfolder_path.lower()
                for allowed in allowed_folders:
                    allowed_lower = allowed.lower()
                    if allowed_lower.startswith(subfolder_path_lower) or subfolder_path_lower.startswith(allowed_lower):
                        is_allowed = True
                        break
                
                if not is_allowed:
                    continue
            
            # In date_based mode, we could skip subfolders with old mod dates,
            # but we still need to recurse because a subfolder might have newer content
            # than its parent. The check happens at the document level.
            
            # Recursively scrape the subfolder
            await self._scrape_folder_recursive(
                folder_url=subfolder_url,
                current_path=subfolder_path,
                datasource_id=datasource_id,
                allowed_folders=allowed_folders,
                resources=resources,
                visited_urls=visited_urls,
                max_resources=max_resources,
                last_scraped_at=last_scraped_at,
                discovery_mode=discovery_mode
            )
        
        await asyncio.sleep(self.get_scraper_delay(datasource_id))
    
    def _parse_folder_page(
        self, 
        soup: BeautifulSoup, 
        folder_url: str,
        last_scraped_at: Optional[datetime] = None
    ) -> Tuple[List[Tuple[str, str]], List[Tuple[Resource, Optional[datetime]]]]:
        """
        Parse a folder page to extract subfolders and documents with modification dates.
        
        When last_scraped_at is provided (date_based mode):
        - Always returns ALL subfolders (they need to be recursed into)
        - For documents: stops parsing as soon as it hits a document older than last_scraped_at
          (documents are sorted newest-first by the portal)
        - If the folder's first document is already old, returns empty documents list
        
        This optimization avoids parsing hundreds of old documents we don't need.
        
        Args:
            soup: BeautifulSoup object of the folder page
            folder_url: URL of the folder (for building absolute URLs)
            last_scraped_at: If provided, stop parsing documents when hitting one older than this
        
        Returns:
            Tuple of:
            - subfolders: List of (name, url) tuples (always all subfolders)
            - documents: List of (Resource, mod_date) tuples (filtered if last_scraped_at provided)
        """
        subfolders = []
        documents = []
        folder_mod_date = None  # Track newest doc date to check if we should skip all docs
        
        # Find all items wrapped in spans with class "document-name"
        # This includes both folders and documents
        document_name_spans = soup.find_all('span', class_='document-name')

        logger.debug(f"Found {len(document_name_spans)} items while parsing folder page.")
        
        # First pass: separate folders from documents and get folder_mod_date
        # We need to do this because folders and documents are mixed in the HTML
        folder_spans = []
        document_spans = []
        
        for span in document_name_spans:
            link = span.find('a')
            if not link or not link.get('href'):
                continue
            
            if 'folderListLink' in link.get('class', []):
                folder_spans.append(span)
            else:
                document_spans.append(span)
                # Check the first document's date to determine folder_mod_date
                if folder_mod_date is None:
                    item_mod_date = self._extract_item_mod_date(span)
                    if item_mod_date is not None:
                        folder_mod_date = item_mod_date
        
        # Process ALL subfolders (always need to recurse into them)
        for span in folder_spans:
            link = span.find('a')
            href = link.get('href', '')
            item_name = link.get_text(strip=True)
            item_url = urljoin(folder_url, href)
            
            subfolders.append((item_name, item_url))
            logger.debug(f"Found subfolder: {item_name}")
        
        # Check if we should skip all documents in this folder
        if last_scraped_at is not None and folder_mod_date is not None:
            if folder_mod_date < last_scraped_at:
                logger.debug(f"Skipping all documents in folder - newest doc {folder_mod_date} < last_scraped {last_scraped_at}")
                return subfolders, documents  # Empty documents list
        
        # Process documents - with early termination if last_scraped_at provided
        for span in document_spans:
            link = span.find('a')
            href = link.get('href', '')
            item_name = link.get_text(strip=True)
            item_url = urljoin(folder_url, href)
            item_mod_date = self._extract_item_mod_date(span)
            
            # In date_based mode, stop when we hit an old document
            # (documents are sorted newest-first)
            if last_scraped_at is not None and item_mod_date is not None:
                if item_mod_date < last_scraped_at:
                    logger.debug(f"Stopping at old document '{item_name}' - mod date {item_mod_date} < last_scraped {last_scraped_at}")
                    break
            
            resource = Resource(
                title=item_name or self._extract_title_from_url(item_url),
                url=item_url,
                category='document',
                datasource_id='wfa_causeway'
            )
            documents.append((resource, item_mod_date))
            logger.debug(f"Found document: {item_name} (mod: {item_mod_date})")
        
        return subfolders, documents
    
    def _extract_item_mod_date(self, item_span) -> Optional[datetime]:
        """
        Extract the modification date for a folder or document item.
        
        The date is in the next <td> sibling after the <td> containing the item span.
        HTML structure:
        <td>...<span class="document-name">...</span>...</td>
        <td><strong>Dec 4, 2025</strong>...</td>
        
        Args:
            item_span: BeautifulSoup element for the item's span (class="document-name")
            
        Returns:
            datetime object or None if date not found/parseable
        """
        try:
            # Navigate: span -> parent td -> next sibling td -> strong (contains date)
            parent_td = item_span.find_parent('td')
            if not parent_td:
                return None
            
            next_td = parent_td.find_next_sibling('td')
            if not next_td:
                return None
            
            # The date is in a <strong> tag within the td
            strong_elem = next_td.find('strong')
            if strong_elem:
                date_text = strong_elem.get_text(strip=True)
                return self._parse_mod_date(date_text)
            
            # Fallback: try getting text directly from td
            date_text = next_td.get_text(strip=True)
            if date_text:
                # Extract just the date part (before any line breaks or parenthetical info)
                date_text = date_text.split('\n')[0].split('(')[0].strip()
                return self._parse_mod_date(date_text)
            
            return None
            
        except Exception as e:
            logger.debug(f"Could not extract mod date: {e}")
            return None
    
    def _parse_mod_date(self, date_text: str) -> Optional[datetime]:
        """
        Parse a modification date string into a datetime object.
        
        Handles common formats:
        - "12/8/25" (MM/DD/YY)
        - "12/8/2025" (MM/DD/YYYY)
        - "Dec 8, 2025"
        
        Note: Since the portal only shows date (not time), we set the time to 
        end of day (23:59:59) to ensure documents posted the same day as the 
        last scrape are included. This handles the case where a document is
        posted later in the day after our last scrape.
        
        Args:
            date_text: Date string to parse
            
        Returns:
            datetime object (timezone-aware UTC, set to end of day) or None if parsing fails
        """
        if not date_text:
            return None
        
        try:
            # Try MM/DD/YY format
            match = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})$', date_text.strip())
            if match:
                month = int(match.group(1))
                day = int(match.group(2))
                year = int(match.group(3))
                if year < 100:
                    year += 2000
                # Set to end of day to include same-day documents
                return datetime(year, month, day, 23, 59, 59, tzinfo=timezone.utc)
            
            # Try other formats with dateutil
            from dateutil import parser as date_parser
            parsed = date_parser.parse(date_text)
            # Set to end of day and ensure timezone-aware
            parsed = parsed.replace(hour=23, minute=59, second=59)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
            
        except Exception as e:
            logger.debug(f"Could not parse date '{date_text}': {e}")
            return None
    
    def _extract_title_from_url(self, url: str) -> str:
        """Extract a reasonable title from a URL when no title is available."""
        # Get filename from URL
        parsed = urlparse(url)
        filename = parsed.path.split('/')[-1]
        
        # Remove extension and clean up
        title = re.sub(r'\.[^.]+$', '', filename)  # Remove extension
        title = title.replace('_', ' ').replace('-', ' ')  # Replace separators
        title = re.sub(r'\s+', ' ', title).strip()  # Clean whitespace
        
        return title or 'Untitled Document'
    
    def _extract_revision_date(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract the most recent revision date from the document revisions table.
        
        The revision table shows document history with dates like "10/24/24, 11:07 AM".
        The first row with "(Active)" is the most recent revision.
        
        Args:
            soup: BeautifulSoup object of the document detail page
            
        Returns:
            ISO format date string (YYYY-MM-DD) or None if not found
        """
        try:
            # Find revision links - they have class 'download_redirect' and contain dates
            # The first one in the table is the most recent (Active) revision
            revision_links = soup.find_all('a', class_='download_redirect')
            
            for link in revision_links:
                link_text = link.get_text(strip=True)
                
                # Parse date format: "10/24/24, 11:07 AM" or "12/2/25, 3:45 PM"
                date_match = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2}),?\s*\d{1,2}:\d{2}\s*(?:AM|PM)?', link_text, re.I)
                if date_match:
                    month = int(date_match.group(1))
                    day = int(date_match.group(2))
                    year_short = int(date_match.group(3))
                    
                    # Convert 2-digit year to 4-digit (assume 2000s)
                    year = 2000 + year_short if year_short < 100 else year_short
                    
                    # Return ISO format date
                    return f"{year:04d}-{month:02d}-{day:02d}"
            
            logger.debug("No revision date found in document page")
            return None
            
        except Exception as e:
            logger.warning(f"Error extracting revision date: {e}")
            return None
    
    async def scrape_resource(self, resource: Resource) -> Resource:
        """
        Scrape content from an individual Causeway portal document.
        
        Handles:
        - Document detail pages with download/preview buttons
        - PDF downloads and text extraction
        - HTML pages with embedded content
        - Office documents (when possible)
        - Extracting publish date from revision history
        - Skipping unchanged documents (revision date <= stored publish_date)
        
        Args:
            resource: Resource object with URL to scrape
            
        Returns:
            Resource object with content populated, or resource with content=None
            if the document hasn't changed since last scrape
        """
        logger.info(f"Scraping resource: {resource.title} -> {resource.url}")
        
        try:
            # Update monitoring
            self.update_current_processing(resource, "accessing document page")
            
            # Make authenticated request to get content
            async with self.session.get(resource.url) as response:
                
                if response.status != 200:
                    logger.error(f"Failed to access resource: HTTP {response.status}")
                    return resource
                
                content_type = response.headers.get('Content-Type', '').lower()
                
                if 'text/html' in content_type:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Extract publish date from revision table (most recent revision)
                    publish_date = self._extract_revision_date(soup)
                    if publish_date:
                        resource.publish_date = publish_date
                        logger.debug(f"Extracted publish date: {publish_date}")
                        
                        # Check if document has been updated since we last scraped it
                        # This avoids re-processing unchanged documents
                        if not self.is_resource_updated(resource.url, publish_date):
                            logger.info(f"Skipping unchanged document: {resource.title} (revision: {publish_date})")
                            resource.content = None  # Signal to caller not to publish
                            self.clear_current_processing()
                            return resource
                    
                    # Look for download button/link on document detail page
                    download_url = None
                    
                    # Try data-direct-download attribute first
                    direct_download = soup.find('a', attrs={'data-direct-download': True})
                    if direct_download:
                        download_url = direct_download.get('data-direct-download')
                    
                    # Try download_redirect class
                    if not download_url:
                        download_redirect = soup.find('a', class_='download_redirect')
                        if download_redirect:
                            download_url = urljoin(resource.url, download_redirect.get('href'))
                    
                    # Fallback: find by text "Download"
                    if not download_url:
                        download_candidates = soup.find_all('a', href=True, string=re.compile(r'^\s*Download\s*$', re.I))
                        if download_candidates:
                            download_url = urljoin(resource.url, download_candidates[0].get('href'))
                    
                    if download_url:
                        logger.debug(f"Downloading from: {download_url}")
                        self.update_current_processing(resource, "downloading document")
                        
                        async with self.session.get(download_url) as doc_response:
                            if doc_response.status != 200:
                                logger.error(f"Failed to download: HTTP {doc_response.status}")
                                return resource
                            
                            doc_content_type = doc_response.headers.get('Content-Type', '').lower()
                            resource.content = await self._extract_content(doc_response, doc_content_type)
                    else:
                        logger.warning(f"No download link found on document page: {resource.url}")
                
                else:
                    # Non-HTML response - unexpected for Causeway
                    logger.warning(f"Unexpected content type for document page: {content_type}")
                
                if resource.content:
                    logger.debug(f"Extracted {len(resource.content)} characters")
                
                if not resource.content or len(resource.content.strip()) < 50:
                    logger.warning(f"Minimal content extracted ({len(resource.content or '')} chars)")
                    
        except Exception as e:
            logger.error(f"Error scraping resource {resource.url}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        
        # Clear monitoring status
        self.clear_current_processing()
        
        return resource
    
    async def _extract_content(self, response, content_type: str) -> str:
        """Extract content from a response based on content type."""
        if 'application/pdf' in content_type:
            return self.extract_pdf_text_from_bytes(await response.read())
        elif 'wordprocessingml' in content_type:
            # .docx format (Office Open XML)
            return self._extract_docx_text(await response.read())
        elif 'application/msword' in content_type:
            # Old .doc format - python-docx can't handle these
            return "[Legacy .doc format - text extraction not supported. Only .docx files can be processed.]"
        elif 'application/vnd.ms-powerpoint' in content_type or 'presentationml' in content_type:
            return self._extract_pptx_text(await response.read())
        elif 'application/vnd.ms-excel' in content_type or 'spreadsheetml' in content_type:
            return self._extract_xlsx_text(await response.read())
        elif 'text/html' in content_type:
            html = await response.text()
            return self._extract_html_text(BeautifulSoup(html, 'html.parser'))
        else:
            return await response.text()
    
    def _extract_html_text(self, soup: BeautifulSoup) -> str:
        """Extract text content from HTML, removing scripts and navigation."""
        for element in soup(['script', 'style', 'nav', 'header', 'footer', 'iframe']):
            element.decompose()
        
        content_elem = soup.find(['article', 'main', 'div'], class_=re.compile('content|body|document|main', re.I))
        if content_elem:
            return content_elem.get_text(strip=True, separator='\n')
        
        body = soup.find('body')
        if body:
            return body.get_text(strip=True, separator='\n')
        
        return soup.get_text(strip=True, separator='\n')
    
    def _extract_docx_text(self, docx_bytes: bytes) -> str:
        """Extract text content from Word document bytes (.docx format)."""
        text_parts = []
        
        try:
            doc = Document(io.BytesIO(docx_bytes))
            
            for para in doc.paragraphs:
                if para.text.strip():
                    text_parts.append(para.text)
            
            for table in doc.tables:
                for row in table.rows:
                    row_text = ' | '.join(cell.text.strip() for cell in row.cells)
                    if row_text.strip():
                        text_parts.append(row_text)
            
            return '\n\n'.join(text_parts) or "[Word document appears to be empty or contains only images]"
            
        except Exception as e:
            error_msg = str(e)
            if 'officeDocument' in error_msg:
                # This usually means it's not a valid .docx or is an old .doc file
                logger.warning(f"Word document extraction failed - may be old .doc format or corrupted: {e}")
                return "[Word document could not be read - may be legacy .doc format, corrupted, or password-protected]"
            else:
                logger.error(f"Error extracting Word document text: {e}")
                return "[Word document text extraction failed]"
    
    def _extract_pptx_text(self, pptx_bytes: bytes) -> str:
        """Extract text content from PowerPoint presentation bytes (.pptx format)."""
        text_parts = []
        
        try:
            prs = Presentation(io.BytesIO(pptx_bytes))
            
            for i, slide in enumerate(prs.slides, 1):
                slide_text = []
                
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        slide_text.append(shape.text.strip())
                    
                    if shape.shape_type == 19:  # TABLE
                        try:
                            for row in shape.table.rows:
                                row_text = ' | '.join(cell.text.strip() for cell in row.cells)
                                if row_text.strip():
                                    slide_text.append(row_text)
                        except Exception as e:
                            logger.debug(f"Failed to extract table from slide {i}: {e}")
                
                if slide_text:
                    text_parts.append(f"--- Slide {i} ---\n" + '\n'.join(slide_text))
            
            return '\n\n'.join(text_parts) or "[PowerPoint appears to be empty or contains only images]"
            
        except Exception as e:
            logger.error(f"Error extracting PowerPoint text: {e}")
            return "[PowerPoint text extraction failed]"
    
    def _extract_xlsx_text(self, xlsx_bytes: bytes) -> str:
        """Extract text content from Excel spreadsheet bytes (.xlsx format)."""
        text_parts = []
        
        try:
            wb = load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
            
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                if ws.max_row == 0:
                    continue
                
                sheet_text = [f"--- Sheet: {sheet_name} ---"]
                
                for row in ws.iter_rows(values_only=True):
                    row_values = [str(cell) if cell is not None else '' for cell in row]
                    if any(val.strip() for val in row_values):
                        sheet_text.append(' | '.join(row_values))
                
                if len(sheet_text) > 1:
                    text_parts.append('\n'.join(sheet_text))
            
            return '\n\n'.join(text_parts) or "[Excel spreadsheet appears to be empty]"
            
        except Exception as e:
            logger.error(f"Error extracting Excel text: {e}")
            return "[Excel text extraction failed - file may be corrupted or in old .xls format]"
    
    async def scrape_calendar(
        self, 
        group_url: str, 
        datasource_id: str,
        last_scraped_at: Optional[datetime] = None,
        max_events: int = -1
    ) -> List[str]:
        """
        Scrape calendar pages to discover event links.
        
        Works backwards from 6 months ahead through history:
        - Initial scrape (last_scraped_at=None): Go back to January 2015
        - Subsequent scrapes: Stop when hitting a past event
        
        Args:
            group_url: Base document URL for the working group
            datasource_id: Datasource ID for tracking
            last_scraped_at: Timestamp of last scrape (None = initial scrape)
            max_events: Maximum number of events to collect (-1 = unlimited)
            
        Returns:
            List of event page URLs to scrape
        """
        from datetime import datetime
        from dateutil.relativedelta import relativedelta
        
        now = datetime.now()
        today = now.date()
        
        # Start from 6 months ahead and work backwards
        # This captures far-future events while still being quick if empty
        start_date = now + relativedelta(months=6)
        start_year = start_date.year
        start_month = start_date.month
        
        # Hard stop: January 2015
        MIN_YEAR = 2015
        MIN_MONTH = 1
        
        base_calendar_url = group_url.replace('/document', '/calendar')
        
        event_urls = []
        seen_urls = set()
        is_initial_scrape = last_scraped_at is None
        
        logger.info(f"Scraping calendar backwards from {start_year}/{start_month} (6 months ahead)")
        logger.info(f"  Mode: {'initial scrape (back to Jan 2015)' if is_initial_scrape else 'incremental (until past event)'}")
        if max_events >= 0:
            logger.info(f"  Max events limit: {max_events}")
        
        # Extract working group name from URL for matching event links
        wg_match = re.search(r'/wg/([^/]+)/', group_url)
        if not wg_match:
            logger.error(f"Could not extract working group from URL: {group_url}")
            return event_urls
        
        working_group = wg_match.group(1)
        # Pattern captures the date from the URL: /wg/{group}/calendar/event/{id}/{YYYY-MM-DD}
        event_link_pattern = re.compile(rf'/wg/{working_group}/calendar/event/(\d+)/(\d{{4}}-\d{{2}}-\d{{2}})')
        
        try:
            self.update_heartbeat()
            self.update_current_processing(
                Event(name="Fetching calendar", event_type="meeting", start_date="", 
                      datasource_id=datasource_id),
                "loading calendar pages"
            )
            
            current_year = start_year
            current_month = start_month
            should_stop = False
            
            while not should_stop:
                # Check if we've hit the max events limit
                if max_events >= 0 and len(event_urls) >= max_events:
                    logger.info(f"Reached max events limit ({max_events}), stopping calendar scrape")
                    break
                
                # Check if we've gone past the hard stop (January 2015)
                if current_year < MIN_YEAR or (current_year == MIN_YEAR and current_month < MIN_MONTH):
                    logger.info(f"Reached hard stop: January {MIN_YEAR}")
                    break
                
                page_url = f"{base_calendar_url}/month/{current_year}/{current_month}"
                logger.debug(f"Fetching calendar page: {page_url}")
                
                async with self.session.get(page_url) as response:
                    if response.status != 200:
                        logger.warning(f"Failed to fetch calendar: HTTP {response.status}")
                        # Move to previous month and continue
                        if current_month == 1:
                            current_year -= 1
                            current_month = 12
                        else:
                            current_month -= 1
                        continue
                    
                    html = await response.text()
                
                page_soup = BeautifulSoup(html, 'html.parser')
                
                # Find all anchor tags with href matching the event pattern
                all_links = page_soup.find_all('a', href=True)
                page_event_count = 0
                found_past_event = False
                
                for link in all_links:
                    # Check max_events limit before adding more
                    if max_events >= 0 and len(event_urls) >= max_events:
                        break
                    
                    href = link.get('href', '')
                    match = event_link_pattern.search(href)
                    if match:
                        event_id = match.group(1)
                        event_date_str = match.group(2)
                        
                        # Parse the event date from URL
                        try:
                            event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
                        except ValueError:
                            logger.warning(f"Could not parse event date from URL: {href}")
                            continue
                        
                        # For non-initial scrapes, check if we hit a past event
                        if not is_initial_scrape and event_date < today:
                            found_past_event = True
                            logger.debug(f"Found past event ({event_date_str}), will stop after this month")
                        
                        # Build full URL
                        full_url = urljoin('https://groups.wi-fi.org', href)
                        
                        # Avoid duplicates
                        if full_url not in seen_urls:
                            seen_urls.add(full_url)
                            event_urls.append(full_url)
                            page_event_count += 1
                            event_name = link.get_text(strip=True)
                            logger.debug(f"Found event link: {event_name} ({event_date_str}) -> {full_url}")
                
                logger.debug(f"Found {page_event_count} events on {current_year}/{current_month}")
                
                # Stopping conditions for non-initial scrapes
                if not is_initial_scrape:
                    if found_past_event:
                        logger.info(f"Found past event on {current_year}/{current_month}, stopping backward traversal")
                        should_stop = True
                    elif page_event_count == 0:
                        # No events on this page - check if the month itself is in the past
                        # A month is "in the past" if we're past its last day
                        from calendar import monthrange
                        _, last_day = monthrange(current_year, current_month)
                        month_end = datetime(current_year, current_month, last_day).date()
                        if month_end < today:
                            logger.info(f"Empty past month {current_year}/{current_month}, stopping backward traversal")
                            should_stop = True
                
                # Move to previous month
                if current_month == 1:
                    current_year -= 1
                    current_month = 12
                else:
                    current_month -= 1
                
                self.update_heartbeat()
            
            # Warn if no events found at all (potential selector/URL issue)
            if len(event_urls) == 0:
                logger.warning(
                    f"No events found across all calendar pages for {working_group}. "
                    f"This may indicate an issue with the calendar URL or event link selectors."
                )
            else:
                logger.info(f"Discovered {len(event_urls)} events from calendar")
            
        except Exception as e:
            logger.error(f"Error scraping calendar: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        
        return event_urls
    
    async def scrape_event_page(self, event_url: str, datasource_id: str) -> Optional[Event]:
        """Scrape an individual event page to extract event details."""
        logger.debug(f"Scraping event page: {event_url}")
        
        try:
            self.update_heartbeat()
            
            async with self.session.get(event_url) as response:
                if response.status != 200:
                    logger.warning(f"Failed to fetch event page: HTTP {response.status}")
                    return None
                
                html = await response.text()
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # Default values
            event_name = ""
            event_type = "meeting"
            start_date = ""
            end_date = None
            location = ""
            timezone = None
            description = ""
            status = "scheduled"
            
            # Extract event name from heading (h2 with class inline-content inside div.bucket_content)
            bucket_content = soup.find('div', class_='bucket_content')
            if bucket_content:
                title_elem = bucket_content.find('h2', class_='inline-block')
                if title_elem:
                    event_name = title_elem.get_text(strip=True)
            
            # Extract date/time from table row
            datetime_th = soup.find('th', string=re.compile(r'Date/Time', re.I))
            if datetime_th:
                datetime_td = datetime_th.find_next_sibling('td')
                if datetime_td:
                    datetime_text = datetime_td.get_text(separator=' ', strip=True)
                    
                    # Parse: "Tuesday, December 23, 2025 9:00 AM - 10:00 AM EST"
                    date_match = re.search(r'(\w+,\s+\w+\s+\d{1,2},\s+\d{4})', datetime_text)
                    if date_match:
                        date_str = date_match.group(1)
                        time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM))', datetime_text, re.I)
                        tz_match = re.search(r'\b([A-Z]{2,4})\s*$', datetime_text)
                        if tz_match:
                            timezone = tz_match.group(1)
                        
                        try:
                            from dateutil import parser as date_parser
                            if time_match:
                                full_datetime = f"{date_str} {time_match.group(1)}"
                                parsed = date_parser.parse(full_datetime)
                                start_date = parsed.strftime('%Y-%m-%dT%H:%M:%S')
                            else:
                                parsed = date_parser.parse(date_str)
                                start_date = parsed.strftime('%Y-%m-%d')
                        except Exception as e:
                            logger.debug(f"Failed to parse date: {e}")
                    
                    # Extract end time if present (after the "-")
                    end_time_match = re.search(r'-\s*(\d{1,2}:\d{2}\s*(?:AM|PM))', datetime_text, re.I)
                    if end_time_match and date_match:
                        try:
                            from dateutil import parser as date_parser
                            end_datetime = f"{date_match.group(1)} {end_time_match.group(1)}"
                            parsed = date_parser.parse(end_datetime)
                            end_date = parsed.strftime('%Y-%m-%dT%H:%M:%S')
                        except Exception as e:
                            logger.debug(f"Failed to parse end time: {e}")
            
            # Fallback: Extract date from URL if not found in page
            if not start_date:
                date_match = re.search(r'/calendar/event/\d+/(\d{4}-\d{2}-\d{2})', event_url)
                if date_match:
                    start_date = date_match.group(1)
            
            # Extract location
            location_th = soup.find('th', string=re.compile(r'^Location$', re.I))
            if location_th:
                location_td = location_th.find_next_sibling('td')
                if location_td:
                    location = location_td.get_text(strip=True)
            
            # Extract description
            desc_th = soup.find('th', string=re.compile(r'^Description$', re.I))
            if desc_th:
                desc_td = desc_th.find_next_sibling('td')
                if desc_td:
                    description = desc_td.get_text(separator='\n', strip=True)
            
            # Check for cancelled status
            cancelled_div = soup.find('div', class_='flash-warning')
            if cancelled_div and 'canceled' in cancelled_div.get_text().lower():
                status = "cancelled"
            
            if not event_name:
                logger.warning(f"Could not extract event name from {event_url}")
                return None
            
            if not start_date:
                logger.warning(f"Could not extract start date from {event_url}")
                return None
            
            event = Event(
                name=event_name,
                event_type=event_type,
                start_date=start_date,
                end_date=end_date,
                location=location,
                timezone=timezone,
                description=description,
                url=event_url,
                status=status,
                datasource_id=datasource_id
            )
            
            logger.debug(f"Scraped event: {event_name} ({start_date})")
            return event
            
        except Exception as e:
            logger.error(f"Error scraping event page {event_url}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None
    
    async def run_scraper(self, datasource_config: Dict[str, Any] = None):
        """
        Scrape a single WFA Causeway working group.
        
        Args:
            datasource_config: Configuration dict from database containing:
                - datasource_id: Unique identifier (e.g., 'wfa_causeway_wifi7mtg')
                - name: Display name (e.g., 'WFA Causeway - Wi-Fi 7 MTG')
                - resource_url: URL path for this group (e.g., '/wg/WiFi7MTG/document')
                - folders: List of folder names to scrape (or None for all)
                - max_resources, scraper_delay, etc.
        """
        if datasource_config is None:
            logger.error("WFACausewayScraper requires a datasource_config")
            return
        
        datasource_id = datasource_config.get('datasource_id')
        datasource_name = datasource_config.get('name', datasource_id)
        resource_url = datasource_config.get('resource_url')
        
        if not resource_url:
            logger.error(f"No resource_url configured for {datasource_id}")
            return
        
        # Build full group URL from base_url and resource_url
        group_url = f"{self.base_url}{resource_url}"
        
        logger.info(f"Starting WFA Causeway scraper for: {datasource_name}")
        logger.info(f"  Group URL: {group_url}")
        
        # Start ingestion batch for tracking
        batch_id = self.start_batch(datasource_id)
        logger.info(f"  Batch ID: {batch_id}")
        
        try:
            # Extract folder configuration from config
            allowed_folders = datasource_config.get('folders', None)
            
            # Ensure folders is a list if it's not None
            if allowed_folders is not None and not isinstance(allowed_folders, list):
                logger.warning(f"Folders is not a list, converting from {type(allowed_folders)}")
                allowed_folders = None
            
            # Get max resources limit and scraper delay from datasource config
            max_resources = datasource_config.get('max_resources', 100)
            scraper_delay = datasource_config.get('scraper_delay', 1.0)
            
            # Get discovery mode and last_scraped_at for efficient scraping
            discovery_mode = datasource_config.get('discovery_mode', 'incremental')
            last_scraped_at = datasource_config.get('last_scraped_at')
            is_full_refresh = datasource_config.get('is_full_refresh', False)
            
            # If full refresh is requested, ignore last_scraped_at
            if is_full_refresh:
                logger.info("  FULL REFRESH mode - ignoring last_scraped_at")
                last_scraped_at = None
            
            logger.info(f"  Config: max_resources={max_resources}, delay={scraper_delay}s, folders={allowed_folders or 'all'}")
            logger.info(f"  Discovery: mode={discovery_mode}, last_scraped={last_scraped_at}, full_refresh={is_full_refresh}")
            
            # Get event URLs from calendar page (pass last_scraped_at for incremental vs initial behavior)
            # Use max_resources to limit events as well (helpful for testing)
            event_urls = await self.scrape_calendar(
                group_url=group_url,
                datasource_id=datasource_id,
                last_scraped_at=last_scraped_at,
                max_events=max_resources
            )
            
            events_processed = 0
            
            if event_urls:
                logger.info(f"Discovered {len(event_urls)} event links")
                
                # Scrape all events first
                scraped_events = []
                for i, event_url in enumerate(event_urls, 1):
                    try:
                        logger.info(f"Scraping event {i}/{len(event_urls)}: {event_url}")
                        
                        event = await self.scrape_event_page(event_url, datasource_id)
                        
                        if event:
                            scraped_events.append(event)
                        else:
                            logger.warning(f"Failed to scrape event details from: {event_url}")
                        
                        await asyncio.sleep(scraper_delay)
                        
                    except Exception as e:
                        logger.error(f"Error scraping event {event_url}: {e}")
                        continue
                
                # Filter events: only publish new events or future events
                events_to_publish = self.filter_events(scraped_events)
                logger.info(f"After filtering: {len(events_to_publish)} events to publish (of {len(scraped_events)} scraped)")
                
                for i, event in enumerate(events_to_publish, 1):
                    try:
                        logger.info(f"Publishing event {i}/{len(events_to_publish)}: {event.name}")
                        self.publish_event(event)
                        events_processed += 1
                        
                    except Exception as e:
                        logger.error(f"Error publishing event {event.name}: {e}")
                        continue
            else:
                logger.info("No calendar event links found")
            
            # Discover documents from this working group
            resources = await self.get_resource_links(
                group_url=group_url,
                datasource_id=datasource_id,
                allowed_folders=allowed_folders,
                max_resources=max_resources,
                discovery_mode=discovery_mode,
                last_scraped_at=last_scraped_at
            )
            
            resources_processed = 0
            resources_skipped = 0
            
            if resources:
                logger.info(f"Processing {len(resources)} documents")
                
                for i, resource in enumerate(resources, 1):
                    try:
                        self.update_heartbeat()
                        resource.datasource_id = datasource_id
                        
                        logger.info(f"Processing resource {i}/{len(resources)}: {resource.title}")
                        scraped_resource = await self.scrape_resource(resource)
                        
                        if scraped_resource.content is None:
                            # Document unchanged (revision date check)
                            resources_skipped += 1
                        elif len(scraped_resource.content.strip()) > 50:
                            self.publish_resource(scraped_resource)
                            resources_processed += 1
                        else:
                            logger.warning(f"Insufficient content: {resource.title}")
                        
                    except Exception as e:
                        logger.error(f"Error processing resource {resource.title}: {e}")
                        continue
                    
                    await asyncio.sleep(scraper_delay)
            
            # Update the last_scraped_at timestamp for this working group
            self.mark_datasource_scraped(datasource_id)
            
            # End batch and signal completion
            total_items = events_processed + resources_processed
            self.end_batch(total_items)
            
            logger.info(f"Completed {datasource_name}: {events_processed} events, {resources_processed} resources published, {resources_skipped} unchanged")
            
        except Exception as e:
            logger.error(f"Error running WFA Causeway scraper for {datasource_name}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # End batch with error (items sent so far)
            if self.get_current_batch_id():
                self.end_batch(self._batch_items_count)
            
            raise
        finally:
            self.clear_current_processing()
