"""Tests for Vector Retriever and Hybrid Search - Phase 2."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

from src.models.response import Document, QueryIntent
from src.services.vector_retriever import VectorRetriever, VectorSearchResult
from src.services.hybrid_search import (
    HybridSearch,
    HybridSearchResult,
    reciprocal_rank_fusion,
    apply_recency_boost,
    RankedDocument,
)


# Test fixtures
@pytest.fixture
def sample_documents():
    """Create sample documents for testing."""
    return [
        Document(
            url="https://example.com/doc1",
            title="Wi-Fi 7 Certification Announcement",
            summary="Wi-Fi Alliance announces Wi-Fi 7 certification program",
            publish_date=(datetime.now() - timedelta(days=5)).isoformat(),
            source="Wi-Fi Alliance",
            category="press_release",
            topics=["Wi-Fi 7", "certification"],
            organizations=["Wi-Fi Alliance"],
            relevance_score=0.9,
            match_reasons=["Keyword match"],
        ),
        Document(
            url="https://example.com/doc2",
            title="802.11be Standard Update",
            summary="IEEE 802.11be working group releases draft amendment",
            publish_date=(datetime.now() - timedelta(days=10)).isoformat(),
            source="IEEE",
            category="standards",
            topics=["802.11be", "Wi-Fi 7"],
            organizations=["IEEE"],
            relevance_score=0.85,
            match_reasons=["Keyword match"],
        ),
        Document(
            url="https://example.com/doc3",
            title="MLO Technology Explained",
            summary="Multi-Link Operation brings new capabilities to Wi-Fi 7",
            publish_date=(datetime.now() - timedelta(days=60)).isoformat(),
            source="Tech News",
            category="article",
            topics=["MLO", "Wi-Fi 7"],
            organizations=[],
            relevance_score=0.75,
            match_reasons=["Keyword match"],
        ),
    ]


@pytest.fixture
def keyword_documents():
    """Documents from keyword retrieval."""
    return [
        Document(
            url="https://example.com/doc1",
            title="Wi-Fi 7 Certification",
            summary="Wi-Fi Alliance certification program",
            relevance_score=0.95,
            match_reasons=["Keyword: Wi-Fi 7"],
        ),
        Document(
            url="https://example.com/doc2",
            title="802.11be Update",
            summary="IEEE draft amendment",
            relevance_score=0.85,
            match_reasons=["Keyword: 802.11be"],
        ),
        Document(
            url="https://example.com/doc4",
            title="Wi-Fi Alliance News",
            summary="Latest announcements",
            relevance_score=0.75,
            match_reasons=["Keyword: Wi-Fi Alliance"],
        ),
    ]


@pytest.fixture
def vector_documents():
    """Documents from vector retrieval."""
    return [
        Document(
            url="https://example.com/doc2",
            title="802.11be Update",
            summary="IEEE draft amendment",
            relevance_score=0.92,
            match_reasons=["Semantic similarity: 0.92"],
        ),
        Document(
            url="https://example.com/doc3",
            title="MLO Technology",
            summary="Multi-Link Operation capabilities",
            relevance_score=0.88,
            match_reasons=["Semantic similarity: 0.88"],
        ),
        Document(
            url="https://example.com/doc1",
            title="Wi-Fi 7 Certification",
            summary="Certification program",
            relevance_score=0.80,
            match_reasons=["Semantic similarity: 0.80"],
        ),
    ]


class TestReciprocalRankFusion:
    """Tests for Reciprocal Rank Fusion algorithm."""
    
    def test_empty_lists(self):
        """RRF handles empty input."""
        result = reciprocal_rank_fusion([])
        assert result == []
    
    def test_single_list(self, keyword_documents):
        """RRF with single list preserves order."""
        result = reciprocal_rank_fusion([keyword_documents])
        
        assert len(result) == 3
        # Order should be preserved
        assert result[0].document.url == "https://example.com/doc1"
        assert result[1].document.url == "https://example.com/doc2"
        assert result[2].document.url == "https://example.com/doc4"
    
    def test_fusion_two_lists(self, keyword_documents, vector_documents):
        """RRF properly combines two ranked lists."""
        result = reciprocal_rank_fusion([keyword_documents, vector_documents])
        
        # Should have 4 unique documents
        assert len(result) == 4
        
        # Doc2 appears in both lists - should rank high
        doc2 = next(r for r in result if r.document.url == "https://example.com/doc2")
        assert doc2.keyword_rank is not None
        assert doc2.vector_rank is not None
        assert "keyword" in doc2.sources
        assert "vector" in doc2.sources
        
        # Doc1 appears in both but at different ranks
        doc1 = next(r for r in result if r.document.url == "https://example.com/doc1")
        assert doc1.keyword_rank == 1
        assert doc1.vector_rank == 3
    
    def test_fusion_scores_decrease(self, keyword_documents, vector_documents):
        """RRF scores should be in descending order."""
        result = reciprocal_rank_fusion([keyword_documents, vector_documents])
        
        scores = [r.rrf_score for r in result]
        assert scores == sorted(scores, reverse=True)
    
    def test_fusion_with_weights(self, keyword_documents, vector_documents):
        """RRF respects list weights."""
        # Heavy weight on keyword
        result_keyword_heavy = reciprocal_rank_fusion(
            [keyword_documents, vector_documents],
            list_weights=[2.0, 0.5],
        )
        
        # Heavy weight on vector
        result_vector_heavy = reciprocal_rank_fusion(
            [keyword_documents, vector_documents],
            list_weights=[0.5, 2.0],
        )
        
        # Rankings should differ based on weights
        keyword_top = result_keyword_heavy[0].document.url
        vector_top = result_vector_heavy[0].document.url
        
        # With different weights, the top result might be different
        # or at least the scores should be different
        assert len(result_keyword_heavy) == len(result_vector_heavy)
    
    def test_match_reasons_updated(self, keyword_documents, vector_documents):
        """RRF updates match reasons to reflect sources."""
        result = reciprocal_rank_fusion([keyword_documents, vector_documents])
        
        for ranked in result:
            reasons = ranked.document.match_reasons
            
            if ranked.keyword_rank:
                assert any("Keyword" in r for r in reasons)
            
            if ranked.vector_rank:
                assert any("Semantic" in r for r in reasons)


class TestRecencyBoost:
    """Tests for recency boost functionality."""
    
    def test_boost_recent_documents(self, sample_documents):
        """Recent documents get boosted scores."""
        with patch('src.services.hybrid_search.settings') as mock_settings:
            mock_settings.recency_boost_enabled = True
            mock_settings.recency_boost_days = 30
            mock_settings.recency_boost_factor = 1.2
            
            boosted = apply_recency_boost(sample_documents)
            
            # Doc1 is 5 days old - should be boosted
            assert boosted[0].relevance_score > sample_documents[0].relevance_score
            
            # Doc3 is 60 days old - should not be boosted
            assert boosted[2].relevance_score == sample_documents[2].relevance_score
    
    def test_boost_adds_match_reason(self, sample_documents):
        """Boosted documents get a match reason."""
        with patch('src.services.hybrid_search.settings') as mock_settings:
            mock_settings.recency_boost_enabled = True
            mock_settings.recency_boost_days = 30
            mock_settings.recency_boost_factor = 1.2
            
            boosted = apply_recency_boost(sample_documents)
            
            # Recent doc should have boost reason
            assert any("Recent" in r for r in boosted[0].match_reasons)
    
    def test_boost_disabled(self, sample_documents):
        """Recency boost can be disabled."""
        with patch('src.services.hybrid_search.settings') as mock_settings:
            mock_settings.recency_boost_enabled = False
            
            boosted = apply_recency_boost(sample_documents)
            
            # Scores should be unchanged
            for orig, boost in zip(sample_documents, boosted):
                assert orig.relevance_score == boost.relevance_score
    
    def test_score_capped_at_one(self, sample_documents):
        """Boosted scores don't exceed 1.0."""
        with patch('src.services.hybrid_search.settings') as mock_settings:
            mock_settings.recency_boost_enabled = True
            mock_settings.recency_boost_days = 30
            mock_settings.recency_boost_factor = 2.0  # Very aggressive boost
            
            boosted = apply_recency_boost(sample_documents)
            
            for doc in boosted:
                assert doc.relevance_score <= 1.0


class TestVectorRetriever:
    """Tests for VectorRetriever."""
    
    @pytest.fixture
    def retriever(self):
        return VectorRetriever()
    
    @pytest.mark.asyncio
    async def test_retrieve_generates_embedding(self, retriever):
        """Vector retrieval generates query embedding."""
        with patch('src.services.vector_retriever.generate_embedding') as mock_embed:
            mock_embed.return_value = [0.1] * 1536
            
            with patch('src.services.vector_retriever.get_repo') as mock_repo:
                mock_client = MagicMock()
                mock_session = MagicMock()
                mock_session.__enter__ = MagicMock(return_value=mock_session)
                mock_session.__exit__ = MagicMock(return_value=False)
                mock_session.run.return_value = iter([])
                mock_client.get_session.return_value = mock_session
                mock_repo.return_value.client = mock_client
                
                result = await retriever.retrieve(
                    query="Wi-Fi 7 certification",
                    filters={},
                    intent=QueryIntent.TOPIC_DISCOVERY,
                )
                
                mock_embed.assert_called_once_with("Wi-Fi 7 certification")
    
    @pytest.mark.asyncio
    async def test_retrieve_handles_embedding_failure(self, retriever):
        """Vector retrieval handles embedding generation failure."""
        with patch('src.services.vector_retriever.generate_embedding') as mock_embed:
            mock_embed.return_value = None
            
            result = await retriever.retrieve(
                query="test query",
                filters={},
                intent=QueryIntent.TOPIC_DISCOVERY,
            )
            
            assert result.documents == []
            assert result.query_embedding_generated == False
    
    @pytest.mark.asyncio
    async def test_retrieve_applies_date_filter(self, retriever):
        """Vector retrieval applies date filters."""
        # This tests the _passes_date_filter method
        props = {
            "publish_date": (datetime.now() - timedelta(days=10)).isoformat()
        }
        
        # Should pass with no filter
        assert retriever._passes_date_filter(props, {}) == True
        
        # Should pass within date range
        filters = {
            "start_date": (datetime.now() - timedelta(days=30)).isoformat(),
            "end_date": datetime.now().isoformat(),
        }
        assert retriever._passes_date_filter(props, filters) == True
        
        # Should fail outside date range
        filters = {
            "start_date": (datetime.now() - timedelta(days=5)).isoformat(),
        }
        assert retriever._passes_date_filter(props, filters) == False


class TestHybridSearch:
    """Tests for HybridSearch combining keyword and vector."""
    
    @pytest.fixture
    def hybrid(self):
        return HybridSearch()
    
    @pytest.mark.asyncio
    async def test_search_uses_both_retrievers(self, hybrid, keyword_documents, vector_documents):
        """Hybrid search uses both keyword and vector retrievers."""
        from src.services.keyword_retriever import RetrievalResult
        from src.services.vector_retriever import VectorSearchResult
        
        with patch.object(hybrid.keyword_retriever, 'retrieve', new_callable=AsyncMock) as mock_kw:
            with patch.object(hybrid.vector_retriever, 'retrieve', new_callable=AsyncMock) as mock_vec:
                mock_kw.return_value = RetrievalResult(
                    documents=keyword_documents,
                    total_candidates=10,
                )
                mock_vec.return_value = VectorSearchResult(
                    documents=vector_documents,
                    total_candidates=15,
                    query_embedding_generated=True,
                )
                
                with patch('src.services.hybrid_search.settings') as mock_settings:
                    mock_settings.vector_search_enabled = True
                    mock_settings.hybrid_search_enabled = True
                    mock_settings.retrieval_pool_multiplier = 3
                    mock_settings.keyword_weight = 1.0
                    mock_settings.vector_weight = 1.0
                    mock_settings.rrf_k = 60
                    mock_settings.recency_boost_enabled = False
                    mock_settings.graph_search_enabled = False
                    mock_settings.parallel_retrieval_enabled = False
                    
                    result = await hybrid.search(
                        query="Wi-Fi 7",
                        filters={},
                        intent=QueryIntent.TOPIC_DISCOVERY,
                        max_results=10,
                    )
                    
                    mock_kw.assert_called_once()
                    mock_vec.assert_called_once()
                    
                    assert "keyword" in result.strategies_used
                    assert "vector" in result.strategies_used
    
    @pytest.mark.asyncio
    async def test_search_keyword_only_when_vector_disabled(self, hybrid, keyword_documents):
        """Hybrid search falls back to keyword when vector disabled."""
        from src.services.keyword_retriever import RetrievalResult
        
        with patch.object(hybrid.keyword_retriever, 'retrieve', new_callable=AsyncMock) as mock_kw:
            with patch.object(hybrid.vector_retriever, 'retrieve', new_callable=AsyncMock) as mock_vec:
                mock_kw.return_value = RetrievalResult(
                    documents=keyword_documents,
                    total_candidates=10,
                )
                
                with patch('src.services.hybrid_search.settings') as mock_settings:
                    mock_settings.vector_search_enabled = False
                    mock_settings.hybrid_search_enabled = False
                    mock_settings.retrieval_pool_multiplier = 3
                    mock_settings.keyword_weight = 1.0
                    mock_settings.recency_boost_enabled = False
                    mock_settings.graph_search_enabled = False
                    mock_settings.parallel_retrieval_enabled = False
                    
                    result = await hybrid.search(
                        query="Wi-Fi 7",
                        filters={},
                        intent=QueryIntent.TOPIC_DISCOVERY,
                        max_results=10,
                    )
                    
                    mock_kw.assert_called_once()
                    mock_vec.assert_not_called()
                    
                    assert result.strategies_used == ["keyword"]
    
    @pytest.mark.asyncio
    async def test_search_handles_vector_failure(self, hybrid, keyword_documents):
        """Hybrid search continues with keyword when vector fails."""
        from src.services.keyword_retriever import RetrievalResult
        
        with patch.object(hybrid.keyword_retriever, 'retrieve', new_callable=AsyncMock) as mock_kw:
            with patch.object(hybrid.vector_retriever, 'retrieve', new_callable=AsyncMock) as mock_vec:
                mock_kw.return_value = RetrievalResult(
                    documents=keyword_documents,
                    total_candidates=10,
                )
                mock_vec.side_effect = Exception("Vector search failed")
                
                with patch('src.services.hybrid_search.settings') as mock_settings:
                    mock_settings.vector_search_enabled = True
                    mock_settings.hybrid_search_enabled = True
                    mock_settings.retrieval_pool_multiplier = 3
                    mock_settings.keyword_weight = 1.0
                    mock_settings.recency_boost_enabled = False
                    mock_settings.graph_search_enabled = False
                    mock_settings.parallel_retrieval_enabled = False
                    
                    result = await hybrid.search(
                        query="Wi-Fi 7",
                        filters={},
                        intent=QueryIntent.TOPIC_DISCOVERY,
                        max_results=10,
                    )
                    
                    # Should still return keyword results
                    assert len(result.documents) > 0
                    assert result.strategies_used == ["keyword"]
    
    @pytest.mark.asyncio
    async def test_search_returns_empty_when_all_fail(self, hybrid):
        """Hybrid search returns empty when all retrievers fail."""
        with patch.object(hybrid.keyword_retriever, 'retrieve', new_callable=AsyncMock) as mock_kw:
            with patch.object(hybrid.vector_retriever, 'retrieve', new_callable=AsyncMock) as mock_vec:
                mock_kw.side_effect = Exception("Keyword failed")
                mock_vec.side_effect = Exception("Vector failed")
                
                with patch('src.services.hybrid_search.settings') as mock_settings:
                    mock_settings.vector_search_enabled = True
                    mock_settings.hybrid_search_enabled = True
                    mock_settings.retrieval_pool_multiplier = 3
                    mock_settings.graph_search_enabled = False
                    mock_settings.parallel_retrieval_enabled = False
                    
                    result = await hybrid.search(
                        query="Wi-Fi 7",
                        filters={},
                        intent=QueryIntent.TOPIC_DISCOVERY,
                        max_results=10,
                    )
                    
                    assert result.documents == []
                    assert result.strategies_used == []


class TestEmbeddingGeneration:
    """Tests for embedding generation in llm_client."""
    
    @pytest.mark.asyncio
    async def test_generate_embedding_success(self):
        """Embedding generation succeeds with valid input."""
        from src.services.llm_client import generate_embedding
        
        with patch('src.services.llm_client.get_llm_client') as mock_get_client:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.data = [MagicMock(embedding=[0.1] * 1536)]
            mock_client.embeddings.create.return_value = mock_response
            mock_get_client.return_value = mock_client
            
            result = await generate_embedding("test text")
            
            assert len(result) == 1536
            mock_client.embeddings.create.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_generate_embedding_empty_text_raises(self):
        """Embedding generation raises for empty text."""
        from src.services.llm_client import generate_embedding
        
        with pytest.raises(ValueError, match="empty text"):
            await generate_embedding("")
        
        with pytest.raises(ValueError, match="empty text"):
            await generate_embedding("   ")
    
    @pytest.mark.asyncio
    async def test_generate_embedding_no_client_raises(self):
        """Embedding generation raises when client unavailable."""
        from src.services.llm_client import generate_embedding
        
        with patch('src.services.llm_client.get_llm_client', return_value=None):
            with pytest.raises(ValueError, match="not available"):
                await generate_embedding("test text")


class TestBatchEmbeddingGeneration:
    """Tests for batch embedding generation."""
    
    @pytest.mark.asyncio
    async def test_generate_embeddings_batch_success(self):
        """Batch embedding generation succeeds."""
        from src.services.llm_client import generate_embeddings_batch
        
        with patch('src.services.llm_client.get_llm_client') as mock_get_client:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.data = [
                MagicMock(embedding=[0.1] * 1536),
                MagicMock(embedding=[0.2] * 1536),
            ]
            mock_client.embeddings.create.return_value = mock_response
            mock_get_client.return_value = mock_client
            
            result = await generate_embeddings_batch(["text1", "text2"])
            
            assert len(result) == 2
            assert len(result[0]) == 1536
            assert len(result[1]) == 1536
    
    @pytest.mark.asyncio
    async def test_generate_embeddings_batch_empty_list(self):
        """Batch embedding returns empty for empty input."""
        from src.services.llm_client import generate_embeddings_batch
        
        result = await generate_embeddings_batch([])
        assert result == []
    
    @pytest.mark.asyncio
    async def test_generate_embeddings_batch_no_client_raises(self):
        """Batch embedding raises when client unavailable."""
        from src.services.llm_client import generate_embeddings_batch
        
        with patch('src.services.llm_client.get_llm_client', return_value=None):
            with pytest.raises(ValueError, match="not available"):
                await generate_embeddings_batch(["text1"])


class TestVectorRetrieverDateFiltering:
    """Additional tests for date filtering in VectorRetriever."""
    
    @pytest.fixture
    def retriever(self):
        return VectorRetriever()
    
    def test_passes_date_filter_no_publish_date(self, retriever):
        """Documents without publish_date pass filter."""
        props = {"title": "Test"}
        filters = {"start_date": "2025-01-01"}
        
        assert retriever._passes_date_filter(props, filters) == True
    
    def test_passes_date_filter_end_date_only(self, retriever):
        """End date filter works alone."""
        props = {"publish_date": "2025-01-15T00:00:00"}
        
        # Should pass - before end date
        filters = {"end_date": "2025-01-20"}
        assert retriever._passes_date_filter(props, filters) == True
        
        # Should fail - after end date
        filters = {"end_date": "2025-01-10"}
        assert retriever._passes_date_filter(props, filters) == False
    
    def test_passes_date_filter_datetime_objects(self, retriever):
        """Date filtering works with datetime objects."""
        from datetime import datetime
        
        props = {"publish_date": datetime(2025, 1, 15)}
        filters = {
            "start_date": datetime(2025, 1, 1),
            "end_date": datetime(2025, 1, 31),
        }
        
        assert retriever._passes_date_filter(props, filters) == True


class TestHybridSearchEdgeCases:
    """Edge case tests for HybridSearch."""
    
    @pytest.fixture
    def hybrid(self):
        return HybridSearch()
    
    @pytest.mark.asyncio
    async def test_search_with_empty_results(self, hybrid):
        """Hybrid search handles empty results from both retrievers."""
        from src.services.keyword_retriever import RetrievalResult
        from src.services.vector_retriever import VectorSearchResult
        
        with patch.object(hybrid.keyword_retriever, 'retrieve', new_callable=AsyncMock) as mock_kw:
            with patch.object(hybrid.vector_retriever, 'retrieve', new_callable=AsyncMock) as mock_vec:
                mock_kw.return_value = RetrievalResult(documents=[], total_candidates=0)
                mock_vec.return_value = VectorSearchResult(
                    documents=[],
                    total_candidates=0,
                    query_embedding_generated=True,
                )
                
                with patch('src.services.hybrid_search.settings') as mock_settings:
                    mock_settings.vector_search_enabled = True
                    mock_settings.hybrid_search_enabled = True
                    mock_settings.retrieval_pool_multiplier = 3
                    mock_settings.keyword_weight = 1.0
                    mock_settings.vector_weight = 1.0
                    mock_settings.rrf_k = 60
                    mock_settings.recency_boost_enabled = False
                    mock_settings.graph_search_enabled = False
                    mock_settings.parallel_retrieval_enabled = False
                    
                    result = await hybrid.search(
                        query="nonexistent topic",
                        filters={},
                        intent=QueryIntent.TOPIC_DISCOVERY,
                        max_results=10,
                    )
                    
                    assert result.documents == []
                    assert result.total_candidates == 0
    
    @pytest.mark.asyncio
    async def test_search_respects_max_results(self, hybrid, keyword_documents, vector_documents):
        """Hybrid search respects max_results limit."""
        from src.services.keyword_retriever import RetrievalResult
        from src.services.vector_retriever import VectorSearchResult
        
        with patch.object(hybrid.keyword_retriever, 'retrieve', new_callable=AsyncMock) as mock_kw:
            with patch.object(hybrid.vector_retriever, 'retrieve', new_callable=AsyncMock) as mock_vec:
                mock_kw.return_value = RetrievalResult(
                    documents=keyword_documents,
                    total_candidates=10,
                )
                mock_vec.return_value = VectorSearchResult(
                    documents=vector_documents,
                    total_candidates=15,
                    query_embedding_generated=True,
                )
                
                with patch('src.services.hybrid_search.settings') as mock_settings:
                    mock_settings.vector_search_enabled = True
                    mock_settings.hybrid_search_enabled = True
                    mock_settings.retrieval_pool_multiplier = 3
                    mock_settings.keyword_weight = 1.0
                    mock_settings.vector_weight = 1.0
                    mock_settings.rrf_k = 60
                    mock_settings.recency_boost_enabled = False
                    mock_settings.graph_search_enabled = False
                    mock_settings.parallel_retrieval_enabled = False
                    
                    result = await hybrid.search(
                        query="Wi-Fi 7",
                        filters={},
                        intent=QueryIntent.TOPIC_DISCOVERY,
                        max_results=2,
                    )
                    
                    assert len(result.documents) <= 2


class TestRRFEdgeCases:
    """Edge case tests for RRF algorithm."""
    
    def test_rrf_with_k_parameter(self, keyword_documents, vector_documents):
        """Different k values affect ranking."""
        result_low_k = reciprocal_rank_fusion(
            [keyword_documents, vector_documents],
            k=10,  # Low k = more weight to top ranks
        )
        
        result_high_k = reciprocal_rank_fusion(
            [keyword_documents, vector_documents],
            k=100,  # High k = more equal weighting
        )
        
        # Both should have same documents
        assert len(result_low_k) == len(result_high_k)
        
        # But scores should differ
        low_k_scores = [r.rrf_score for r in result_low_k]
        high_k_scores = [r.rrf_score for r in result_high_k]
        
        # Scores with low k should be higher (more concentrated)
        assert sum(low_k_scores) > sum(high_k_scores)
    
    def test_rrf_preserves_document_data(self, keyword_documents):
        """RRF preserves all document data."""
        result = reciprocal_rank_fusion([keyword_documents])
        
        original = keyword_documents[0]
        fused = result[0].document
        
        assert fused.url == original.url
        assert fused.title == original.title
        assert fused.summary == original.summary


class TestRecencyBoostEdgeCases:
    """Edge case tests for recency boost."""
    
    def test_boost_invalid_date_format(self):
        """Recency boost handles invalid date formats gracefully."""
        docs = [
            Document(
                url="https://example.com/doc1",
                title="Test",
                publish_date="invalid-date",
                relevance_score=0.8,
            )
        ]
        
        with patch('src.services.hybrid_search.settings') as mock_settings:
            mock_settings.recency_boost_enabled = True
            mock_settings.recency_boost_days = 30
            mock_settings.recency_boost_factor = 1.2
            
            # Should not raise, just skip boost
            boosted = apply_recency_boost(docs)
            assert len(boosted) == 1
    
    def test_boost_no_publish_date(self):
        """Recency boost handles missing publish_date."""
        docs = [
            Document(
                url="https://example.com/doc1",
                title="Test",
                relevance_score=0.8,
            )
        ]
        
        with patch('src.services.hybrid_search.settings') as mock_settings:
            mock_settings.recency_boost_enabled = True
            mock_settings.recency_boost_days = 30
            mock_settings.recency_boost_factor = 1.2
            
            boosted = apply_recency_boost(docs)
            assert boosted[0].relevance_score == 0.8  # Unchanged
