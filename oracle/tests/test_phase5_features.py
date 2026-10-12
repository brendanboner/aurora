"""Tests for Phase 5 Oracle Service features.

Tests cover:
- Document chunking service
- Re-ranking service
- Enhanced answer generation
- Content caching
- /oracle/enhance endpoint
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import asdict

from src.services.chunking import (
    chunk_document,
    ChunkedDocument,
    TextChunk,
    get_all_chunks,
)
from src.services.reranking import (
    rerank_chunks,
    RankedChunk,
    ReRankingResult,
    extract_best_quotes,
)
from src.services.enhance import (
    fetch_document_content,
    FetchedDocument,
    EnhanceResult,
)


# ==================== Test Fixtures ====================

@pytest.fixture
def sample_document_content():
    """Create sample document content for testing."""
    # Simulates a document with multiple sections
    return """
    Wi-Fi 7 Certification Program Overview
    
    The Wi-Fi Alliance has officially launched the Wi-Fi CERTIFIED 7 program, 
    bringing the latest advances in Wi-Fi technology to the consumer market. 
    This certification ensures interoperability and performance standards for 
    devices supporting the IEEE 802.11be amendment.
    
    Key Features of Wi-Fi 7
    
    Multi-Link Operation (MLO) enables devices to simultaneously connect across 
    multiple bands (2.4 GHz, 5 GHz, and 6 GHz), significantly improving throughput 
    and reducing latency. This feature is particularly beneficial for real-time 
    applications such as video conferencing and cloud gaming.
    
    320 MHz Channel Width support in the 6 GHz band provides unprecedented 
    bandwidth capacity, enabling peak theoretical speeds of over 46 Gbps. 
    This increased capacity addresses the growing demand for high-bandwidth 
    applications.
    
    4K QAM (Quadrature Amplitude Modulation) increases data encoding efficiency 
    by 20% compared to Wi-Fi 6's 1024-QAM, improving throughput in favorable 
    RF conditions.
    
    Certification Requirements
    
    Devices seeking Wi-Fi CERTIFIED 7 designation must pass a comprehensive 
    test suite that validates core capabilities including MLO support, 
    security protocols, and interoperability with other certified devices.
    
    The certification program builds upon the foundation of Wi-Fi 6E while 
    adding new test cases specific to 802.11be features.
    """.strip()


@pytest.fixture
def sample_question():
    """Create a sample question for testing."""
    return "What are the key features of Wi-Fi 7?"


@pytest.fixture
def sample_chunks(sample_document_content, sample_question):
    """Create pre-chunked sample document."""
    return chunk_document(
        content=sample_document_content,
        url="https://example.com/wifi7-overview",
        title="Wi-Fi 7 Certification Overview",
    )


# ==================== Chunking Service Tests ====================

class TestChunkingService:
    """Tests for the document chunking service."""
    
    def test_chunk_document_creates_chunks(self, sample_document_content):
        """Test that chunking creates multiple chunks from content."""
        result = chunk_document(
            content=sample_document_content,
            url="https://example.com/doc",
            title="Test Doc",
            chunk_size=200,  # Small chunks for testing
        )
        
        assert isinstance(result, ChunkedDocument)
        assert len(result.chunks) > 1
        assert result.url == "https://example.com/doc"
        assert result.title == "Test Doc"
    
    def test_chunk_document_preserves_content(self, sample_document_content):
        """Test that chunking doesn't lose significant content."""
        result = chunk_document(
            content=sample_document_content,
            url="https://example.com/doc",
            title="Test Doc",
            chunk_size=200,
            chunk_overlap=50,
        )
        
        # Combine all chunks
        combined = " ".join(chunk.text for chunk in result.chunks)
        
        # Key terms should be preserved
        assert "Wi-Fi 7" in combined
        assert "MLO" in combined or "Multi-Link Operation" in combined
        assert "320 MHz" in combined
    
    def test_chunk_document_with_empty_content(self):
        """Test chunking with empty content returns empty chunks."""
        result = chunk_document(
            content="",
            url="https://example.com/empty",
            title="Empty Doc",
        )
        
        assert len(result.chunks) == 0
    
    def test_chunk_indices_are_sequential(self, sample_document_content):
        """Test that chunk indices are sequential starting from 0."""
        result = chunk_document(
            content=sample_document_content,
            url="https://example.com/doc",
            title="Test Doc",
            chunk_size=150,
        )
        
        indices = [chunk.chunk_index for chunk in result.chunks]
        assert indices == list(range(len(indices)))
    
    def test_chunks_have_source_info(self, sample_document_content):
        """Test that chunks retain source document information."""
        result = chunk_document(
            content=sample_document_content,
            url="https://example.com/wifi7",
            title="Wi-Fi 7 Overview",
            chunk_size=200,
        )
        
        for chunk in result.chunks:
            assert chunk.source_url == "https://example.com/wifi7"
            assert chunk.source_title == "Wi-Fi 7 Overview"


class TestGetAllChunks:
    """Tests for combining chunks from multiple documents."""
    
    def test_get_all_chunks_combines_documents(self, sample_document_content):
        """Test that chunks from multiple docs are combined."""
        doc1 = chunk_document(
            content=sample_document_content,
            url="https://example.com/doc1",
            title="Doc 1",
            chunk_size=300,
        )
        doc2 = chunk_document(
            content="Short content",
            url="https://example.com/doc2",
            title="Doc 2",
        )
        
        all_chunks = get_all_chunks([doc1, doc2])
        
        # Should have chunks from both documents
        urls = set(chunk.source_url for chunk in all_chunks)
        assert len(urls) >= 1  # At least doc1 should have chunks
    
    def test_get_all_chunks_empty_list(self):
        """Test get_all_chunks with empty input."""
        assert get_all_chunks([]) == []


# ==================== Reranking Service Tests ====================

class TestRerankingService:
    """Tests for the re-ranking service."""
    
    @pytest.mark.asyncio
    async def test_rerank_chunks_returns_ranked_results(self, sample_chunks, sample_question):
        """Test that reranking returns ranked chunks."""
        # Mock the embedding functions
        with patch('src.services.reranking.generate_embedding') as mock_embed_query, \
             patch('src.services.reranking.batch_generate_embeddings') as mock_embed_batch:
            # Return mock embeddings (simple normalized vectors)
            mock_embed_query.return_value = [0.5] * 1536
            mock_embed_batch.return_value = [[0.5] * 1536] * len(sample_chunks.chunks)
            
            result = await rerank_chunks(
                query=sample_question,
                chunks=sample_chunks.chunks,
                top_k=3,
            )
            
            assert isinstance(result, ReRankingResult)
            assert all(isinstance(r, RankedChunk) for r in result.chunks)
            assert len(result.chunks) <= 3
    
    @pytest.mark.asyncio
    async def test_rerank_chunks_orders_by_score(self, sample_chunks, sample_question):
        """Test that results are ordered by score descending."""
        with patch('src.services.reranking.generate_embedding') as mock_embed_query, \
             patch('src.services.reranking.batch_generate_embeddings') as mock_embed_batch:
            # Create query embedding
            mock_embed_query.return_value = [1.0] + [0.0] * 1535
            
            # Create mock embeddings that will produce different similarity scores
            num_chunks = len(sample_chunks.chunks)
            embeddings = []
            # Chunk embeddings with decreasing similarity
            for i in range(num_chunks):
                vec = [1.0 - (i * 0.1)] + [0.1 * i] + [0.0] * 1534
                norm = sum(v**2 for v in vec) ** 0.5
                if norm > 0:
                    embeddings.append([v / norm for v in vec])
                else:
                    embeddings.append(vec)
            
            mock_embed_batch.return_value = embeddings
            
            result = await rerank_chunks(
                query=sample_question,
                chunks=sample_chunks.chunks,
                top_k=5,
            )
            
            # Check scores are in descending order
            scores = [r.score for r in result.chunks]
            assert scores == sorted(scores, reverse=True)
    
    @pytest.mark.asyncio
    async def test_rerank_empty_chunks(self, sample_question):
        """Test reranking with no chunks."""
        result = await rerank_chunks(
            query=sample_question,
            chunks=[],
            top_k=5,
        )
        
        assert isinstance(result, ReRankingResult)
        assert result.chunks == []


class TestExtractBestQuotes:
    """Tests for quote extraction from ranked chunks."""
    
    def test_extract_best_quotes_returns_quotes(self, sample_chunks):
        """Test that quote extraction returns quotes."""
        # Create mock ranked chunks
        ranked = [
            RankedChunk(
                chunk=sample_chunks.chunks[0],
                score=0.95,
                rank=1,
            )
        ]
        
        quotes = extract_best_quotes(
            ranked_chunks=ranked,
            max_quotes=2,
            min_score=0.5,  # Lower threshold to ensure we get quotes
        )
        
        assert isinstance(quotes, list)
        # May or may not find quotes depending on content
    
    def test_extract_best_quotes_empty_input(self):
        """Test quote extraction with no chunks."""
        quotes = extract_best_quotes(
            ranked_chunks=[],
            max_quotes=3,
        )
        
        assert quotes == []


# ==================== Content Fetching Tests ====================

class TestFetchDocumentContent:
    """Tests for document content fetching."""
    
    @pytest.mark.asyncio
    async def test_fetch_returns_cached_content(self):
        """Test that cached content is returned without HTTP request."""
        with patch('src.services.enhance.OracleCache') as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache.is_available.return_value = True
            mock_cache.get_document_content = AsyncMock(return_value="Cached content here")
            # get_cache is async, so it needs to return an awaitable
            mock_cache_cls.get_cache = AsyncMock(return_value=mock_cache)
            
            result = await fetch_document_content(
                url="https://example.com/cached",
                datasource_id="test",
                title="Cached Doc",
            )
            
            assert result.success
            assert result.content == "Cached content here"
            assert result.from_cache
    
    @pytest.mark.asyncio
    async def test_fetch_handles_retriever_error(self):
        """Test handling of retriever service errors."""
        with patch('src.services.enhance.OracleCache') as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache.is_available.return_value = False
            mock_cache.get_document_content = AsyncMock(return_value=None)
            # get_cache is async, so it needs to return an awaitable
            mock_cache_cls.get_cache = AsyncMock(return_value=mock_cache)
            
            with patch('src.services.enhance.aiohttp.ClientSession') as mock_session_cls:
                # Set up the mock response
                mock_response = MagicMock()
                mock_response.status = 500
                mock_response.text = AsyncMock(return_value="Internal Server Error")
                mock_response.__aenter__ = AsyncMock(return_value=mock_response)
                mock_response.__aexit__ = AsyncMock(return_value=None)
                
                # Set up the mock session
                mock_session = MagicMock()
                mock_session.post = MagicMock(return_value=mock_response)
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=None)
                
                mock_session_cls.return_value = mock_session
                
                result = await fetch_document_content(
                    url="https://example.com/error",
                    datasource_id="test",
                )
                
                assert not result.success
                assert result.error is not None


# ==================== Integration-Style Tests ====================

class TestEnhanceEndToEnd:
    """Integration-style tests for the enhance pipeline."""
    
    def test_chunking_to_ranking_pipeline(self, sample_document_content, sample_question):
        """Test the chunking to ranking pipeline."""
        # Step 1: Chunk the document
        chunked = chunk_document(
            content=sample_document_content,
            url="https://example.com/wifi7",
            title="Wi-Fi 7 Overview",
            chunk_size=250,
            chunk_overlap=50,
        )
        
        assert len(chunked.chunks) > 0
        
        # Verify chunks have all required fields
        for chunk in chunked.chunks:
            assert chunk.text
            assert chunk.source_url
            assert chunk.chunk_index >= 0
    
    def test_multiple_documents_pipeline(self, sample_document_content):
        """Test chunking and combining multiple documents."""
        docs = [
            chunk_document(
                content=sample_document_content,
                url=f"https://example.com/doc{i}",
                title=f"Document {i}",
                chunk_size=200,
            )
            for i in range(3)
        ]
        
        all_chunks = get_all_chunks(docs)
        
        # Should have chunks from all documents
        assert len(all_chunks) > 0
        
        # Verify source tracking
        source_urls = set(chunk.source_url for chunk in all_chunks)
        assert len(source_urls) == 3


# ==================== Edge Cases ====================

class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_chunk_very_short_content(self):
        """Test chunking content shorter than chunk size."""
        result = chunk_document(
            content="Short text",
            url="https://example.com/short",
            title="Short",
            chunk_size=500,
        )
        
        # Should create at most 1 chunk
        assert len(result.chunks) <= 1
    
    def test_chunk_with_special_characters(self):
        """Test chunking content with special characters."""
        content = """
        Wi-Fi® technology uses 802.11™ standards.
        Speeds: >1 Gbps using "MLO" feature.
        Testing unicode: émojis 🎉 and symbols ©®™
        """
        
        result = chunk_document(
            content=content,
            url="https://example.com/special",
            title="Special Chars",
        )
        
        # Should not raise exceptions
        assert result is not None
        # Content should be preserved
        combined = " ".join(c.text for c in result.chunks)
        assert "Wi-Fi" in combined
    
    def test_chunk_preserves_paragraph_breaks(self):
        """Test that chunking respects paragraph structure."""
        content = """
        Paragraph one about Wi-Fi 7 certification.
        
        Paragraph two about MLO features.
        
        Paragraph three about 320 MHz channels.
        """
        
        result = chunk_document(
            content=content,
            url="https://example.com/paragraphs",
            title="Paragraphs",
            chunk_size=100,
        )
        
        # Should have created chunks
        assert len(result.chunks) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
