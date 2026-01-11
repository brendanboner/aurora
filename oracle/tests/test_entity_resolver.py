"""Tests for Entity Resolver - Graph-aware entity resolution."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.services.entity_resolver import (
    EntityResolver,
    ResolvedEntity,
    EntityResolutionResult,
    resolve_entities,
)


class TestEntityResolver:
    """Tests for EntityResolver class."""
    
    @pytest.fixture
    def resolver(self):
        return EntityResolver(min_similarity=0.75)
    
    @pytest.mark.asyncio
    async def test_resolve_empty_inputs(self, resolver):
        """Resolver handles empty inputs gracefully."""
        result = await resolver.resolve(
            topics=[],
            organizations=[],
            people=[],
        )
        
        assert result.topics == []
        assert result.organizations == []
        assert result.people == []
        assert result.unresolved == []
    
    @pytest.mark.asyncio
    async def test_exact_match_topic(self, resolver):
        """Resolver finds exact match for topic."""
        with patch.object(resolver, '_exact_match', new_callable=AsyncMock) as mock_exact:
            mock_exact.return_value = ResolvedEntity(
                original="Wi-Fi 7",
                resolved="Wi-Fi 7",
                entity_type="topic",
                confidence=1.0,
                node_id="topic_123",
            )
            
            result = await resolver.resolve(
                topics=["Wi-Fi 7"],
                organizations=[],
                people=[],
            )
            
            assert len(result.topics) == 1
            assert result.topics[0].resolved == "Wi-Fi 7"
            assert result.topics[0].confidence == 1.0
    
    @pytest.mark.asyncio
    async def test_exact_match_with_alias(self, resolver):
        """Resolver matches aliases to canonical names."""
        with patch.object(resolver, '_exact_match', new_callable=AsyncMock) as mock_exact:
            # "WFA" should resolve to "Wi-Fi Alliance"
            mock_exact.return_value = ResolvedEntity(
                original="WFA",
                resolved="Wi-Fi Alliance",
                entity_type="organization",
                confidence=1.0,
                node_id="org_456",
            )
            
            result = await resolver.resolve(
                topics=[],
                organizations=["WFA"],
                people=[],
            )
            
            assert len(result.organizations) == 1
            assert result.organizations[0].original == "WFA"
            assert result.organizations[0].resolved == "Wi-Fi Alliance"
    
    @pytest.mark.asyncio
    async def test_vector_match_fallback(self, resolver):
        """Resolver falls back to vector match when exact fails."""
        with patch.object(resolver, '_exact_match', new_callable=AsyncMock) as mock_exact:
            with patch.object(resolver, '_vector_match', new_callable=AsyncMock) as mock_vector:
                mock_exact.return_value = None  # No exact match
                mock_vector.return_value = ResolvedEntity(
                    original="Quallcomm",  # Typo
                    resolved="Qualcomm",
                    entity_type="organization",
                    confidence=0.92,
                )
                
                with patch('src.services.entity_resolver.settings') as mock_settings:
                    mock_settings.vector_search_enabled = True
                    
                    result = await resolver.resolve(
                        topics=[],
                        organizations=["Quallcomm"],
                        people=[],
                    )
                    
                    assert len(result.organizations) == 1
                    assert result.organizations[0].original == "Quallcomm"
                    assert result.organizations[0].resolved == "Qualcomm"
                    assert result.organizations[0].confidence == 0.92
    
    @pytest.mark.asyncio
    async def test_unresolved_entities_tracked(self, resolver):
        """Unresolved entities are tracked in result."""
        with patch.object(resolver, '_exact_match', new_callable=AsyncMock) as mock_exact:
            with patch.object(resolver, '_vector_match', new_callable=AsyncMock) as mock_vector:
                # First topic resolves, second doesn't
                mock_exact.side_effect = [
                    ResolvedEntity(
                        original="Wi-Fi 7",
                        resolved="Wi-Fi 7",
                        entity_type="topic",
                        confidence=1.0,
                    ),
                    None,  # "FooBar" not found
                ]
                mock_vector.return_value = None  # Vector also fails
                
                with patch('src.services.entity_resolver.settings') as mock_settings:
                    mock_settings.vector_search_enabled = True
                    
                    result = await resolver.resolve(
                        topics=["Wi-Fi 7", "FooBar"],
                        organizations=[],
                        people=[],
                    )
                    
                    assert len(result.topics) == 2
                    # First should be resolved
                    assert result.topics[0].resolved == "Wi-Fi 7"
                    assert result.topics[0].confidence == 1.0
                    # Second should be unresolved but still returned with low confidence
                    assert result.topics[1].resolved == "FooBar"
                    assert result.topics[1].confidence == 0.5
    
    @pytest.mark.asyncio
    async def test_resolve_multiple_entity_types(self, resolver):
        """Resolver handles multiple entity types in one call."""
        with patch.object(resolver, '_exact_match', new_callable=AsyncMock) as mock_exact:
            mock_exact.side_effect = [
                ResolvedEntity(original="Wi-Fi 7", resolved="Wi-Fi 7", entity_type="topic", confidence=1.0),
                ResolvedEntity(original="Intel", resolved="Intel Corporation", entity_type="organization", confidence=1.0),
                ResolvedEntity(original="John Smith", resolved="John Smith", entity_type="person", confidence=1.0),
            ]
            
            result = await resolver.resolve(
                topics=["Wi-Fi 7"],
                organizations=["Intel"],
                people=["John Smith"],
            )
            
            assert len(result.topics) == 1
            assert len(result.organizations) == 1
            assert len(result.people) == 1
            assert result.organizations[0].resolved == "Intel Corporation"


class TestExactMatch:
    """Tests for exact match functionality."""
    
    @pytest.fixture
    def resolver(self):
        return EntityResolver()
    
    @pytest.mark.asyncio
    async def test_exact_match_query_structure(self, resolver):
        """Exact match queries the correct node label and fields."""
        mock_client = MagicMock()
        # execute_query returns a list of dict-like records
        mock_client.execute_query.return_value = [
            {"name": "Wi-Fi 7", "node_id": "topic_123"}
        ]
        
        with patch('src.services.entity_resolver.get_repo') as mock_get_repo:
            mock_get_repo.return_value.client = mock_client
            
            result = await resolver._exact_match("Wi-Fi 7", "topic")
            
            assert result is not None
            assert result.resolved == "Wi-Fi 7"
            assert result.confidence == 1.0
            
            # Verify query was called
            mock_client.execute_query.assert_called_once()
            call_args = mock_client.execute_query.call_args
            assert "Topic" in call_args[0][0]  # Label in query
            assert call_args[0][1]["candidate"] == "Wi-Fi 7"


class TestVectorMatch:
    """Tests for vector similarity match functionality."""
    
    @pytest.fixture
    def resolver(self):
        return EntityResolver(min_similarity=0.75)
    
    @pytest.mark.asyncio
    async def test_vector_match_generates_embedding(self, resolver):
        """Vector match generates embedding for candidate."""
        with patch('src.services.entity_resolver.generate_embedding', new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = [0.1] * 1536
            
            mock_client = MagicMock()
            # execute_query returns a list of dict-like records
            mock_client.execute_query.return_value = [
                {"name": "Qualcomm", "node_id": "org_123", "score": 0.95}
            ]
            
            with patch('src.services.entity_resolver.get_repo') as mock_get_repo:
                mock_get_repo.return_value.client = mock_client
                
                result = await resolver._vector_match("Quallcomm", "organization")
                
                mock_embed.assert_called_once_with("Quallcomm")
                assert result is not None
                assert result.resolved == "Qualcomm"
                assert result.confidence == 0.95
    
    @pytest.mark.asyncio
    async def test_vector_match_respects_min_similarity(self, resolver):
        """Vector match returns None if below threshold."""
        with patch('src.services.entity_resolver.generate_embedding', new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = [0.1] * 1536
            
            mock_client = MagicMock()
            # execute_query returns empty list when no results above threshold
            mock_client.execute_query.return_value = []
            
            with patch('src.services.entity_resolver.get_repo') as mock_get_repo:
                mock_get_repo.return_value.client = mock_client
                
                result = await resolver._vector_match("totally_unknown", "topic")
                
                assert result is None


class TestConvenienceFunction:
    """Tests for the resolve_entities convenience function."""
    
    @pytest.mark.asyncio
    async def test_convenience_function(self):
        """Convenience function creates resolver and calls resolve."""
        with patch('src.services.entity_resolver.EntityResolver') as MockResolver:
            mock_instance = MagicMock()
            mock_instance.resolve = AsyncMock(return_value=EntityResolutionResult(
                topics=[],
                organizations=[],
                people=[],
                unresolved=[],
            ))
            MockResolver.return_value = mock_instance
            
            result = await resolve_entities(
                topics=["Wi-Fi 7"],
                organizations=["Intel"],
            )
            
            mock_instance.resolve.assert_called_once_with(
                topics=["Wi-Fi 7"],
                organizations=["Intel"],
                people=[],
            )


class TestQueryParserIntegration:
    """Tests for QueryParser integration with EntityResolver."""
    
    @pytest.mark.asyncio
    async def test_parser_resolves_entities_when_enabled(self):
        """QueryParser calls entity resolver when enabled."""
        from src.services.query_parser import QueryParser
        
        with patch('src.services.query_parser.get_llm_client') as mock_client:
            mock_client.return_value = None  # Force heuristic parsing
            
            with patch('src.services.query_parser.settings') as mock_settings:
                mock_settings.entity_resolution_enabled = True
                
                parser = QueryParser(resolve_entities=True)
                
                with patch.object(parser, '_resolve_entities', new_callable=AsyncMock) as mock_resolve:
                    mock_resolve.return_value = MagicMock(
                        topics=["Wi-Fi 7"],
                        organizations=[],
                        people=[],
                        entities_resolved=True,
                    )
                    
                    result = await parser.parse("What's new with Wi-Fi 7?")
                    
                    # Resolution should have been called
                    mock_resolve.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_parser_skips_resolution_when_disabled(self):
        """QueryParser skips entity resolver when disabled."""
        from src.services.query_parser import QueryParser
        
        with patch('src.services.query_parser.get_llm_client') as mock_client:
            mock_client.return_value = None  # Force heuristic parsing
            
            parser = QueryParser(resolve_entities=False)
            
            with patch.object(parser, '_resolve_entities', new_callable=AsyncMock) as mock_resolve:
                result = await parser.parse("What's new with Wi-Fi 7?")
                
                # Resolution should NOT have been called
                mock_resolve.assert_not_called()
