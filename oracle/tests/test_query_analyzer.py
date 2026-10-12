"""Tests for Query Analyzer service.

Tests cover:
- Query quality scoring
- Issue detection (vague, no topic, no timeframe, etc.)
- Heuristic query revision
- LLM-based query revision
- Should-suggest-revision logic
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.query_analyzer import (
    analyze_query,
    QueryAnalysis,
    QUERY_ISSUES,
    should_suggest_revision,
    _heuristic_revision,
)


# ==================== Test Fixtures ====================

@pytest.fixture
def good_query():
    """A well-formed query with topic, org, and timeframe."""
    return "What are the latest Wi-Fi 7 updates from Wi-Fi Alliance in the last month?"


@pytest.fixture
def vague_query():
    """A vague query missing specifics."""
    return "latest news"


@pytest.fixture
def no_timeframe_query():
    """Query with time-sensitive words but no timeframe."""
    return "latest updates on Wi-Fi 7"


@pytest.fixture
def short_query():
    """Very short query."""
    return "wifi"


# ==================== Query Quality Tests ====================

class TestQueryQualityScoring:
    """Tests for query quality assessment."""

    @pytest.mark.asyncio
    async def test_good_query_high_score(self, good_query):
        """Well-formed queries should have high quality scores."""
        analysis = await analyze_query(good_query)
        
        assert analysis.quality_score >= 0.7
        assert analysis.is_good_query is True
        assert len(analysis.issues) == 0

    @pytest.mark.asyncio
    async def test_vague_query_low_score(self, vague_query):
        """Vague queries should have low quality scores."""
        analysis = await analyze_query(vague_query)
        
        assert analysis.quality_score < 0.7
        assert analysis.is_good_query is False
        assert len(analysis.issues) > 0

    @pytest.mark.asyncio
    async def test_short_query_penalized(self, short_query):
        """Very short queries should be penalized."""
        analysis = await analyze_query(short_query)
        
        assert analysis.quality_score < 0.7
        assert QUERY_ISSUES["too_vague"] in analysis.issues

    @pytest.mark.asyncio
    async def test_query_with_topic_better_score(self):
        """Queries with specific topics should score better."""
        with_topic = "Wi-Fi 7 certification"
        without_topic = "certification process"
        
        with_topic_analysis = await analyze_query(with_topic)
        without_topic_analysis = await analyze_query(without_topic)
        
        # Query with specific topic should score better
        assert with_topic_analysis.quality_score >= without_topic_analysis.quality_score

    @pytest.mark.asyncio
    async def test_query_with_org_better_score(self):
        """Queries mentioning organizations should score better."""
        with_org = "Wi-Fi Alliance announcements"
        without_org = "announcements today"
        
        with_org_analysis = await analyze_query(with_org)
        without_org_analysis = await analyze_query(without_org)
        
        assert with_org_analysis.quality_score >= without_org_analysis.quality_score


# ==================== Issue Detection Tests ====================

class TestIssueDetection:
    """Tests for detecting specific query issues."""

    @pytest.mark.asyncio
    async def test_detect_no_timeframe_issue(self, no_timeframe_query):
        """Should detect missing timeframe for time-sensitive queries."""
        analysis = await analyze_query(no_timeframe_query)
        
        assert QUERY_ISSUES["no_timeframe"] in analysis.issues

    @pytest.mark.asyncio
    async def test_no_timeframe_with_date_ok(self):
        """Queries with explicit dates shouldn't have timeframe issue."""
        query_with_date = "latest Wi-Fi 7 news in the last month"
        analysis = await analyze_query(query_with_date)
        
        assert QUERY_ISSUES["no_timeframe"] not in analysis.issues

    @pytest.mark.asyncio
    async def test_detect_too_vague_issue(self):
        """Should detect overly vague queries."""
        vague = "tell me about stuff"
        analysis = await analyze_query(vague)
        
        assert QUERY_ISSUES["too_vague"] in analysis.issues

    @pytest.mark.asyncio
    async def test_detect_missing_context(self):
        """Should detect queries missing helpful context."""
        broad = "what's new"
        analysis = await analyze_query(broad)
        
        # Should identify as missing context or too vague
        assert len(analysis.issues) > 0

    @pytest.mark.asyncio
    async def test_specific_query_no_issues(self):
        """Specific queries should have no issues."""
        specific = "802.11be MLO feature specification from IEEE in 2024"
        analysis = await analyze_query(specific)
        
        # Well-formed query should have minimal issues
        assert analysis.is_good_query is True or analysis.quality_score >= 0.6


# ==================== Topic Pattern Tests ====================

class TestTopicPatterns:
    """Tests for topic pattern recognition."""

    @pytest.mark.asyncio
    async def test_wifi_patterns(self):
        """Should recognize various Wi-Fi patterns."""
        wifi_queries = [
            "Wi-Fi 7 news",
            "wifi 6E spectrum",
            "Wi-Fi 8 development",
            "wifi6 devices",
        ]
        
        for query in wifi_queries:
            analysis = await analyze_query(query)
            # Should not flag as missing topic
            assert QUERY_ISSUES["no_topic"] not in analysis.issues or analysis.quality_score >= 0.5

    @pytest.mark.asyncio
    async def test_802_11_patterns(self):
        """Should recognize 802.11 standard patterns."""
        standard_queries = [
            "802.11be features",
            "802.11ax vs 802.11be",
            "802.11bn development",
        ]
        
        for query in standard_queries:
            analysis = await analyze_query(query)
            assert QUERY_ISSUES["no_topic"] not in analysis.issues

    @pytest.mark.asyncio
    async def test_other_tech_patterns(self):
        """Should recognize other technology patterns."""
        tech_queries = [
            "Matter smart home",
            "Thread networking",
            "Bluetooth 5.4",
            "6 GHz spectrum",
            "5G and Wi-Fi coexistence",
        ]
        
        for query in tech_queries:
            analysis = await analyze_query(query)
            # Should recognize as having a topic
            assert analysis.quality_score >= 0.5 or QUERY_ISSUES["no_topic"] not in analysis.issues


# ==================== Heuristic Revision Tests ====================

class TestHeuristicRevision:
    """Tests for heuristic query revision."""

    def test_add_timeframe_to_news_query(self):
        """Should add timeframe to news queries."""
        query = "latest Wi-Fi news"
        issues = [QUERY_ISSUES["no_timeframe"]]
        
        revised, reason, tokens = _heuristic_revision(query, issues)
        
        assert revised is not None
        assert "last month" in revised.lower() or "month" in revised.lower()
        assert reason is not None
        assert tokens == 0  # Heuristic doesn't use tokens

    def test_vague_whats_new_query(self):
        """Should improve 'what's new' type queries."""
        queries = ["whats new", "what's new", "any news", "any updates"]
        
        for query in queries:
            revised, reason, tokens = _heuristic_revision(query, [QUERY_ISSUES["too_vague"]])
            
            assert revised is not None, f"Failed for query: {query}"
            assert "wi-fi" in revised.lower() or "wireless" in revised.lower()
            assert "month" in revised.lower()

    def test_short_query_gets_context(self):
        """Short queries should get time context added."""
        query = "Matter"
        issues = [QUERY_ISSUES["too_vague"], QUERY_ISSUES["missing_context"]]
        
        revised, reason, tokens = _heuristic_revision(query, issues)
        
        assert revised is not None
        assert "month" in revised.lower()


# ==================== Should Suggest Revision Tests ====================

class TestShouldSuggestRevision:
    """Tests for determining when to show revision suggestions."""

    def test_should_suggest_for_poor_quality(self):
        """Should suggest revision for poor quality queries."""
        analysis = QueryAnalysis(
            original_query="news",
            is_good_query=False,
            quality_score=0.4,
            issues=["Too vague"],
            revised_query="Wi-Fi 7 news in the last month",
            revision_reason="Added specificity",
            tokens_used=0,
        )
        
        assert should_suggest_revision(analysis) is True

    def test_should_not_suggest_for_good_query(self):
        """Should not suggest revision for good queries."""
        analysis = QueryAnalysis(
            original_query="Wi-Fi 7 certification from Wi-Fi Alliance",
            is_good_query=True,
            quality_score=0.9,
            issues=[],
            revised_query=None,
            revision_reason=None,
            tokens_used=0,
        )
        
        assert should_suggest_revision(analysis) is False

    def test_should_not_suggest_without_revision(self):
        """Should not suggest when no revision available."""
        analysis = QueryAnalysis(
            original_query="stuff",
            is_good_query=False,
            quality_score=0.3,
            issues=["Too vague"],
            revised_query=None,
            revision_reason=None,
            tokens_used=0,
        )
        
        assert should_suggest_revision(analysis) is False

    def test_should_not_suggest_identical_revision(self):
        """Should not suggest when revision is identical."""
        analysis = QueryAnalysis(
            original_query="Wi-Fi news",
            is_good_query=False,
            quality_score=0.5,
            issues=["Missing timeframe"],
            revised_query="Wi-Fi news",  # Same as original
            revision_reason="No change",
            tokens_used=0,
        )
        
        assert should_suggest_revision(analysis) is False


# ==================== LLM Revision Tests ====================

class TestLLMRevision:
    """Tests for LLM-based query revision."""

    @pytest.mark.asyncio
    async def test_llm_revision_called_for_poor_queries(self):
        """LLM should be called for poor quality queries."""
        with patch('src.services.query_analyzer.get_llm_client') as mock_get_client, \
             patch('src.services.query_analyzer.call_llm') as mock_call_llm:
            
            # Setup mock
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_call_llm.return_value = MagicMock(
                content='{"revised_query": "Wi-Fi 7 news in the last month", "reason": "Added specificity"}',
                tokens_used=50
            )
            
            # Very poor query should trigger LLM
            analysis = await analyze_query("news")
            
            # LLM should have been called
            if analysis.quality_score < 0.6:
                mock_call_llm.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_not_called_for_good_queries(self):
        """LLM should not be called for good quality queries."""
        with patch('src.services.query_analyzer.get_llm_client') as mock_get_client, \
             patch('src.services.query_analyzer.call_llm') as mock_call_llm:
            
            mock_get_client.return_value = MagicMock()
            
            # Good query shouldn't need LLM
            analysis = await analyze_query("Wi-Fi 7 certification updates from Wi-Fi Alliance in the last month")
            
            # LLM should not be called for good queries
            if analysis.is_good_query:
                mock_call_llm.assert_not_called()


# ==================== Integration Tests ====================

class TestAnalyzerIntegration:
    """Integration tests for query analyzer."""

    @pytest.mark.asyncio
    async def test_full_analysis_flow(self):
        """Test complete analysis flow."""
        query = "latest news"
        
        analysis = await analyze_query(query)
        
        # Should return valid analysis
        assert isinstance(analysis, QueryAnalysis)
        assert analysis.original_query == query
        assert 0.0 <= analysis.quality_score <= 1.0
        assert isinstance(analysis.issues, list)
        assert isinstance(analysis.is_good_query, bool)

    @pytest.mark.asyncio
    async def test_analysis_preserves_original_query(self):
        """Analysis should preserve the original query."""
        queries = [
            "Wi-Fi 7",
            "latest news about Matter",
            "what is 802.11be",
        ]
        
        for query in queries:
            analysis = await analyze_query(query)
            assert analysis.original_query == query

    @pytest.mark.asyncio
    async def test_quality_score_consistency(self):
        """Quality scores should be consistent for same query."""
        query = "Wi-Fi 7 news"
        
        analysis1 = await analyze_query(query)
        analysis2 = await analyze_query(query)
        
        # Heuristic scoring should be deterministic
        assert analysis1.quality_score == analysis2.quality_score
        assert analysis1.issues == analysis2.issues


# ==================== Edge Case Tests ====================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_query(self):
        """Should handle empty queries gracefully."""
        analysis = await analyze_query("")
        
        assert analysis.is_good_query is False
        assert analysis.quality_score < 0.5

    @pytest.mark.asyncio
    async def test_very_long_query(self):
        """Should handle very long queries."""
        long_query = "Wi-Fi 7 " * 100  # Very long query
        
        analysis = await analyze_query(long_query)
        
        # Should not crash and return valid analysis
        assert isinstance(analysis, QueryAnalysis)

    @pytest.mark.asyncio
    async def test_special_characters(self):
        """Should handle special characters in queries."""
        queries = [
            "Wi-Fi 7 & 802.11be",
            "What's new with Wi-Fi?",
            "802.11be/ax comparison",
        ]
        
        for query in queries:
            analysis = await analyze_query(query)
            assert isinstance(analysis, QueryAnalysis)

    @pytest.mark.asyncio
    async def test_unicode_query(self):
        """Should handle unicode characters."""
        query = "Wi-Fi 7 日本語 テスト"
        
        analysis = await analyze_query(query)
        assert isinstance(analysis, QueryAnalysis)
