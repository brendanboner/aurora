"""Tests for QueryParser - Entity and filter extraction."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

from src.services.query_parser import QueryParser, ParsedQuery


class TestQueryParserHeuristic:
    """Test heuristic query parsing (no LLM)."""
    
    @pytest.fixture
    def parser(self):
        return QueryParser()
    
    def test_extract_wifi_topics(self, parser):
        """Test extraction of Wi-Fi topics."""
        result = parser._parse_heuristic("What's new in Wi-Fi 7 and Wi-Fi 6E?")
        
        assert "Wi-Fi 7" in result.topics
        assert "Wi-Fi 6E" in result.topics
    
    def test_extract_standard_topics(self, parser):
        """Test extraction of IEEE standard topics."""
        result = parser._parse_heuristic("Updates on 802.11be and 802.11ax")
        
        assert "802.11be" in result.topics
        assert "802.11ax" in result.topics
    
    def test_extract_organizations(self, parser):
        """Test extraction of organizations."""
        result = parser._parse_heuristic("What did Wi-Fi Alliance and IEEE announce?")
        
        assert "Wi-Fi Alliance" in result.organizations
        assert "IEEE" in result.organizations
    
    def test_extract_tech_companies(self, parser):
        """Test extraction of tech company names."""
        result = parser._parse_heuristic("Qualcomm and Intel announcements")
        
        assert "Qualcomm" in result.organizations
        assert "Intel" in result.organizations
    
    def test_extract_iso_dates(self, parser):
        """Test extraction of ISO format dates."""
        start, end = parser._extract_dates_heuristic(
            "Documents from 2024-01-15 to 2024-02-15"
        )
        
        assert start == "2024-01-15"
        assert end == "2024-02-15"
    
    def test_extract_relative_date_last_week(self, parser):
        """Test extraction of 'last week' date range."""
        start, end = parser._extract_dates_heuristic("News from last week")
        
        assert start is not None
        assert end is not None
        
        # Check dates are reasonable
        today = datetime.now()
        week_ago = (today - timedelta(days=7)).strftime('%Y-%m-%d')
        assert start == week_ago
    
    def test_extract_relative_date_last_month(self, parser):
        """Test extraction of 'last month' date range."""
        start, end = parser._extract_dates_heuristic("Updates from last month")
        
        assert start is not None
        
        today = datetime.now()
        month_ago = (today - timedelta(days=30)).strftime('%Y-%m-%d')
        assert start == month_ago
    
    def test_extract_relative_date_latest(self, parser):
        """Test extraction of 'latest' implies recent."""
        start, end = parser._extract_dates_heuristic("What's the latest on Wi-Fi 7?")
        
        assert start is not None
        # "latest" should default to last 30 days
        today = datetime.now()
        month_ago = (today - timedelta(days=30)).strftime('%Y-%m-%d')
        assert start == month_ago
    
    def test_extract_category_press_release(self, parser):
        """Test extraction of document category."""
        result = parser._parse_heuristic("Show me press releases about Wi-Fi 7")
        
        assert result.category == "press release"
    
    def test_extract_category_whitepaper(self, parser):
        """Test extraction of whitepaper category."""
        result = parser._parse_heuristic("Find whitepapers on 6 GHz")
        
        assert result.category == "whitepaper"
    
    def test_extract_keywords(self, parser):
        """Test extraction of significant keywords."""
        result = parser._parse_heuristic("certification program for wireless devices")
        
        assert len(result.keywords) > 0
        # Should extract meaningful words, not stopwords
        assert "certification" in result.keywords or "program" in result.keywords or "wireless" in result.keywords
    
    def test_keywords_exclude_stopwords(self, parser):
        """Test that stopwords are excluded from keywords."""
        result = parser._parse_heuristic("What is the latest news about this topic?")
        
        for keyword in result.keywords:
            assert keyword not in ["what", "is", "the", "about", "this"]
    
    def test_no_duplicate_keywords(self, parser):
        """Test that keywords are deduplicated."""
        result = parser._parse_heuristic("certification certification certification")
        
        # Count occurrences
        count = result.keywords.count("certification")
        assert count <= 1


class TestQueryParserWithLLM:
    """Test LLM-based query parsing."""
    
    @pytest.fixture
    def parser(self):
        return QueryParser()
    
    @pytest.mark.asyncio
    async def test_parse_falls_back_to_heuristic_when_llm_unavailable(self, parser):
        """Test fallback to heuristic when LLM is not available."""
        with patch('src.services.query_parser.get_llm_client', return_value=None):
            result = await parser.parse("What's new in Wi-Fi 7?")
            
            assert isinstance(result, ParsedQuery)
            assert result.tokens_used == 0
    
    @pytest.mark.asyncio
    async def test_parse_with_llm_response(self, parser):
        """Test successful LLM parsing."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '''
        {
            "topics": ["Wi-Fi 7", "802.11be"],
            "organizations": ["Wi-Fi Alliance"],
            "people": [],
            "start_date": "2024-01-01",
            "end_date": null,
            "category": null,
            "doc_type": null,
            "keywords": ["certification", "launch"]
        }
        '''
        mock_response.tokens_used = 150
        
        with patch('src.services.query_parser.get_llm_client', return_value=mock_client):
            with patch('src.services.query_parser.call_llm', new_callable=AsyncMock, return_value=mock_response):
                result = await parser.parse("Wi-Fi 7 certification launch updates")
                
                assert "Wi-Fi 7" in result.topics
                assert "802.11be" in result.topics
                assert "Wi-Fi Alliance" in result.organizations
                assert result.start_date == "2024-01-01"
                assert result.tokens_used == 150
    
    @pytest.mark.asyncio
    async def test_parse_handles_llm_error(self, parser):
        """Test fallback when LLM call fails."""
        mock_client = MagicMock()
        
        with patch('src.services.query_parser.get_llm_client', return_value=mock_client):
            with patch('src.services.query_parser.call_llm', new_callable=AsyncMock, side_effect=Exception("LLM error")):
                result = await parser.parse("What's new in Wi-Fi 7?")
                
                # Should fall back to heuristic
                assert isinstance(result, ParsedQuery)
                assert result.tokens_used == 0


class TestParsedQueryStructure:
    """Test ParsedQuery data structure."""
    
    def test_parsed_query_has_all_fields(self):
        """Test that ParsedQuery has all required fields."""
        query = ParsedQuery(
            topics=["Wi-Fi 7"],
            organizations=["IEEE"],
            people=["John Doe"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            category="press release",
            doc_type="announcement",
            keywords=["certification"],
            tokens_used=100
        )
        
        assert query.topics == ["Wi-Fi 7"]
        assert query.organizations == ["IEEE"]
        assert query.people == ["John Doe"]
        assert query.start_date == "2024-01-01"
        assert query.end_date == "2024-12-31"
        assert query.category == "press release"
        assert query.doc_type == "announcement"
        assert query.keywords == ["certification"]
        assert query.tokens_used == 100
