"""Tests for QueryRouter - Intent classification."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.services.query_router import QueryRouter, IntentResult
from src.models.response import QueryIntent


class TestQueryRouterHeuristic:
    """Test heuristic intent classification (no LLM)."""
    
    @pytest.fixture
    def router(self):
        return QueryRouter()
    
    def test_entity_focused_detection(self, router):
        """Test that entity-focused queries are detected."""
        queries = [
            "What did Wi-Fi Alliance announce last week?",
            "Show me press releases from IEEE",
            "Intel's latest updates",
        ]
        
        for query in queries:
            result = router._classify_heuristic(query)
            assert result.intent == QueryIntent.ENTITY_FOCUSED, f"Failed for: {query}"
    
    def test_relationship_query_detection(self, router):
        """Test that relationship queries are detected."""
        queries = [
            "Who is working on 802.11be?",
            "Which companies support Matter?",
            "Who collaborates with IEEE on 6 GHz?",
        ]
        
        for query in queries:
            result = router._classify_heuristic(query)
            assert result.intent == QueryIntent.RELATIONSHIP_QUERY, f"Failed for: {query}"
    
    def test_trend_analysis_detection(self, router):
        """Test that trend analysis queries are detected."""
        queries = [
            "What topics are trending this month?",
            "How has Wi-Fi 6 adoption changed over time?",
            "Show me the growth in 6 GHz spectrum news",
        ]
        
        for query in queries:
            result = router._classify_heuristic(query)
            assert result.intent == QueryIntent.TREND_ANALYSIS, f"Failed for: {query}"
    
    def test_comparative_detection(self, router):
        """Test that comparative queries are detected."""
        queries = [
            "Compare Wi-Fi 6E and Wi-Fi 7",
            "Differences between Thread and Zigbee",
            "Wi-Fi 6 vs Wi-Fi 7 features",
        ]
        
        for query in queries:
            result = router._classify_heuristic(query)
            assert result.intent == QueryIntent.COMPARATIVE, f"Failed for: {query}"
    
    def test_topic_discovery_default(self, router):
        """Test that topic discovery is the default for general queries."""
        queries = [
            "What's the latest in Wi-Fi 7?",
            "Tell me about 6 GHz spectrum",
            "Updates on MLO technology",
        ]
        
        for query in queries:
            result = router._classify_heuristic(query)
            assert result.intent == QueryIntent.TOPIC_DISCOVERY, f"Failed for: {query}"
    
    def test_entity_extraction(self, router):
        """Test that entities are extracted from queries."""
        query = "What did Wi-Fi Alliance announce about Wi-Fi 7?"
        result = router._classify_heuristic(query)
        
        assert "Wi-Fi Alliance" in result.entities_detected
        assert "Wi-Fi 7" in result.entities_detected
    
    def test_requires_temporal_flag(self, router):
        """Test that temporal requirement is detected."""
        query = "What's the latest news on 802.11be?"
        result = router._classify_heuristic(query)
        
        assert result.requires_temporal is True
    
    def test_confidence_score(self, router):
        """Test that confidence scores are reasonable."""
        result = router._classify_heuristic("Compare Wi-Fi 6 and Wi-Fi 7")
        
        assert 0.0 <= result.confidence <= 1.0
        assert result.confidence >= 0.5  # Should have reasonable confidence


class TestQueryRouterWithLLM:
    """Test LLM-based intent classification."""
    
    @pytest.fixture
    def router(self):
        return QueryRouter()
    
    @pytest.mark.asyncio
    async def test_classify_falls_back_to_heuristic_when_llm_unavailable(self, router):
        """Test fallback to heuristic when LLM is not available."""
        with patch('src.services.query_router.get_llm_client', return_value=None):
            result = await router.classify_intent("What's new in Wi-Fi 7?")
            
            assert isinstance(result, IntentResult)
            assert result.tokens_used == 0  # No LLM tokens used
    
    @pytest.mark.asyncio
    async def test_classify_with_llm_response(self, router):
        """Test successful LLM classification."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"intent": "topic_discovery", "confidence": 0.9, "entities_detected": ["Wi-Fi 7"], "requires_temporal": true, "requires_graph_traversal": false}'
        mock_response.tokens_used = 100
        
        with patch('src.services.query_router.get_llm_client', return_value=mock_client):
            with patch('src.services.query_router.call_llm', new_callable=AsyncMock, return_value=mock_response):
                result = await router.classify_intent("What's new in Wi-Fi 7?")
                
                assert result.intent == QueryIntent.TOPIC_DISCOVERY
                assert result.confidence == 0.9
                assert "Wi-Fi 7" in result.entities_detected
                assert result.tokens_used == 100
    
    @pytest.mark.asyncio
    async def test_classify_handles_llm_error(self, router):
        """Test fallback when LLM call fails."""
        mock_client = MagicMock()
        
        with patch('src.services.query_router.get_llm_client', return_value=mock_client):
            with patch('src.services.query_router.call_llm', new_callable=AsyncMock, side_effect=Exception("LLM error")):
                result = await router.classify_intent("What's new in Wi-Fi 7?")
                
                # Should fall back to heuristic
                assert isinstance(result, IntentResult)
                assert result.tokens_used == 0


class TestRetrievalStrategies:
    """Test retrieval strategy selection."""
    
    @pytest.fixture
    def router(self):
        return QueryRouter()
    
    def test_keyword_always_included(self, router):
        """Test that keyword search is always included."""
        for intent in QueryIntent:
            strategies = router.get_retrieval_strategies(intent)
            assert "keyword" in strategies
    
    def test_strategies_return_list(self, router):
        """Test that strategies are returned as a list."""
        strategies = router.get_retrieval_strategies(QueryIntent.TOPIC_DISCOVERY)
        assert isinstance(strategies, list)
        assert len(strategies) > 0
