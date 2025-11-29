import asyncio
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
from typing import List, Optional
import logging
import json
import io
import pypdf

from .base import BaseScraper, Resource
from settings import settings

class WFAScraper(BaseScraper):
    DOCUMENT_EXTENSIONS = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']
    scraper_name = "wfa"  # Used for JSON file naming
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://www.wi-fi.org"
        self.resource_center_url = f"{self.base_url}/resource-center"

    def is_document_url(self, url: str) -> bool:
        """Check if URL points to a document file"""
        return any(ext in url.lower() for ext in self.DOCUMENT_EXTENSIONS)



    def _extract_resources_from_soup(self, soup: BeautifulSoup) -> List[Resource]:
        """Helper function to extract resources from a BeautifulSoup object"""
        resources = []
        
        # Look for card elements
        card_elements = soup.find_all('div', class_=lambda x: x and 'card' in str(x).lower())
        
        for card in card_elements:
            # Find the first link with an href
            link = next((a for a in card.find_all('a') if a.get('href')), None)
            if not link:
                continue
                
            url = urljoin(self.base_url, link['href'])
            
            # Extract title from h5 element within the card
            title = None
            title_element = card.find('h5')
            if title_element:
                extracted_title = title_element.get_text(strip=True)
                # Only use the title if it's not truncated (doesn't end with ..)
                if not extracted_title.endswith('..'):
                    title = extracted_title
            
            # Extract category from span element with class "resources-type"
            category_element = card.find('span', class_='resources-type')
            category = category_element.get_text(strip=True).lower() if category_element else ''
            
            resources.append(Resource(
                title=title or 'Title to be extracted',
                url=url,
                category=category,
                datasource_id='wfa_resource_page'
            ))
        
        return resources
    
    async def get_resource_links(self, max_resources: int = -1) -> List[Resource]:
        """
        Extract resource links from the resource center, collecting across pages as needed.
        Resolves redirects and checks for duplicates to ensure we collect only new resources.
        
        Args:
            max_resources: Maximum number of NEW resources to collect (-1 = unlimited/all pages)
        
        Returns:
            List of Resource objects with resolved URLs that don't exist in the database
        """
        new_resources = []
        page = 0
        total_found = 0
        duplicates_skipped = 0
        
        while True:
            page_url = f"{self.resource_center_url}?page={page}" if page > 0 else self.resource_center_url
            logging.info(f"Scraping page {page + 1}: {page_url}")
            
            # Update monitoring with current page discovery progress
            self.update_heartbeat()
            self.update_current_processing(
                Resource(title="Fetching resource list", url=page_url, category="discovery"),
                f"loading page {page + 1}"
            )
            
            async with self.session.get(page_url) as response:
                html = await response.text()
            
            soup = BeautifulSoup(html, 'html.parser')
            page_resources = self._extract_resources_from_soup(soup)
            
            # If no resources found on this page, we've reached the end
            if not page_resources:
                logging.info(f"No resources found on page {page + 1}, stopping pagination")
                break
            
            total_found += len(page_resources)
            logging.info(f"Found {len(page_resources)} resources on page {page + 1} (total found: {total_found})")
            
            # Process each resource: resolve redirects and check for duplicates
            for resource in page_resources:
                # Check if we've already collected enough new resources
                if max_resources >= 0 and len(new_resources) >= max_resources:
                    logging.info(f"Reached max_resources limit of {max_resources} new resources")
                    break
                
                try:
                    logging.info(f"Processing resource: {resource.title} -> {resource.url}")
                    # Resolve the URL to its final destination
                    self.update_heartbeat()
                    final_url = await self.follow_redirect_chain(resource.url)
                    
                    # Check if the final URL already exists in the database
                    if self.url_exists_in_db(final_url):
                        duplicates_skipped += 1
                        logging.info(f"Skipping duplicate URL (after redirect): {final_url}")
                        continue
                    
                    # This is a new resource - update with final URL and add to list
                    resource.url = final_url
                    new_resources.append(resource)
                    logging.info(f"Added new resource: {resource.title} -> {final_url}")
                    
                except Exception as e:
                    logging.error(f"Error processing resource {resource.url}: {e}")
                    # Skip this resource on error
                    continue
            
            # Check if we've reached the max_resources limit
            if max_resources >= 0 and len(new_resources) >= max_resources:
                logging.info(f"Collected {len(new_resources)} new resources, stopping pagination")
                break
            
            # Be respectful - add delay between page requests
            await asyncio.sleep(settings.scraper_delay)
            page += 1
        
        logging.info(f"Resource collection complete: {total_found} found, {duplicates_skipped} duplicates skipped, {len(new_resources)} new resources to scrape")
        return new_resources
    
    async def scrape_resource(self, resource: Resource) -> Resource:
        """
        Scrape a resource's content. URL is already resolved to final destination.
        
        Note: The URL in the resource has already been resolved through the redirect chain
        by get_resource_links(), so we don't need to follow redirects again.
        """
        try:
            # Update status
            self.update_heartbeat()
            self.update_current_processing(resource, "extracting content")
            
            # Determine content type and process accordingly
            # Note: resource.url is already the final URL after redirect resolution
            if self.is_document_url(resource.url):
                # It's a document - extract PDF text
                logging.debug(f"Extracting document from URL: {resource.url}")
                self.update_heartbeat()
                self.update_current_processing(resource, "extracting PDF content")
                pdf_text = await self.extract_pdf_text(resource.url)
                logging.debug(f"Extracted PDF text length: {len(pdf_text) if pdf_text else 0}")
                resource.content = pdf_text if pdf_text else "PDF document - text extraction failed"
            else:
                logging.debug(f"Extracting HTML content from URL: {resource.url}")
                self.update_heartbeat()
                self.update_current_processing(resource, "extracting HTML content")
                # It's an HTML page - extract content
                async with self.session.get(resource.url) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        await self.extract_html_content(resource, soup)
                    else:
                        resource.content = f"Error: HTTP {response.status}"
                
        except Exception as e:
            logging.error(f"Error scraping {resource.url}: {e}")
            resource.content = f"Error: {str(e)}"

        return resource

    
    async def follow_redirect_chain(self, url: str, max_redirects: int = None) -> str:
        """Follow server redirects, then check for client-side redirects"""
        if max_redirects is None:
            max_redirects = settings.scraper_max_redirects
        
        current_url = url
        redirect_count = 0
        
        # Follow server redirects first
        while redirect_count < max_redirects:
            logging.debug(f"Following redirect chain: {current_url}")
            
            async with self.session.get(current_url, allow_redirects=False) as response:
                # Handle server redirects
                if response.status in [301, 302, 303, 307, 308]:
                    location = response.headers.get('Location')
                    if location:
                        current_url = urljoin(current_url, location)
                        redirect_count += 1
                        logging.debug(f"Server redirect to: {current_url}")
                        continue
                
                # No more server redirects - break and check for client-side
                break
        
        if redirect_count >= max_redirects:
            logging.warning(f"Max redirects ({max_redirects}) reached for URL: {current_url}")
            return current_url
        
        # Check for client-side redirects (this handles the final URL determination)
        final_url = await self.check_for_client_side_redirect_url(current_url)
        return final_url
    
    
    async def check_for_client_side_redirect_url(self, url: str) -> str:
        """Check for client-side redirects - returns redirect URL or original URL if end of chain"""
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    content_type = response.headers.get('content-type', '').lower()
                    
                    if 'text/html' in content_type:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Check for inline script with data-drupal-selector attribute
                        drupal_scripts = soup.find_all('script', attrs={'data-drupal-selector': True})
                        if drupal_scripts:
                            logging.debug(f"Found {len(drupal_scripts)} Drupal scripts, checking for filePath...")
                            
                            for i, script in enumerate(drupal_scripts):
                                if script.string:
                                    script_content = script.string.strip()
                                    
                                    # Look for filePath in the JavaScript object
                                    filepath_pattern = r'["\']?filePath["\']?\s*:\s*["\']([^"\']+)["\']'
                                    matches = re.findall(filepath_pattern, script_content, re.IGNORECASE)
                                    
                                    if matches:
                                        for match in matches:
                                            # Clean up escaped forward slashes from JavaScript
                                            clean_match = match.replace('\\/', '/')
                                            logging.debug(f"Found filePath: {clean_match}")
                                            
                                            # Check if it's a document file
                                            if self.is_document_url(clean_match):
                                                redirect_url = urljoin(self.base_url, clean_match)
                                                logging.debug(f"Found document redirect: {redirect_url}")
                                                return redirect_url
                                    logging.debug(f"No filePath found in Drupal script #{i+1}")
        
        except Exception as e:
            logging.error(f"Error checking for client-side redirect: {e}")
        
        # No redirect found - this is the end of the chain
        logging.debug(f"End of redirect chain reached: {url}")
        return url
    
    async def extract_pdf_text(self, pdf_url: str) -> Optional[str]:
        """Extract text from PDF URL without downloading to disk"""
        try:
            async with self.session.get(pdf_url) as response:
                if response.status == 200:
                    # Read PDF content into memory
                    pdf_bytes = await response.read()
                    pdf_file = io.BytesIO(pdf_bytes)
                    
                    # Extract text using pypdf
                    pdf_reader = pypdf.PdfReader(pdf_file)
                    text_content = []
                    
                    for page_num in range(len(pdf_reader.pages)):
                        page = pdf_reader.pages[page_num]
                        text_content.append(page.extract_text())
                    
                    return "\n".join(text_content).strip()
                else:
                    return f"Failed to fetch PDF: HTTP {response.status}"
                    
        except Exception as e:
            logging.error(f"Error extracting PDF text from {pdf_url}: {e}")
            return f"Error extracting PDF text: {str(e)}"

    async def extract_html_content(self, resource: Resource, soup: BeautifulSoup):
        """Extract content from HTML page"""
        # Extract full title if it was truncated or missing
        if resource.title is None or resource.title == 'Title to be extracted':
            title_element = soup.find('h1') or soup.find(class_='title')
            if title_element:
                resource.title = title_element.get_text(strip=True)
        
        # Extract publish date from span with asset-date class
        date_element = soup.find('span', class_='asset-date')
        if date_element:
            resource.publish_date = date_element.get_text(strip=True)
        
        # Extract main content from the section element (only one per page)
        content_area = soup.find('section')
        if content_area:
            # Remove navigation, ads, etc.
            for unwanted in content_area.find_all(['nav', 'aside', 'footer', 'header']):
                unwanted.decompose()
            
            resource.content = content_area.get_text(strip=True, separator='\n')
    
    async def run_scraper(self):
        """Daily scraper execution - scrapes only the first page for new content"""
        logging.info("Starting Wi-Fi Alliance daily resource scraper...")

        datasource_id = "wfa_resource_page"
        
        # Check if we should scrape based on configuration
        if not self.should_scrape_datasource(datasource_id):
            config = self.get_datasource_config(datasource_id)
            logging.info(f"Skipping scrape for {datasource_id} - frequency: {config.get('scrape_frequency')}, last scraped: {config.get('last_scraped_at')}")
            return

        max_resources = settings.scraper_max_resources
        
        if max_resources == -1:
            logging.info("Starting Wi-Fi Alliance FULL resource scraper (unlimited)...")
        else:
            logging.info(f"Starting Wi-Fi Alliance resource scraper (max {max_resources} new resources)...")
        
        # Get new resource links (already deduplicated and redirects resolved)
        resources = await self.get_resource_links(max_resources=max_resources)

        if len(resources) == 0:
            logging.info("No new resources to scrape")
            self.clear_current_processing()
            return
        
        logging.info(f"Scraping {len(resources)} new resources")
        
        # Scrape all collected resources
        for i, resource in enumerate(resources, 1):
             # Update heartbeat and tracking
            self.update_heartbeat()
            self.update_current_processing(resource, f"scraping ({i}/{len(resources)})")
            
            logging.info(f"Scraping resource {i}/{len(resources)}: {resource.title}")
            scraped_resource = await self.scrape_resource(resource)
            
            # Log progress periodically
            if i % 10 == 0 or i == len(resources):
                scraped_data = self._format_resource_for_logging(scraped_resource)
                logging.info(f"Progress {i}/{len(resources)} - Scraped: {scraped_resource.title}")
                logging.debug(f"Resource data:\n{json.dumps(scraped_data, indent=2, ensure_ascii=False)}")
            
            self.update_current_processing(scraped_resource, f"publishing to queue ({i}/{len(resources)})")
            self.publish_message(scraped_resource)
            
            # Be respectful - add delay between requests
            await asyncio.sleep(settings.scraper_delay)

        # Mark datasource as scraped
        self.mark_datasource_scraped(datasource_id)
        
         # Clear current processing when done
        self.clear_current_processing()
        logging.info(f"Scraping completed: {len(resources)} resources processed")