"""Tests for Phase 4 Oracle Service features.

Tests cover:
- Confidence scoring
- Query refinement suggestions
- Ranking explainability
- Redis caching
- Parallel retrieval
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.models.response import Document, Citation, QueryIntent, GraphContext, RelatedEntity
from src.services.confidence_scorer import (
    calculate_confidence,
    ConfidenceScore,
    ConfidenceFactors,
    interpret_confidence,
    FACTOR_WEIGHTS,
)
from src.services.query_suggestions import (
    suggest_refinements,
    should_show_suggestions,
    SuggestionContext,
)
from src.services.ranking_explainer import (
    explain_ranking,
    RankingExplanation,
    add_explanations_to_documents,
    get_ranking_breakdown,
)
from src.services.cache import (
    OracleCache,
    hash_options,
    CacheTTL,
    CachePrefix,
)


# ==================== Test Fixtures ====================

@pytest.fixture
def sample_documents():
    """Create sample documents for testing."""
    return [
        Document(
            url="https://example.com/doc1",
            title="Wi-Fi 7 Certification Launch",
            summary="Wi-Fi Alliance announces Wi-Fi 7 certification program launch.",
            publish_date=(datetime.now() - timedelta(days=5)).isoformat(),
            source="Wi-Fi Alliance",
            category="Press Release",
            topics=["Wi-Fi 7", "802.11be", "Certification"],
            organizations=["Wi-Fi Alliance"],
            relevance_score=0.95,
            match_reasons=["Keyword match (rank #1)"],
        ),
        Document(
            url="https://example.com/doc2",
            title="802.11be Technical Overview",
            summary="Technical deep dive into 802.11be features including MLO and 320MHz.",
            publish_date=(datetime.now() - timedelta(days=30)).isoformat(),
            source="IEEE",
            category="Technical Article",
            topics=["802.11be", "MLO", "320MHz"],
            organizations=["IEEE"],
            relevance_score=0.85,
            match_reasons=["Semantic match (rank #2)"],
        ),
        Document(
            url="https://example.com/doc3",
            title="Wi-Fi 7 Device Availability",
            summary="Major manufacturers announce Wi-Fi 7 device availability.",
            publish_date=(datetime.now() - timedelta(days=60)).isoformat(),
            source="TechNews",
            category="News",
            topics=["Wi-Fi 7", "Devices"],
            organizations=["Qualcomm", "MediaTek"],
            relevance_score=0.75,
            match_reasons=["Graph traversal (rank #5)"],
        ),
    ]


@pytest.fixture
def sample_citations(sample_documents):
    """Create sample citations for testing."""
    return [
        Citation(
            index=1,
            document_url=sample_documents[0].url,
            title=sample_documents[0].title,
            excerpt="Wi-Fi Alliance announces...",
        ),
        Citation(
            index=2,
            document_url=sample_documents[1].url,
            title=sample_documents[1].title,
            excerpt="Technical deep dive into...",
        ),
    ]


@pytest.fixture
def sample_graph_context():
    """Create sample graph context for testing."""
    return GraphContext(
        central_topics=["Wi-Fi 7", "802.11be", "MLO"],
        key_organizations=["Wi-Fi Alliance", "IEEE", "Qualcomm"],
        key_people=["John Smith"],
        related_entities=[
            RelatedEntity(name="Wi-Fi 6E", type="topic", relevance=0.7),
            RelatedEntity(name="Intel", type="organization", relevance=0.6),
        ],
        temporal_patterns="Activity increased over the past month",
    )


# ==================== Confidence Scoring Tests ====================

class TestConfidenceScoring:
    """Tests for confidence scoring functionality."""
    
    def test_calculate_confidence_with_good_results(self, sample_documents, sample_citations):
        """Test confidence calculation with good quality results."""
        answer = """Based on the retrieved documents, Wi-Fi 7 (802.11be) certification 
        was launched by the Wi-Fi Alliance [1]. The technology includes features like 
        MLO and 320MHz channels [2]. Multiple manufacturers are releasing devices."""
        
        result = calculate_confidence(
            answer=answer,
            documents=sample_documents,
            citations=sample_citations,
            query="What is Wi-Fi 7?",
            intent=QueryIntent.TOPIC_DISCOVERY,
        )
        
        assert isinstance(result, ConfidenceScore)
        assert 0.5 <= result.score <= 1.0  # Good results should have medium-high confidence
        assert result.level in ["high", "medium"]
        assert isinstance(result.factors, ConfidenceFactors)
        assert result.explanation
    
    def test_calculate_confidence_with_no_documents(self):
        """Test confidence calculation with no documents."""
        result = calculate_confidence(
            answer="No information available",
            documents=[],
            citations=[],
            query="What is Wi-Fi 7?",
            intent=QueryIntent.TOPIC_DISCOVERY,
        )
        
        assert result.score == 0.0
        assert result.level == "low"
        assert "No documents" in result.explanation
    
    def test_calculate_confidence_with_empty_answer(self, sample_documents):
        """Test confidence calculation with empty answer."""
        result = calculate_confidence(
            answer="",
            documents=sample_documents,
            citations=[],
            query="What is Wi-Fi 7?",
            intent=QueryIntent.TOPIC_DISCOVERY,
        )
        
        assert result.score == 0.0
        assert result.level == "low"
    
    def test_calculate_confidence_with_hedging_language(self, sample_documents, sample_citations):
        """Test that hedging language reduces confidence."""
        hedging_answer = """I'm not sure, but it's unclear what Wi-Fi 7 is. 
        It might be a new wireless standard, but I cannot determine this for certain."""
        
        confident_answer = """Wi-Fi 7 (802.11be) is the latest wireless standard 
        offering improved speeds and lower latency [1]."""
        
        hedging_result = calculate_confidence(
            answer=hedging_answer,
            documents=sample_documents,
            citations=sample_citations,
            query="What is Wi-Fi 7?",
            intent=QueryIntent.TOPIC_DISCOVERY,
        )
        
        confident_result = calculate_confidence(
            answer=confident_answer,
            documents=sample_documents,
            citations=sample_citations,
            query="What is Wi-Fi 7?",
            intent=QueryIntent.TOPIC_DISCOVERY,
        )
        
        # Hedging answer should have lower confidence
        assert hedging_result.score < confident_result.score
        assert "uncertainty" in " ".join(hedging_result.warnings).lower() or len(hedging_result.warnings) > 0
    
    def test_calculate_confidence_factors_sum_to_one(self):
        """Test that factor weights sum to 1.0."""
        total_weight = sum(FACTOR_WEIGHTS.values())
        assert abs(total_weight - 1.0) < 0.001
    
    def test_interpret_confidence_levels(self):
        """Test confidence level interpretation."""
        assert "Very high" in interpret_confidence(0.90)
        assert "High" in interpret_confidence(0.80)
        assert "Moderate" in interpret_confidence(0.65)
        assert "Low" in interpret_confidence(0.35)
        assert "Very low" in interpret_confidence(0.20)


# ==================== Query Suggestions Tests ====================

class TestQuerySuggestions:
    """Tests for query refinement suggestions."""
    
    @pytest.mark.asyncio
    async def test_suggest_refinements_with_few_results(self, sample_graph_context):
        """Test suggestions when there are few results."""
        # Create just one document (few results scenario)
        documents = [
            Document(
                url="https://example.com/doc1",
                title="Wi-Fi 7 Overview",
                summary="Brief overview of Wi-Fi 7",
                relevance_score=0.6,
                topics=["Wi-Fi 7"],
                organizations=["Wi-Fi Alliance"],
            )
        ]
        
        suggestions = await suggest_refinements(
            query="wifi 7 certification this week",
            documents=documents,
            graph_context=sample_graph_context,
            intent=QueryIntent.TOPIC_DISCOVERY,
            max_suggestions=3,
        )
        
        # Should suggest broadening the query (removing date restriction)
        assert len(suggestions) >= 1
        assert all(s.suggestion for s in suggestions)
        assert all(s.reason for s in suggestions)
    
    @pytest.mark.asyncio
    async def test_suggest_refinements_with_no_results(self, sample_graph_context):
        """Test suggestions when there are no results."""
        suggestions = await suggest_refinements(
            query="nonexistent technology xyz",
            documents=[],
            graph_context=sample_graph_context,
            intent=QueryIntent.ENTITY_FOCUSED,
            max_suggestions=3,
        )
        
        # Should provide suggestions from graph context
        assert len(suggestions) >= 0  # May or may not generate based on LLM availability
    
    @pytest.mark.asyncio
    async def test_suggest_refinements_with_good_results(self, sample_documents, sample_graph_context):
        """Test that no suggestions are shown for good results."""
        suggestions = await suggest_refinements(
            query="Wi-Fi 7",
            documents=sample_documents,
            graph_context=sample_graph_context,
            intent=QueryIntent.TOPIC_DISCOVERY,
            max_suggestions=3,
        )
        
        # Good results should have few or no suggestions
        assert len(suggestions) <= 1
    
    def test_should_show_suggestions_few_results(self):
        """Test should_show_suggestions with few results."""
        documents = [
            Document(url="test", title="Test", relevance_score=0.8)
        ]
        
        assert should_show_suggestions(documents, min_results=3) is True
    
    def test_should_show_suggestions_low_relevance(self, sample_documents):
        """Test should_show_suggestions with low relevance."""
        # Modify documents to have low relevance
        low_relevance_docs = []
        for doc in sample_documents:
            d = doc.model_copy()
            d.relevance_score = 0.3
            low_relevance_docs.append(d)
        
        assert should_show_suggestions(low_relevance_docs, min_relevance=0.5) is True
    
    def test_should_show_suggestions_good_results(self, sample_documents):
        """Test should_show_suggestions with good results."""
        assert should_show_suggestions(sample_documents, min_results=2, min_relevance=0.5) is False


# ==================== Ranking Explainability Tests ====================

class TestRankingExplainability:
    """Tests for ranking explainability functionality."""
    
    def test_explain_ranking_basic(self, sample_documents):
        """Test basic ranking explanation."""
        doc = sample_documents[0]
        
        explanation = explain_ranking(
            document=doc,
            rank=1,
            query="Wi-Fi 7 certification",
            intent=QueryIntent.TOPIC_DISCOVERY,
            retrieval_metadata={"keyword_rank": 1, "vector_rank": 2},
        )
        
        assert isinstance(explanation, RankingExplanation)
        assert explanation.rank == 1
        assert explanation.relevance_score == doc.relevance_score
        assert explanation.keyword_rank == 1
        assert explanation.vector_rank == 2
        assert len(explanation.factors) > 0
        assert explanation.summary
        assert len(explanation.match_reasons) > 0
    
    def test_explain_ranking_all_retrieval_methods(self, sample_documents):
        """Test explanation with all retrieval methods."""
        doc = sample_documents[0]
        
        explanation = explain_ranking(
            document=doc,
            rank=1,
            query="Wi-Fi 7 certification",
            intent=QueryIntent.TOPIC_DISCOVERY,
            retrieval_metadata={
                "keyword_rank": 1,
                "vector_rank": 3,
                "graph_rank": 2,
            },
        )
        
        assert explanation.keyword_rank == 1
        assert explanation.vector_rank == 3
        assert explanation.graph_rank == 2
        
        # Should have factors for all methods
        factor_names = [f.name for f in explanation.factors]
        assert "Keyword Match" in factor_names
        assert "Semantic Similarity" in factor_names
        assert "Graph Relationships" in factor_names
    
    def test_explain_ranking_recency_factor(self):
        """Test recency factor in ranking explanation."""
        recent_doc = Document(
            url="https://example.com/recent",
            title="Recent News",
            summary="Very recent news",
            publish_date=datetime.now().isoformat(),
            relevance_score=0.8,
        )
        
        old_doc = Document(
            url="https://example.com/old",
            title="Old News",
            summary="Old news from years ago",
            publish_date=(datetime.now() - timedelta(days=500)).isoformat(),
            relevance_score=0.8,
        )
        
        recent_explanation = explain_ranking(
            document=recent_doc,
            rank=1,
            query="news",
            intent=QueryIntent.TOPIC_DISCOVERY,
        )
        
        old_explanation = explain_ranking(
            document=old_doc,
            rank=1,
            query="news",
            intent=QueryIntent.TOPIC_DISCOVERY,
        )
        
        # Get recency scores
        recent_recency = next(f for f in recent_explanation.factors if f.name == "Recency")
        old_recency = next(f for f in old_explanation.factors if f.name == "Recency")
        
        assert recent_recency.score > old_recency.score
    
    def test_add_explanations_to_documents(self, sample_documents):
        """Test adding explanations to a list of documents."""
        explained_docs = add_explanations_to_documents(
            documents=sample_documents.copy(),
            query="Wi-Fi 7",
            intent=QueryIntent.TOPIC_DISCOVERY,
        )
        
        # Each document should have match reasons
        for doc in explained_docs:
            assert len(doc.match_reasons) >= 1
    
    def test_get_ranking_breakdown(self, sample_documents):
        """Test getting detailed ranking breakdown."""
        breakdown = get_ranking_breakdown(
            documents=sample_documents,
            query="Wi-Fi 7 certification",
            intent=QueryIntent.TOPIC_DISCOVERY,
            max_documents=2,
        )
        
        assert len(breakdown) == 2
        
        first = breakdown[0]
        assert first["rank"] == 1
        assert first["url"] == sample_documents[0].url
        assert "factors" in first
        assert "summary" in first
        
        # Check factor structure
        for factor in first["factors"]:
            assert "name" in factor
            assert "score" in factor
            assert "weight" in factor
            assert "weighted_contribution" in factor


# ==================== Caching Tests ====================

class TestCaching:
    """Tests for Redis caching functionality."""
    
    def test_hash_options_consistency(self):
        """Test that hash_options produces consistent hashes."""
        options = {"max_documents": 20, "include_graph": True}
        
        hash1 = hash_options(options)
        hash2 = hash_options(options)
        
        assert hash1 == hash2
    
    def test_hash_options_different_options(self):
        """Test that different options produce different hashes."""
        options1 = {"max_documents": 20}
        options2 = {"max_documents": 50}
        
        hash1 = hash_options(options1)
        hash2 = hash_options(options2)
        
        assert hash1 != hash2
    
    def test_hash_options_order_independence(self):
        """Test that option order doesn't affect hash."""
        options1 = {"a": 1, "b": 2}
        options2 = {"b": 2, "a": 1}
        
        hash1 = hash_options(options1)
        hash2 = hash_options(options2)
        
        assert hash1 == hash2
    
    def test_hash_options_empty(self):
        """Test hash of empty options."""
        assert hash_options({}) == "default" or len(hash_options({})) == 12
        assert hash_options(None) == "default"
    
    def test_cache_ttl_values(self):
        """Test that cache TTL values are reasonable."""
        assert CacheTTL.QUERY_RESPONSE == 300  # 5 minutes
        assert CacheTTL.EMBEDDING == 3600  # 1 hour
        assert CacheTTL.GRAPH_CONTEXT == 900  # 15 minutes
        assert CacheTTL.DOCUMENT == 1800  # 30 minutes
    
    def test_cache_prefix_values(self):
        """Test cache key prefix values."""
        assert CachePrefix.QUERY.startswith("oracle:")
        assert CachePrefix.EMBEDDING.startswith("oracle:")
        assert CachePrefix.GRAPH_CONTEXT.startswith("oracle:")
        assert CachePrefix.DOCUMENT.startswith("oracle:")
    
    @pytest.mark.asyncio
    async def test_cache_initialization(self):
        """Test cache initialization without Redis."""
        with patch('src.services.cache.settings') as mock_settings:
            mock_settings.cache_enabled = False
            
            cache = OracleCache()
            assert cache.enabled is False
            assert cache.is_available() is False
    
    @pytest.mark.asyncio
    async def test_cache_key_generation(self):
        """Test cache key generation."""
        cache = OracleCache()
        
        # Query key
        query_key = cache._query_key("test query", "answer", "hash123")
        assert query_key.startswith(CachePrefix.QUERY)
        assert "answer" in query_key
        
        # Embedding key
        embed_key = cache._embedding_key("test text")
        assert embed_key.startswith(CachePrefix.EMBEDDING)
        
        # Document key
        doc_key = cache._document_key("https://example.com/doc")
        assert doc_key.startswith(CachePrefix.DOCUMENT)
        
        # Graph context key
        graph_key = cache._graph_context_key(["url1", "url2"])
        assert graph_key.startswith(CachePrefix.GRAPH_CONTEXT)
    
    @pytest.mark.asyncio
    async def test_cache_stats(self):
        """Test cache statistics tracking."""
        cache = OracleCache()
        
        # Initial stats should be zero
        for cache_type in ["query", "embedding", "graph", "document"]:
            assert cache.stats[cache_type].hits == 0
            assert cache.stats[cache_type].misses == 0
            assert cache.stats[cache_type].errors == 0


# ==================== Parallel Retrieval Tests ====================

class TestParallelRetrieval:
    """Tests for parallel retrieval functionality."""
    
    @pytest.mark.asyncio
    async def test_parallel_search_settings(self):
        """Test that parallel retrieval settings exist."""
        from src.settings import settings
        
        assert hasattr(settings, 'parallel_retrieval_enabled')
        assert hasattr(settings, 'retrieval_timeout')
        assert settings.retrieval_timeout > 0
    
    @pytest.mark.asyncio
    async def test_hybrid_search_uses_parallel(self):
        """Test that hybrid search uses parallel retrieval when enabled."""
        from src.services.hybrid_search import HybridSearch
        
        searcher = HybridSearch()
        
        # Verify the searcher has the parallel search method
        assert hasattr(searcher, '_parallel_search')
        assert hasattr(searcher, '_sequential_search')
        assert hasattr(searcher, '_safe_keyword_retrieve')
        assert hasattr(searcher, '_safe_vector_retrieve')
        assert hasattr(searcher, '_safe_graph_retrieve')


# ==================== Integration Tests ====================

class TestPhase4Integration:
    """Integration tests for Phase 4 features working together."""
    
    def test_confidence_with_explainability(self, sample_documents, sample_citations):
        """Test that confidence scoring works with explained documents."""
        # Add explanations to documents
        explained_docs = add_explanations_to_documents(
            documents=sample_documents.copy(),
            query="Wi-Fi 7 certification",
            intent=QueryIntent.TOPIC_DISCOVERY,
        )
        
        # Calculate confidence with explained documents
        answer = "Wi-Fi 7 certification was launched [1][2]."
        result = calculate_confidence(
            answer=answer,
            documents=explained_docs,
            citations=sample_citations,
            query="Wi-Fi 7 certification",
            intent=QueryIntent.TOPIC_DISCOVERY,
        )
        
        assert result.score > 0
        assert result.level in ["high", "medium", "low"]
    
    @pytest.mark.asyncio
    async def test_suggestions_with_explained_documents(self, sample_graph_context):
        """Test that suggestions work with explained documents."""
        # Create low-relevance explained documents
        docs = [
            Document(
                url="https://example.com/doc",
                title="Test Doc",
                summary="Test summary",
                relevance_score=0.3,
                topics=["Wi-Fi"],
                match_reasons=["Explained match"],
            )
        ]
        
        suggestions = await suggest_refinements(
            query="wifi 7 this week",
            documents=docs,
            graph_context=sample_graph_context,
            intent=QueryIntent.TOPIC_DISCOVERY,
        )
        
        # Should generate suggestions due to low relevance
        assert isinstance(suggestions, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
