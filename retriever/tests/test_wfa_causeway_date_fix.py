"""
Tests for WFA Causeway scraper date comparison fix.

This test verifies the fix for a bug where last_scraped_at stored as a string
in Neo4j caused date comparisons to fail silently, resulting in 0 resources
being discovered on incremental scrapes.

The bug: Neo4j stores last_scraped_at as ISO string "2026-01-09T03:02:37.160014"
but the scraper compared it directly with datetime objects, causing TypeError.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from bs4 import BeautifulSoup

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestLastScrapedAtParsing:
    """Test the _parse_last_scraped_at helper function."""
    
    def test_parse_iso_string(self):
        """Test parsing ISO format string from Neo4j."""
        from scrapers.WFA_causeway import _parse_last_scraped_at
        
        # This is exactly how Neo4j returns the timestamp
        neo4j_string = "2026-01-09T03:02:37.160014"
        
        result = _parse_last_scraped_at(neo4j_string)
        
        assert result is not None
        assert isinstance(result, datetime)
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 9
        assert result.hour == 3
        assert result.minute == 2
        assert result.tzinfo is not None  # Should be timezone-aware
    
    def test_parse_datetime_passthrough(self):
        """Test that datetime objects pass through unchanged."""
        from scrapers.WFA_causeway import _parse_last_scraped_at
        
        dt = datetime(2026, 1, 6, 1, 38, 5, tzinfo=timezone.utc)
        
        result = _parse_last_scraped_at(dt)
        
        assert result == dt
        assert result.tzinfo is not None
    
    def test_parse_naive_datetime_gets_timezone(self):
        """Test that naive datetimes get UTC timezone added."""
        from scrapers.WFA_causeway import _parse_last_scraped_at
        
        naive_dt = datetime(2026, 1, 6, 1, 38, 5)
        assert naive_dt.tzinfo is None
        
        result = _parse_last_scraped_at(naive_dt)
        
        assert result.tzinfo == timezone.utc
    
    def test_parse_none_returns_none(self):
        """Test that None input returns None."""
        from scrapers.WFA_causeway import _parse_last_scraped_at
        
        result = _parse_last_scraped_at(None)
        
        assert result is None
    
    def test_parse_invalid_string_returns_none(self):
        """Test that invalid strings return None (not raise)."""
        from scrapers.WFA_causeway import _parse_last_scraped_at
        
        result = _parse_last_scraped_at("not a date")
        
        assert result is None


class TestDateComparisonBug:
    """
    Test the actual bug scenario: comparing parsed mod dates with last_scraped_at.
    
    The bug occurred because:
    1. Portal mod dates are parsed to datetime objects (e.g., 2026-01-07T23:59:59 UTC)
    2. last_scraped_at comes from Neo4j as a string (e.g., "2026-01-06T01:38:05")
    3. Comparing datetime < string raises TypeError
    4. The error was caught and swallowed, returning empty resource list
    """
    
    def test_old_behavior_string_comparison_fails(self):
        """
        Demonstrate the bug: comparing datetime with string raises TypeError.
        
        This is what happened before the fix.
        """
        # Parsed mod date from portal (datetime object, timezone-aware)
        item_mod_date = datetime(2026, 1, 7, 23, 59, 59, tzinfo=timezone.utc)
        
        # last_scraped_at from Neo4j as string (the bug)
        last_scraped_at_string = "2026-01-06T01:38:05.123456"
        
        # This comparison raises TypeError - the root cause of the bug
        with pytest.raises(TypeError) as exc_info:
            _ = item_mod_date < last_scraped_at_string
        
        assert "can't compare" in str(exc_info.value).lower() or "not supported" in str(exc_info.value).lower()
    
    def test_fixed_behavior_datetime_comparison_works(self):
        """
        After the fix: both values are datetime objects, comparison works.
        """
        from scrapers.WFA_causeway import _parse_last_scraped_at
        
        # Parsed mod date from portal (datetime object, timezone-aware)
        item_mod_date = datetime(2026, 1, 7, 23, 59, 59, tzinfo=timezone.utc)
        
        # last_scraped_at from Neo4j, now properly parsed
        last_scraped_at_string = "2026-01-06T01:38:05.123456"
        last_scraped_at = _parse_last_scraped_at(last_scraped_at_string)
        
        # Now comparison works without error
        result = item_mod_date < last_scraped_at
        
        # Jan 7 23:59:59 is NOT less than Jan 6 01:38:05, so this should be False
        assert result is False
        
        # The document SHOULD be included (it's newer than last_scraped_at)
        should_include = item_mod_date >= last_scraped_at
        assert should_include is True
    
    def test_same_day_document_posted_after_scrape(self):
        """
        Test the specific scenario that caused missing documents:
        - Scrape ran at 01:38 AM on Jan 6
        - Document posted at 12:00 PM on Jan 6 (after scrape)
        - Portal shows mod date as "Jan 6, 2026" (parsed to 23:59:59)
        - Next day's scrape should pick up this document
        """
        from scrapers.WFA_causeway import _parse_last_scraped_at
        
        # Scrape completed early morning Jan 6
        last_scraped_at_string = "2026-01-06T01:38:05.123456"
        last_scraped_at = _parse_last_scraped_at(last_scraped_at_string)
        
        # Document posted later on Jan 6, portal shows "Jan 6, 2026"
        # Parser sets to end of day: 23:59:59 UTC
        doc_mod_date = datetime(2026, 1, 6, 23, 59, 59, tzinfo=timezone.utc)
        
        # The document's mod date (23:59:59) is AFTER last_scraped_at (01:38:05)
        # So the document should be included
        should_skip = doc_mod_date < last_scraped_at
        assert should_skip is False, "Document posted same day after scrape should NOT be skipped"


class TestParseModDate:
    """Test the _parse_mod_date method that parses portal date strings."""
    
    def test_parse_month_day_year_format(self):
        """Test parsing 'Jan 7, 2026' format."""
        from scrapers.WFA_causeway import WFACausewayScraper
        
        scraper = WFACausewayScraper.__new__(WFACausewayScraper)
        
        result = scraper._parse_mod_date("Jan 7, 2026")
        
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 7
        # Should be end of day to include same-day documents
        assert result.hour == 23
        assert result.minute == 59
        assert result.second == 59
        assert result.tzinfo is not None
    
    def test_parse_numeric_format(self):
        """Test parsing '1/7/26' format."""
        from scrapers.WFA_causeway import WFACausewayScraper
        
        scraper = WFACausewayScraper.__new__(WFACausewayScraper)
        
        result = scraper._parse_mod_date("1/7/26")
        
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 7
        assert result.hour == 23
        assert result.minute == 59
    
    def test_parse_empty_returns_none(self):
        """Test that empty string returns None."""
        from scrapers.WFA_causeway import WFACausewayScraper
        
        scraper = WFACausewayScraper.__new__(WFACausewayScraper)
        
        result = scraper._parse_mod_date("")
        
        assert result is None


class TestParseFolderPageFiltering:
    """Test the _parse_folder_page method's date filtering logic."""
    
    def get_mock_scraper(self):
        """Create a mock scraper instance for testing."""
        from scrapers.WFA_causeway import WFACausewayScraper
        
        scraper = WFACausewayScraper.__new__(WFACausewayScraper)
        scraper.base_url = "https://groups.wi-fi.org"
        return scraper
    
    def create_test_html(self, documents):
        """
        Create test HTML mimicking the Causeway portal structure.
        
        Args:
            documents: List of (title, date_string) tuples, newest first
        """
        rows = []
        for title, date_str in documents:
            rows.append(f'''
            <tr>
                <td>
                    <span class="document-name">
                        <a href="/wg/WiFi8MTG/document/12345">{title}</a>
                    </span>
                </td>
                <td><strong>{date_str}</strong></td>
            </tr>
            ''')
        
        html = f'''
        <html>
        <body>
            <table>
                {''.join(rows)}
            </table>
        </body>
        </html>
        '''
        return html
    
    def test_filtering_with_datetime_last_scraped(self):
        """Test filtering works when last_scraped_at is a proper datetime."""
        scraper = self.get_mock_scraper()
        
        # Documents on portal (newest first, as portal displays)
        html = self.create_test_html([
            ("New Doc Jan 8", "Jan 8, 2026"),
            ("New Doc Jan 7", "Jan 7, 2026"),
            ("Old Doc Jan 5", "Jan 5, 2026"),
            ("Old Doc Jan 4", "Jan 4, 2026"),
        ])
        soup = BeautifulSoup(html, 'html.parser')
        
        # Scrape ran on Jan 6
        last_scraped = datetime(2026, 1, 6, 3, 0, 0, tzinfo=timezone.utc)
        
        subfolders, documents = scraper._parse_folder_page(
            soup, 
            "https://groups.wi-fi.org/wg/WiFi8MTG/document",
            last_scraped_at=last_scraped
        )
        
        # Should get Jan 7 and Jan 8 docs (newer than Jan 6 scrape)
        # Should stop at Jan 5 doc (older than scrape)
        assert len(documents) == 2
        titles = [doc.title for doc, _ in documents]
        assert "New Doc Jan 8" in titles
        assert "New Doc Jan 7" in titles
        assert "Old Doc Jan 5" not in titles
    
    def test_filtering_fails_with_string_last_scraped(self):
        """
        Demonstrate the bug: filtering fails when last_scraped_at is a string.
        
        This test shows why we needed the fix - the comparison raises TypeError.
        """
        scraper = self.get_mock_scraper()
        
        html = self.create_test_html([
            ("New Doc Jan 7", "Jan 7, 2026"),
            ("Old Doc Jan 5", "Jan 5, 2026"),
        ])
        soup = BeautifulSoup(html, 'html.parser')
        
        # Bug: last_scraped_at as string (how it comes from Neo4j without fix)
        last_scraped_string = "2026-01-06T03:00:00.000000"
        
        # This will raise TypeError during comparison
        with pytest.raises(TypeError):
            scraper._parse_folder_page(
                soup,
                "https://groups.wi-fi.org/wg/WiFi8MTG/document", 
                last_scraped_at=last_scraped_string
            )


class TestIntegrationScenario:
    """
    Integration test for the complete scenario that was failing in production.
    """
    
    def test_production_scenario_jan_6_7_documents(self):
        """
        Reproduce the exact production issue:
        - Initial scrape: Jan 6 at 01:38 AM, got 149 resources
        - Jan 6 doc posted at 12:00 PM (after scrape)
        - Jan 7 doc posted at 6:06 PM
        - Daily scrapes on Jan 7, 8, 9 got 0 resources (bug!)
        
        With the fix, these documents should be discovered.
        """
        from scrapers.WFA_causeway import _parse_last_scraped_at, WFACausewayScraper
        
        # This is exactly what came from Neo4j
        neo4j_last_scraped = "2026-01-06T01:38:05.739738"
        
        # Parse it with our fix
        last_scraped_at = _parse_last_scraped_at(neo4j_last_scraped)
        
        assert last_scraped_at is not None
        assert isinstance(last_scraped_at, datetime)
        
        # Portal dates get parsed to end-of-day
        jan_6_doc_mod = datetime(2026, 1, 6, 23, 59, 59, tzinfo=timezone.utc)
        jan_7_doc_mod = datetime(2026, 1, 7, 23, 59, 59, tzinfo=timezone.utc)
        
        # Both documents should be considered "newer" than the scrape
        # because their parsed mod dates (23:59:59) are after 01:38:05
        assert jan_6_doc_mod > last_scraped_at, "Jan 6 doc (posted after scrape) should be newer"
        assert jan_7_doc_mod > last_scraped_at, "Jan 7 doc should be newer"
        
        # The filter logic: skip if mod_date < last_scraped_at
        should_skip_jan6 = jan_6_doc_mod < last_scraped_at
        should_skip_jan7 = jan_7_doc_mod < last_scraped_at
        
        assert should_skip_jan6 is False, "Jan 6 doc should NOT be skipped"
        assert should_skip_jan7 is False, "Jan 7 doc should NOT be skipped"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
