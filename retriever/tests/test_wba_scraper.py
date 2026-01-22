"""
Tests for the WBA (Wireless Broadband Alliance) scraper.

Tests cover:
- Authentication (WordPress login flow)
- Resource discovery and extraction (year-based pagination)
- Event discovery (hosted and external events)
- Content extraction (PDF, HTML, YouTube, ZIP)
- Full refresh with content hash checking
- Incremental discovery with duplicate detection
"""

import pytest
from datetime import datetime, date
from unittest.mock import MagicMock, AsyncMock, patch, call
from bs4 import BeautifulSoup
import hashlib
from typing import List, Dict, Any
from urllib.parse import urlparse

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.WBA import WBAScraper
from scrapers.base import Resource, Event


# =============================================================================
# Test Helpers
# =============================================================================

class AsyncContextManagerMock:
    """Helper class to mock async context managers like aiohttp responses."""
    def __init__(self, return_value):
        self.return_value = return_value
    
    async def __aenter__(self):
        # Return the actual response object, not self
        return self.return_value
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def wba_scraper(patched_base_scraper_deps):
    """Create WBAScraper instance with mocked dependencies."""
    scraper = WBAScraper()
    # Mock the session with AsyncMock
    mock_session = MagicMock()
    # Add cookie_jar mock
    mock_session.cookie_jar = MagicMock()
    scraper.session = mock_session
    return scraper


@pytest.fixture
def sample_wba_config():
    """Sample WBA datasource configuration."""
    return {
        'datasource_id': 'wba_resources',
        'name': 'WBA Resources',
        'scraper_type': 'wba',
        'resource_url': '/resources/',
        'scrape_schedule': '0 3 * * *',
        'scraper_delay': 0.5,
        'max_resources': 100,
        'discovery_mode': 'incremental',
        'consecutive_duplicates_limit': 5,
        'is_full_refresh': False,
        'check_content_hash': True
    }


@pytest.fixture
def sample_resource_html():
    """Sample HTML for a WBA resource listing page."""
    return """
    <html>
    <body>
        <div class="wal-resource-item">
            <div class="wal-item-content">
                <h2><a href="/resources/test-whitepaper-2024/">5G Whitepaper</a></h2>
                <p>A comprehensive guide to 5G technology deployment.</p>
            </div>
            <div class="wal-item-dl-bar">
                <button class="wal-download-link-resource" onclick="openInNewTab('https://wballiance.com/wp-content/uploads/2024/01/5g-whitepaper.pdf')">Download</button>
                <span style="white-space: nowrap">01 - 15 - 24</span>
                <span style="white-space: nowrap"><a href="/category/whitepapers/">Whitepapers</a></span>
            </div>
        </div>
        <div class="wal-resource-item">
            <div class="wal-item-content">
                <h2><a href="https://www.youtube.com/watch?v=test123">WBA Webinar: Wi-Fi 6E</a></h2>
                <p>Watch our latest webinar on Wi-Fi 6E deployment strategies.</p>
            </div>
            <div class="wal-item-dl-bar">
                <button class="wal-download-link-resource" onclick="openInNewTab('https://www.youtube.com/watch?v=test123')">Watch</button>
                <span style="white-space: nowrap">12 - 10 - 23</span>
                <span style="white-space: nowrap"><a href="/category/webinars/">Webinars</a></span>
            </div>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def sample_hosted_events_html():
    """Sample HTML for WBA hosted events page."""
    return """
    <html>
    <body>
        <div class="fusion-builder-row">
            <a href="https://wballiance.com/event/wba-forum-2026/" class="fusion-button">
                <span class="fusion-button-text">REGISTER</span>
            </a>
            <a href="https://wirelessglobalcongress.com/americas-2026/" class="fusion-button">
                <span class="fusion-button-text">REGISTER</span>
            </a>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def sample_wba_event_detail_html():
    """Sample HTML for a WBA-hosted event detail page."""
    return """
    <html>
    <body>
        <div class="fusion-title-1">
            <h2>WBA Annual <br> Forum 2026</h2>
        </div>
        <h3>Next Forum: March 15, 2026</h3>
    </body>
    </html>
    """


@pytest.fixture
def sample_wgc_event_detail_html():
    """Sample HTML for a WGC event detail page."""
    return """
    <html>
    <body>
        <div class="fusion-title-1">
            <h1>Wireless Global <br> Congress Americas</h1>
        </div>
        <a class="fusion-button" href="/register">
            <span class="fusion-button-text">DALLAS, USA • MAY 18 – MAY 21</span>
        </a>
        <div class="fusion-builder-row-3">
            <div class="fusion-text">
                <p>Join industry leaders for the premier wireless technology event.</p>
            </div>
            <div class="fusion-text">
                <p>Topics include 5G, Wi-Fi 6E, and IoT deployment strategies.</p>
            </div>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def sample_external_events_html():
    """Sample HTML for external events page."""
    return """
    <html>
    <body>
        <div class="fusion-equal-height-columns">
            <div class="fusion-builder-row fusion-row">
                <div class="fusion-layout-column fusion-builder-column-0">
                    <h4>Mobile World Congress 2026</h4>
                    <h2>25 February 2026, Barcelona</h2>
                    <h6>The world's largest mobile technology exhibition.</h6>
                    <h6>Meet with WBA representatives at booth #1234.</h6>
                    <a class="fusion-button" href="https://mwc.com/2026">Register</a>
                </div>
                <div class="fusion-layout-column fusion-builder-column-1">
                    <h4>5G Technology Summit</h4>
                    <h2>10 March 2026, Webinar</h2>
                    <h6>Virtual summit featuring 5G deployment case studies.</h6>
                    <a class="fusion-button" href="https://5gsummit.com/register">Register</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """


# =============================================================================
# Test WBAScraper Initialization
# =============================================================================

class TestWBAScraperInit:
    """Tests for WBAScraper initialization."""
    
    def test_init_sets_base_url(self, patched_base_scraper_deps):
        """WBAScraper should initialize with correct base URL."""
        scraper = WBAScraper()
        assert scraper.base_url == "https://wballiance.com"
        assert scraper.resources_url == "https://wballiance.com/resources/"
        assert scraper.scraper_name == "wba"
    
    def test_init_authentication_state(self, patched_base_scraper_deps):
        """WBAScraper should start in unauthenticated state."""
        scraper = WBAScraper()
        assert scraper.username is None
        assert scraper.password is None
        assert scraper.is_authenticated is False


# =============================================================================
# Test URL Type Detection
# =============================================================================

class TestURLTypeDetection:
    """Tests for URL type detection methods."""
    
    def test_is_document_url_pdf(self, wba_scraper):
        """Should detect PDF URLs."""
        assert wba_scraper.is_document_url("https://example.com/doc.pdf")
        assert wba_scraper.is_document_url("https://example.com/DOC.PDF")
    
    def test_is_document_url_office(self, wba_scraper):
        """Should detect Office document URLs."""
        assert wba_scraper.is_document_url("https://example.com/report.docx")
        assert wba_scraper.is_document_url("https://example.com/data.xlsx")
        assert wba_scraper.is_document_url("https://example.com/slides.pptx")
    
    def test_is_document_url_negative(self, wba_scraper):
        """Should not detect non-document URLs."""
        assert not wba_scraper.is_document_url("https://example.com/page.html")
        assert not wba_scraper.is_document_url("https://youtube.com/watch?v=123")
    
    def test_is_youtube_url(self, wba_scraper):
        """Should detect YouTube URLs."""
        assert wba_scraper.is_youtube_url("https://www.youtube.com/watch?v=test123")
        assert wba_scraper.is_youtube_url("https://youtu.be/test123")
        assert wba_scraper.is_youtube_url("https://YOUTUBE.COM/watch")
    
    def test_is_youtube_url_negative(self, wba_scraper):
        """Should not detect non-YouTube URLs."""
        assert not wba_scraper.is_youtube_url("https://example.com/video")
    
    def test_is_zip_url(self, wba_scraper):
        """Should detect ZIP archive URLs."""
        assert wba_scraper.is_zip_url("https://example.com/archive.zip")
        assert wba_scraper.is_zip_url("https://example.com/ARCHIVE.ZIP")
    
    def test_is_zip_url_negative(self, wba_scraper):
        """Should not detect non-ZIP URLs."""
        assert not wba_scraper.is_zip_url("https://example.com/doc.pdf")


# =============================================================================
# Test Authentication
# =============================================================================

class TestAuthentication:
    """Tests for WordPress authentication."""
    
    @pytest.mark.asyncio
    async def test_authenticate_success(self, wba_scraper):
        """Authentication should succeed with valid credentials and cookies."""
        # Mock successful authentication response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.url = "https://wballiance.com/wp-admin/"
        mock_response.headers = {'Set-Cookie': 'wordpress_logged_in_abc123=value'}
        mock_response.text = AsyncMock(return_value="<html>Success</html>")
        
        # Create a proper mock cookie that can be used in iteration
        mock_cookie = MagicMock()
        mock_cookie.key = "wordpress_logged_in_abc123"
        
        # Mock cookie jar to return an iterable with values()
        mock_cookies_dict = MagicMock()
        mock_cookies_dict.values.return_value = [mock_cookie]
        wba_scraper.session.cookie_jar.filter_cookies.return_value = mock_cookies_dict
        
        # Create async context manager using helper
        # Note: mock_post should NOT be async - it returns an AsyncContextManagerMock directly
        def mock_post(*args, **kwargs):
            return AsyncContextManagerMock(mock_response)
        
        wba_scraper.session.post = mock_post
        
        result = await wba_scraper.authenticate("testuser", "testpass")
        
        assert result is True
        assert wba_scraper.is_authenticated is True
        assert wba_scraper.username == "testuser"
        assert wba_scraper.password == "testpass"
    
    @pytest.mark.asyncio
    async def test_authenticate_failure_no_cookie(self, wba_scraper):
        """Authentication should fail if no auth cookie is set."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.url = "https://wballiance.com/wp-login.php"
        mock_response.headers = {}
        mock_response.text = AsyncMock(return_value="<html>login_error</html>")
        
        # Mock empty cookie jar
        mock_cookies_dict = MagicMock()
        mock_cookies_dict.values.return_value = []
        wba_scraper.session.cookie_jar.filter_cookies.return_value = mock_cookies_dict
        
        def mock_post(*args, **kwargs):
            return AsyncContextManagerMock(mock_response)
        
        wba_scraper.session.post = mock_post
        
        result = await wba_scraper.authenticate("testuser", "wrongpass")
        
        assert result is False
        assert wba_scraper.is_authenticated is False
    
    @pytest.mark.asyncio
    async def test_authenticate_no_credentials(self, wba_scraper):
        """Authentication should fail gracefully if no credentials provided."""
        result = await wba_scraper.authenticate(None, None)
        
        assert result is False
        assert wba_scraper.is_authenticated is False
    
    @pytest.mark.asyncio
    async def test_authenticate_http_error(self, wba_scraper):
        """Authentication should fail on HTTP error."""
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="<html>Server Error</html>")
        
        def mock_post(*args, **kwargs):
            return AsyncContextManagerMock(mock_response)
        
        wba_scraper.session.post = mock_post
        
        result = await wba_scraper.authenticate("testuser", "testpass")
        
        assert result is False
        assert wba_scraper.is_authenticated is False


# =============================================================================
# Test Resource Extraction
# =============================================================================

class TestResourceExtraction:
    """Tests for extracting resources from HTML."""
    
    def test_extract_resources_from_soup(self, wba_scraper, sample_resource_html):
        """Should extract resources from HTML with correct fields."""
        soup = BeautifulSoup(sample_resource_html, 'html.parser')
        resources = wba_scraper._extract_resources_from_soup(
            soup, 
            year=2024, 
            datasource_id='wba_test'
        )
        
        assert len(resources) == 2
        
        # Check first resource (PDF)
        pdf_resource = resources[0]
        assert pdf_resource.title == "5G Whitepaper"
        assert "5g-whitepaper.pdf" in pdf_resource.url
        assert pdf_resource.category == "whitepapers"
        assert pdf_resource.publish_date == "2024-01-15"
        assert pdf_resource.datasource_id == "wba_test"
        
        # Check second resource (YouTube)
        youtube_resource = resources[1]
        assert "WBA Webinar: Wi-Fi 6E" in youtube_resource.title
        parsed_url = urlparse(youtube_resource.url)
        assert parsed_url.hostname and (
            parsed_url.hostname == "youtube.com"
            or parsed_url.hostname.endswith(".youtube.com")
        )
        assert youtube_resource.category == "webinars"
        assert youtube_resource.publish_date == "2023-12-10"
    
    def test_extract_resources_empty_page(self, wba_scraper):
        """Should return empty list for page with no resources."""
        html = "<html><body><div>No resources here</div></body></html>"
        soup = BeautifulSoup(html, 'html.parser')
        resources = wba_scraper._extract_resources_from_soup(soup, year=2024)
        
        assert resources == []
    
    def test_extract_resources_missing_fields(self, wba_scraper):
        """Should handle missing optional fields gracefully."""
        html = """
        <html>
        <body>
            <div class="wal-resource-item">
                <div class="wal-item-content">
                    <h2><a href="/resources/test/">Test Resource</a></h2>
                </div>
                <div class="wal-item-dl-bar">
                    <button class="wal-download-link-resource" onclick="openInNewTab('https://example.com/test.pdf')">Download</button>
                </div>
            </div>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')
        resources = wba_scraper._extract_resources_from_soup(soup, year=2025)
        
        assert len(resources) == 1
        assert resources[0].title == "Test Resource"
        assert resources[0].category == "uncategorized"
        assert resources[0].publish_date == "2025-01-01"  # Falls back to year


# =============================================================================
# Test Year-Based Resource Discovery
# =============================================================================

class TestYearBasedDiscovery:
    """Tests for get_resources_for_year method."""
    
    @pytest.mark.asyncio
    async def test_get_resources_for_year_single_page(self, wba_scraper, sample_resource_html):
        """Should extract resources from a single year page."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value=sample_resource_html)
        
        mock_response_404 = AsyncMock()
        mock_response_404.status = 404
        
        def mock_get(url, **kwargs):
            # Return 404 for page 2 and beyond to stop pagination
            if '/page/2/' in url or '/page/3/' in url:
                return AsyncContextManagerMock(mock_response_404)
            return AsyncContextManagerMock(mock_response)
        
        wba_scraper.session.get = mock_get
        
        # Mock batch_check_urls_exist to return no existing URLs
        wba_scraper.batch_check_urls_exist = MagicMock(return_value={})
        wba_scraper.update_heartbeat = MagicMock()
        wba_scraper.update_current_processing = MagicMock()
        wba_scraper.get_scraper_delay = MagicMock(return_value=0)
        
        resources, consecutive_count = await wba_scraper.get_resources_for_year(
            year=2024,
            datasource_id='wba_test',
            max_resources=-1,
            discovery_mode='incremental'
        )
        
        assert len(resources) == 2
        assert consecutive_count == 0  # No duplicates found
    
    @pytest.mark.asyncio
    async def test_get_resources_for_year_with_pagination(self, wba_scraper, sample_resource_html):
        """Should handle pagination across multiple pages."""
        # Mock responses for page 1 (has content) and page 2 (404)
        mock_response_page1 = AsyncMock()
        mock_response_page1.status = 200
        mock_response_page1.text = AsyncMock(return_value=sample_resource_html)
        
        mock_response_page2 = AsyncMock()
        mock_response_page2.status = 404
        
        def mock_get(url, **kwargs):
            # Check if it's page 1 or page 2+
            if '/page/1/' in url or url.endswith('/2024/'):
                return AsyncContextManagerMock(mock_response_page1)
            else:
                return AsyncContextManagerMock(mock_response_page2)
        
        wba_scraper.session.get = mock_get
        wba_scraper.batch_check_urls_exist = MagicMock(return_value={})
        wba_scraper.update_heartbeat = MagicMock()
        wba_scraper.update_current_processing = MagicMock()
        wba_scraper.get_scraper_delay = MagicMock(return_value=0)
        
        resources, _ = await wba_scraper.get_resources_for_year(
            year=2024,
            datasource_id='wba_test'
        )
        
        assert len(resources) == 2  # Only from page 1
    
    @pytest.mark.asyncio
    async def test_get_resources_for_year_stops_on_consecutive_duplicates(self, wba_scraper, sample_resource_html):
        """Should stop scraping after hitting consecutive duplicate limit."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value=sample_resource_html)
        
        mock_response_404 = AsyncMock()
        mock_response_404.status = 404
        
        def mock_get(url, **kwargs):
            # Return 404 for page 2+ to prevent infinite loop if duplicates don't stop it
            if '/page/2/' in url or '/page/3/' in url:
                return AsyncContextManagerMock(mock_response_404)
            return AsyncContextManagerMock(mock_response)
        
        wba_scraper.session.get = mock_get
        
        # Mock all URLs as existing (duplicates)
        wba_scraper.batch_check_urls_exist = MagicMock(return_value={
            "https://wballiance.com/wp-content/uploads/2024/01/5g-whitepaper.pdf": True,
            "https://www.youtube.com/watch?v=test123": True
        })
        wba_scraper.update_heartbeat = MagicMock()
        wba_scraper.update_current_processing = MagicMock()
        wba_scraper.get_scraper_delay = MagicMock(return_value=0)
        
        resources, consecutive_count = await wba_scraper.get_resources_for_year(
            year=2024,
            datasource_id='wba_test',
            discovery_mode='incremental',
            consecutive_duplicates_limit=2
        )
        
        assert len(resources) == 0  # All duplicates, none added
        assert consecutive_count == 2  # Hit the limit


# =============================================================================
# Test Full Refresh with Content Hash Checking
# =============================================================================

class TestFullRefreshContentHash:
    """Tests for full refresh mode with content hash checking."""
    
    @pytest.mark.asyncio
    async def test_full_refresh_detects_content_changes(self, wba_scraper, sample_resource_html):
        """Should re-scrape existing resources and detect content changes."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value=sample_resource_html)
        
        mock_response_404 = AsyncMock()
        mock_response_404.status = 404
        
        def mock_get(url, **kwargs):
            # Return 404 for page 2+ to prevent infinite loop
            if '/page/2/' in url or '/page/3/' in url:
                return AsyncContextManagerMock(mock_response_404)
            return AsyncContextManagerMock(mock_response)
        
        wba_scraper.session.get = mock_get
        
        # Mock URL exists but content has changed
        wba_scraper.batch_check_urls_exist = MagicMock(return_value={
            "https://wballiance.com/wp-content/uploads/2024/01/5g-whitepaper.pdf": True
        })
        
        # Mock scrape_resource to return content
        async def mock_scrape(resource):
            resource.content = "Updated content for 5G whitepaper"
            return resource
        wba_scraper.scrape_resource = mock_scrape
        
        # Mock has_content_changed to return True (content changed)
        wba_scraper.has_content_changed = MagicMock(return_value=True)
        wba_scraper.update_heartbeat = MagicMock()
        wba_scraper.update_current_processing = MagicMock()
        wba_scraper.get_scraper_delay = MagicMock(return_value=0)
        
        resources, consecutive_count = await wba_scraper.get_resources_for_year(
            year=2024,
            datasource_id='wba_test',
            is_full_refresh=True,
            check_content_hash=True
        )
        
        # Should include the changed resource
        assert len(resources) >= 1
        assert consecutive_count == 0  # Content change resets counter


# =============================================================================
# Test Event Discovery - Hosted Events
# =============================================================================

class TestHostedEventsDiscovery:
    """Tests for discovering WBA hosted events."""
    
    @pytest.mark.asyncio
    async def test_get_hosted_events(self, wba_scraper, sample_hosted_events_html,
                                     sample_wba_event_detail_html, sample_wgc_event_detail_html):
        """Should discover both WBA and WGC hosted events."""
        # Mock the hosted events listing page
        mock_listing_response = AsyncMock()
        mock_listing_response.status = 200
        mock_listing_response.text = AsyncMock(return_value=sample_hosted_events_html)
        
        # Mock WBA event detail page
        mock_wba_detail = AsyncMock()
        mock_wba_detail.status = 200
        mock_wba_detail.text = AsyncMock(return_value=sample_wba_event_detail_html)
        
        # Mock WGC event detail page
        mock_wgc_detail = AsyncMock()
        mock_wgc_detail.status = 200
        mock_wgc_detail.text = AsyncMock(return_value=sample_wgc_event_detail_html)
        
        def mock_get(url, **kwargs):
            if 'wba-hosted-events' in url:
                return AsyncContextManagerMock(mock_listing_response)
            elif 'wballiance.com/event' in url:
                return AsyncContextManagerMock(mock_wba_detail)
            else:  # WGC event
                return AsyncContextManagerMock(mock_wgc_detail)
        
        wba_scraper.session.get = mock_get
        wba_scraper.batch_check_urls_exist = MagicMock(return_value={})
        wba_scraper.update_heartbeat = MagicMock()
        wba_scraper.update_current_processing = MagicMock()
        
        events = await wba_scraper.get_hosted_events(datasource_id='wba_test')
        
        # Should have both events
        assert len(events) == 2
        
        # Check WBA event
        wba_event = next((e for e in events if 'wballiance.com/event' in e.url), None)
        assert wba_event is not None
        assert "Forum" in wba_event.name
        assert wba_event.event_type == "forum"
        assert wba_event.start_date == "2026-03-15"
        
        # Check WGC event
        wgc_event = next((e for e in events if urlparse(e.url).hostname == "wirelessglobalcongress.com"), None)
        assert wgc_event is not None
        assert "Congress" in wgc_event.name
        assert wgc_event.event_type == "conference"
        assert wgc_event.location == "DALLAS, USA"
    
    @pytest.mark.asyncio
    async def test_hosted_events_filters_past_events(self, wba_scraper):
        """Should only include future events or new past events."""
        # HTML with past event date
        past_event_html = """
        <html><body>
            <a href="https://wballiance.com/event/past-forum/" class="fusion-button">
                <span class="fusion-button-text">REGISTER</span>
            </a>
        </body></html>
        """
        
        past_detail_html = """
        <html><body>
            <div class="fusion-title-1"><h2>Past Forum</h2></div>
            <h3>Next Event: January 1, 2020</h3>
        </body></html>
        """
        
        mock_listing = AsyncMock()
        mock_listing.status = 200
        mock_listing.text = AsyncMock(return_value=past_event_html)
        
        mock_detail = AsyncMock()
        mock_detail.status = 200
        mock_detail.text = AsyncMock(return_value=past_detail_html)
        
        def mock_get(url, **kwargs):
            if 'wba-hosted-events' in url:
                return AsyncContextManagerMock(mock_listing)
            else:
                return AsyncContextManagerMock(mock_detail)
        
        wba_scraper.session.get = mock_get
        # Mock as already existing
        wba_scraper.batch_check_urls_exist = MagicMock(return_value={
            "https://wballiance.com/event/past-forum/": True
        })
        wba_scraper.update_heartbeat = MagicMock()
        wba_scraper.update_current_processing = MagicMock()
        
        events = await wba_scraper.get_hosted_events(datasource_id='wba_test')
        
        # Past event already in DB should be filtered out
        assert len(events) == 0


# =============================================================================
# Test Event Discovery - External Events
# =============================================================================

class TestExternalEventsDiscovery:
    """Tests for discovering external events."""
    
    @pytest.mark.asyncio
    async def test_get_external_events(self, wba_scraper, sample_external_events_html):
        """Should discover external events from listing page."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value=sample_external_events_html)
        
        def mock_get(*args, **kwargs):
            return AsyncContextManagerMock(mock_response)
        
        wba_scraper.session.get = mock_get
        
        wba_scraper.batch_check_urls_exist = MagicMock(return_value={})
        wba_scraper.update_heartbeat = MagicMock()
        wba_scraper.update_current_processing = MagicMock()
        
        events = await wba_scraper.get_external_events(datasource_id='wba_test')
        
        assert len(events) == 2
        
        # Check MWC event
        mwc_event = next(
            (e for e in events if urlparse(e.url).hostname == "mwc.com"),
            None,
        )
        assert mwc_event is not None
        assert "Mobile World Congress" in mwc_event.name
        assert mwc_event.location == "Barcelona"
        assert mwc_event.start_date == "2026-02-25"
        assert mwc_event.event_type == "external"
        
        # Check 5G summit event
        summit_event = next(
            (e for e in events if urlparse(e.url).hostname == "5gsummit.com"),
            None,
        )
        assert summit_event is not None
        assert "5G Technology Summit" in summit_event.name
        assert summit_event.location == "Webinar"
        assert summit_event.start_date == "2026-03-10"


# =============================================================================
# Test Content Scraping
# =============================================================================

class TestContentScraping:
    """Tests for scraping resource content."""
    
    @pytest.mark.asyncio
    async def test_scrape_youtube_resource(self, wba_scraper):
        """Should handle YouTube videos as metadata-only."""
        resource = Resource(
            title="Test Webinar",
            url="https://www.youtube.com/watch?v=test123",
            category="webinars",
            datasource_id="wba_test"
        )
        
        wba_scraper.update_heartbeat = MagicMock()
        wba_scraper.update_current_processing = MagicMock()
        
        result = await wba_scraper.scrape_resource(resource)
        
        assert "YouTube video" in result.content
        assert result.url in result.content
    
    @pytest.mark.asyncio
    async def test_scrape_zip_resource(self, wba_scraper):
        """Should handle ZIP archives as metadata-only."""
        resource = Resource(
            title="Standards Archive",
            url="https://wballiance.com/files/standards.zip",
            category="standards",
            datasource_id="wba_test"
        )
        
        wba_scraper.update_heartbeat = MagicMock()
        wba_scraper.update_current_processing = MagicMock()
        
        result = await wba_scraper.scrape_resource(resource)
        
        assert "ZIP archive" in result.content
        assert result.url in result.content
    
    @pytest.mark.asyncio
    async def test_scrape_pdf_resource_requires_auth(self, wba_scraper):
        """Should attempt PDF download with authenticated session."""
        resource = Resource(
            title="5G Whitepaper",
            url="https://wballiance.com/wp-content/uploads/test.pdf",
            category="whitepapers",
            datasource_id="wba_test"
        )
        
        # Mock authenticated session
        wba_scraper.is_authenticated = True
        
        # Mock 403 response (access denied)
        mock_response = AsyncMock()
        mock_response.status = 403
        
        def mock_get(*args, **kwargs):
            return AsyncContextManagerMock(mock_response)
        
        wba_scraper.session.get = mock_get
        
        wba_scraper.update_heartbeat = MagicMock()
        wba_scraper.update_current_processing = MagicMock()
        
        result = await wba_scraper.scrape_resource(resource)
        
        assert "Access denied" in result.content


# =============================================================================
# Test Full Scraper Run
# =============================================================================

class TestFullScraperRun:
    """Tests for the complete run_scraper method."""
    
    @pytest.mark.asyncio
    async def test_run_scraper_requires_authentication(self, wba_scraper, sample_wba_config):
        """Should fail if authentication fails."""
        wba_scraper.authenticate = AsyncMock(return_value=False)
        wba_scraper.start_batch = MagicMock(return_value="batch-123")
        
        # Mock settings with credentials
        with patch('scrapers.WBA.settings') as mock_settings:
            mock_settings.wba_username = "testuser"
            mock_settings.wba_password = "testpass"
            
            with pytest.raises(Exception, match="authentication failed"):
                await wba_scraper.run_scraper(sample_wba_config)
    
    @pytest.mark.asyncio
    async def test_run_scraper_success(self, wba_scraper, sample_wba_config):
        """Should successfully run scraper with all phases."""
        # Mock successful authentication
        wba_scraper.authenticate = AsyncMock(return_value=True)
        
        # Mock discovery methods
        wba_scraper.get_hosted_events = AsyncMock(return_value=[
            Event(
                name="Test Forum",
                event_type="forum",
                start_date="2026-03-15",
                location="Virtual",
                url="https://wballiance.com/event/test",
                datasource_id="wba_test"
            )
        ])
        wba_scraper.get_external_events = AsyncMock(return_value=[])
        wba_scraper.get_resources = AsyncMock(return_value=[
            Resource(
                title="Test Whitepaper",
                url="https://wballiance.com/test.pdf",
                category="whitepapers",
                datasource_id="wba_test"
            )
        ])
        
        # Mock publishing methods
        wba_scraper.start_batch = MagicMock(return_value="batch-123")
        wba_scraper.publish_event = MagicMock()
        wba_scraper.scrape_resource = AsyncMock(side_effect=lambda r: r)
        wba_scraper.publish_resource = MagicMock()
        wba_scraper.mark_datasource_scraped = MagicMock()
        wba_scraper.end_batch = MagicMock()
        wba_scraper.update_heartbeat = MagicMock()
        wba_scraper.update_current_processing = MagicMock()
        wba_scraper.clear_current_processing = MagicMock()
        wba_scraper.get_current_batch_id = MagicMock(return_value="batch-123")
        
        # Mock settings
        with patch('scrapers.WBA.settings') as mock_settings:
            mock_settings.wba_username = "testuser"
            mock_settings.wba_password = "testpass"
            
            await wba_scraper.run_scraper(sample_wba_config)
        
        # Verify phases executed
        wba_scraper.authenticate.assert_called_once()
        wba_scraper.get_hosted_events.assert_called_once()
        wba_scraper.get_external_events.assert_called_once()
        wba_scraper.get_resources.assert_called_once()
        
        # Verify events and resources were published
        assert wba_scraper.publish_event.call_count == 1
        assert wba_scraper.publish_resource.call_count == 1
        
        wba_scraper.mark_datasource_scraped.assert_called_once()
        wba_scraper.end_batch.assert_called_once()


# =============================================================================
# Test Header Generation
# =============================================================================

class TestHeaderGeneration:
    """Tests for browser header generation."""
    
    def test_get_headers_default(self, wba_scraper):
        """Should return default browser headers."""
        headers = wba_scraper.get_headers()
        
        assert 'User-Agent' in headers
        assert 'Chrome' in headers['User-Agent']
        assert 'Accept' in headers
        assert 'Sec-Fetch-Dest' in headers
    
    def test_get_headers_with_referer(self, wba_scraper):
        """Should include custom referer when provided."""
        headers = wba_scraper.get_headers(referer="https://wballiance.com/resources/")
        
        assert headers['Referer'] == "https://wballiance.com/resources/"
        assert 'User-Agent' in headers


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
