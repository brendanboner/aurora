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
    
    async def get_resource_links(self) -> List[Resource]:
        """Extract resource links from the main resource center page (page 1 only - for daily updates)"""
        self.update_heartbeat()
        self.update_current_processing(
            Resource(title="Fetching resource list", url=self.resource_center_url, category="discovery"),
            "loading page 1"
        )
        async with self.session.get(self.resource_center_url) as response:
            html = await response.text()
        
        soup = BeautifulSoup(html, 'html.parser')
        return self._extract_resources_from_soup(soup)
    
    async def get_all_resource_links(self) -> List[Resource]:
        """Extract all resource links from all pages (for full database population)"""
        all_resources = []
        page = 0
        
        while True:
            page_url = f"{self.resource_center_url}?page={page}"
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
                break
                
            all_resources.extend(page_resources)
            logging.info(f"Found {len(page_resources)} resources on page {page + 1} (total: {len(all_resources)})")
            
            # Be respectful - add delay between page requests
            await asyncio.sleep(settings.scraper_delay)
            page += 1
        
        logging.info(f"Total resources found across all pages: {len(all_resources)}")
        return all_resources
    
    async def scrape_resource(self, resource: Resource) -> Resource:
        """Main entry point for scraping a resource - follows redirects to final content"""
        try:
            # Update status: resolving URL
            self.update_heartbeat()
            self.update_current_processing(resource, "resolving URL redirects")
            
            # Follow the complete redirect chain to get the final URL
            final_url = await self.follow_redirect_chain(resource.url)
            
            # Update the resource with the final URL
            resource.url = final_url
            
            # Determine content type and process accordingly
            if self.is_document_url(final_url):
                # It's a document - extract PDF text
                logging.debug(f"Extracting document from URL: {final_url}")
                self.update_heartbeat()
                self.update_current_processing(resource, "extracting PDF content")
                pdf_text = await self.extract_pdf_text(final_url)
                logging.debug(f"Extracted PDF text length: {len(pdf_text) if pdf_text else 0}")
                resource.content = pdf_text if pdf_text else "PDF document - text extraction failed"
            else:
                logging.debug(f"Extracting HTML content from URL: {final_url}")
                self.update_heartbeat()
                self.update_current_processing(resource, "extracting HTML content")
                # It's an HTML page - extract content
                async with self.session.get(final_url) as response:
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
        
        # Get resource links from first page only
        resources = await self.get_resource_links()
        logging.info(f"Found {len(resources)} resources on first page")
        
        # Scrape all resources from the first page
        for resource in resources:
            # Update heartbeat and tracking
            self.update_heartbeat()
            self.update_current_processing(resource, "scraping")
            
            logging.info(f"Scraping resource: {resource.title} at ({resource.url})")
            scraped_resource = await self.scrape_resource(resource)
            
            # Log scraped resource as formatted JSON
            scraped_data = self._format_resource_for_logging(scraped_resource)
            logging.debug(f"Scraped resource:\n{json.dumps(scraped_data, indent=2, ensure_ascii=False)}")
            
            self.update_current_processing(scraped_resource, "publishing to queue")
            self.publish_message(scraped_resource)
            
            # Be respectful - add delay between requests
            await asyncio.sleep(settings.scraper_delay)
        
        # Mark datasource as scraped
        self.mark_datasource_scraped(datasource_id)
        logging.info(f"Updated last_scraped_at for {datasource_id}")
        
        # Clear current processing when done
        self.clear_current_processing()
    
    async def run_full_scraper(self):
        """Full scraper execution - scrapes ALL pages for complete database population"""
        logging.info("Starting Wi-Fi Alliance FULL resource scraper...")
        
        # Get ALL resource links from all pages
        resources = await self.get_all_resource_links()
        logging.info(f"Found {len(resources)} total resources across all pages")
        
        # Scrape all resources
        for i, resource in enumerate(resources, 1):
            # Update heartbeat and tracking
            self.update_heartbeat()
            self.update_current_processing(resource, f"scraping ({i}/{len(resources)})")
            
            logging.info(f"Scraping resource {i}/{len(resources)}: {resource.title}")
            scraped_resource = await self.scrape_resource(resource)
            
            # Log progress every 50 resources
            if i % 50 == 0:
                scraped_data = self._format_resource_for_logging(scraped_resource)
                logging.debug(f"Progress {i}/{len(resources)} - Scraped resource:\n{json.dumps(scraped_data, indent=2, ensure_ascii=False)}")
            
            self.update_current_processing(scraped_resource, f"publishing to queue ({i}/{len(resources)})")
            self.publish_message(scraped_resource)
            
            # Be respectful - add delay between requests
            await asyncio.sleep(settings.scraper_delay)
        
        # Clear current processing when done
        self.clear_current_processing()


# TODO:
# - After getting the first page of resources if all are new resources we need to get another page