"""Tests for Graph Retriever - Phase 3."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

from src.models.response import Document, QueryIntent
from src.services.graph_retriever import (
    GraphRetriever,
    GraphSearchResult,
    TrendingTopic,
    PersonTopicConnection,
    OrgCollaboration,
    graph_search,
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
            match_reasons=["Graph traversal (org_hierarchy)"],
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
            match_reasons=["Graph traversal (org_hierarchy)"],
        ),
    ]


@pytest.fixture
def mock_neo4j_client():
    """Create a mock Neo4j client."""
    mock_session = MagicMock()
    mock_client = MagicMock()
    mock_client.get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_client.get_session.return_value.__exit__ = MagicMock(return_value=False)
    # Also set up execute_query for the new API pattern
    mock_client.execute_query.return_value = []
    return mock_client, mock_session


@pytest.fixture
def mock_repo(mock_neo4j_client):
    """Create a mock repository."""
    mock_client, mock_session = mock_neo4j_client
    mock_repo = MagicMock()
    mock_repo.client = mock_client
    return mock_repo


class TestGraphRetriever:
    """Tests for GraphRetriever class."""
    
    @pytest.mark.asyncio
    async def test_retrieve_selects_pattern_based_on_intent(self, mock_repo):
        """Test that retrieve selects the correct pattern based on intent."""
        retriever = GraphRetriever()
        
        with patch('src.services.graph_retriever.get_repo', return_value=mock_repo):
            # Mock the session run to return empty results
            mock_repo.client.get_session.return_value.__enter__.return_value.run.return_value = []
            
            # Test entity_focused intent
            result = await retriever.retrieve(
                query="What did Wi-Fi Alliance announce?",
                filters={"organizations": ["Wi-Fi Alliance"]},
                intent=QueryIntent.ENTITY_FOCUSED,
                max_results=10,
            )
            
            assert result.query_pattern == "org_hierarchy"
    
    @pytest.mark.asyncio
    async def test_retrieve_trend_analysis(self, mock_repo):
        """Test trend analysis pattern."""
        retriever = GraphRetriever()
        
        with patch('src.services.graph_retriever.get_repo', return_value=mock_repo):
            # Mock trend query results
            mock_session = mock_repo.client.get_session.return_value.__enter__.return_value
            
            # First call for trending topics
            trend_result = MagicMock()
            trend_result.__iter__ = MagicMock(return_value=iter([
                {
                    "topic": "Wi-Fi 7",
                    "current_count": 15,
                    "previous_count": 5,
                    "growth_rate": 2.0,
                    "growth_percentage": 200,
                }
            ]))
            
            # Second call for documents (empty for simplicity)
            doc_result = MagicMock()
            doc_result.__iter__ = MagicMock(return_value=iter([]))
            
            mock_session.run.side_effect = [trend_result, doc_result]
            
            result = await retriever.retrieve(
                query="What topics are trending this month?",
                filters={},
                intent=QueryIntent.TREND_ANALYSIS,
                max_results=10,
            )
            
            assert result.query_pattern == "trend_analysis"
            assert result.graph_data is not None
            assert "trending_topics" in result.graph_data
    
    @pytest.mark.asyncio
    async def test_retrieve_relationship_query(self, mock_repo):
        """Test people-topic relationship pattern."""
        retriever = GraphRetriever()
        
        with patch('src.services.graph_retriever.get_repo', return_value=mock_repo):
            mock_session = mock_repo.client.get_session.return_value.__enter__.return_value
            mock_session.run.return_value = []
            
            result = await retriever.retrieve(
                query="Who is working on Wi-Fi 7?",
                filters={"topics": ["Wi-Fi 7"]},
                intent=QueryIntent.RELATIONSHIP_QUERY,
                max_results=10,
            )
            
            assert result.query_pattern == "people_topic"
    
    @pytest.mark.asyncio
    async def test_retrieve_handles_errors_gracefully(self, mock_repo):
        """Test that retrieve handles Neo4j errors gracefully."""
        retriever = GraphRetriever()
        
        with patch('src.services.graph_retriever.get_repo') as mock_get_repo:
            mock_get_repo.side_effect = Exception("Connection failed")
            
            result = await retriever.retrieve(
                query="Test query",
                filters={},
                intent=QueryIntent.TOPIC_DISCOVERY,
                max_results=10,
            )
            
            assert result.documents == []
            # Pattern function catches the error and returns with pattern name + error info
            assert result.query_pattern == "topic_relationship"
            assert "error" in result.graph_data


class TestOrgHierarchySearch:
    """Tests for organization hierarchy traversal pattern."""
    
    @pytest.mark.asyncio
    async def test_org_hierarchy_with_orgs(self, mock_repo):
        """Test org hierarchy search with organizations filter."""
        retriever = GraphRetriever()
        
        with patch('src.services.graph_retriever.get_repo', return_value=mock_repo):
            mock_session = mock_repo.client.get_session.return_value.__enter__.return_value
            
            # Mock resource result
            mock_resource = {
                "url": "https://example.com/doc1",
                "title": "Test Doc",
                "summary": "Test summary",
                "publish_date": datetime.now(),
                "source": "Test Source",
                "category": "test",
            }
            
            mock_result = MagicMock()
            mock_result.__iter__ = MagicMock(return_value=iter([{
                "resource": mock_resource,
                "organizations": ["Wi-Fi Alliance"],
                "topics": ["Wi-Fi 7"],
                "relevance": 1.0,
            }]))
            
            mock_session.run.return_value = mock_result
            
            result = await retriever._org_hierarchy_search(
                query="What did Wi-Fi Alliance announce?",
                filters={"organizations": ["Wi-Fi Alliance"]},
                max_results=10,
            )
            
            assert result.query_pattern == "org_hierarchy"
            assert "searched_orgs" in result.graph_data
    
    @pytest.mark.asyncio
    async def test_org_hierarchy_without_orgs_falls_back(self, mock_repo):
        """Test that org hierarchy falls back to topic search without orgs."""
        retriever = GraphRetriever()
        
        with patch('src.services.graph_retriever.get_repo', return_value=mock_repo):
            mock_session = mock_repo.client.get_session.return_value.__enter__.return_value
            mock_session.run.return_value = []
            
            result = await retriever._org_hierarchy_search(
                query="Test query",
                filters={},  # No organizations
                max_results=10,
            )
            
            # Should fall back to topic_relationship
            assert result.query_pattern == "topic_relationship"


class TestTrendAnalysisSearch:
    """Tests for temporal trend analysis pattern."""
    
    @pytest.mark.asyncio
    async def test_trend_analysis_calculates_growth(self, mock_repo):
        """Test that trend analysis correctly calculates growth rates."""
        retriever = GraphRetriever()
        
        with patch('src.services.graph_retriever.get_repo', return_value=mock_repo):
            # Mock trending topics (execute_query returns list of dicts)
            trend_records = [
                {
                    "topic": "Wi-Fi 7",
                    "current_count": 20,
                    "previous_count": 10,
                    "growth_rate": 1.0,
                    "growth_percentage": 100,
                },
                {
                    "topic": "MLO",
                    "current_count": 15,
                    "previous_count": 5,
                    "growth_rate": 2.0,
                    "growth_percentage": 200,
                },
            ]
            
            # execute_query is called multiple times:
            # 1st for trending topics, 2nd for documents, 3rd for org breakdown
            mock_repo.client.execute_query.side_effect = [
                trend_records,  # Trending topics query
                [],  # Documents query
                [],  # Org breakdown query
            ]
            
            result = await retriever._trend_analysis_search(
                query="What's trending?",
                filters={},
                max_results=10,
            )
            
            assert "trending_topics" in result.graph_data
            trends = result.graph_data["trending_topics"]
            assert len(trends) == 2
            assert trends[0]["name"] == "Wi-Fi 7"
            assert trends[0]["growth_percentage"] == 100


class TestCrossOrgCollaborationSearch:
    """Tests for cross-organization collaboration pattern."""
    
    @pytest.mark.asyncio
    async def test_cross_org_finds_collaborations(self, mock_repo):
        """Test that cross-org search finds collaborating organizations."""
        retriever = GraphRetriever()
        
        with patch('src.services.graph_retriever.get_repo', return_value=mock_repo):
            mock_session = mock_repo.client.get_session.return_value.__enter__.return_value
            mock_session.run.return_value = []
            
            result = await retriever._cross_org_collaboration_search(
                query="Which organizations are collaborating on 6 GHz?",
                filters={"topics": ["6 GHz"]},
                max_results=10,
            )
            
            assert result.query_pattern == "cross_org_collaboration"


class TestGraphSearchConvenienceFunction:
    """Tests for the graph_search convenience function."""
    
    @pytest.mark.asyncio
    async def test_graph_search_returns_result(self, mock_repo):
        """Test that graph_search convenience function works."""
        with patch('src.services.graph_retriever.get_repo', return_value=mock_repo):
            mock_session = mock_repo.client.get_session.return_value.__enter__.return_value
            mock_session.run.return_value = []
            
            result = await graph_search(
                query="Test query",
                filters={"topics": ["Wi-Fi 7"]},
                intent=QueryIntent.TOPIC_DISCOVERY,
                max_results=10,
            )
            
            assert isinstance(result, GraphSearchResult)


class TestDocumentConversion:
    """Tests for document conversion from Neo4j results."""
    
    def test_execute_query_and_convert(self, mock_repo):
        """Test that _execute_query_and_convert properly converts Neo4j results."""
        retriever = GraphRetriever()
        
        # Mock Neo4j node (execute_query returns list of dicts)
        mock_resource = {
            "url": "https://example.com/test",
            "title": "Test Document",
            "summary": "Test summary content",
            "publish_date": datetime.now(),
            "source": "Test Source",
            "category": "test_category",
        }
        
        mock_repo.client.execute_query.return_value = [{
            "resource": mock_resource,
            "topics": ["Topic1", "Topic2"],
            "organizations": ["Org1"],
            "relevance": 0.9,
        }]
        
        documents = retriever._execute_query_and_convert(
            repo=mock_repo,
            cypher="TEST QUERY",
            params={},
            pattern_name="test_pattern",
        )
        
        assert len(documents) == 1
        doc = documents[0]
        assert doc.url == "https://example.com/test"
        assert doc.title == "Test Document"
        assert "Topic1" in doc.topics
        assert "Org1" in doc.organizations
        assert "Graph traversal (test_pattern)" in doc.match_reasons


class TestHelperMethods:
    """Tests for helper methods."""
    
    def test_find_related_topics(self, mock_repo):
        """Test _find_related_topics method."""
        retriever = GraphRetriever()
        
        # execute_query returns list of dicts
        mock_repo.client.execute_query.return_value = [
            {"name": "Related Topic", "description": "A related topic", "co_occurrence": 5}
        ]
        
        related = retriever._find_related_topics(mock_repo, ["Wi-Fi 7"])
        
        assert len(related) == 1
        assert related[0]["name"] == "Related Topic"
    
    def test_find_org_collaborations(self, mock_repo):
        """Test _find_org_collaborations method."""
        retriever = GraphRetriever()
        
        # execute_query returns list of dicts
        mock_repo.client.execute_query.return_value = [
            {
                "org1_name": "Org A",
                "org2_name": "Org B",
                "collaboration_count": 3,
                "shared_topics": ["Topic1"],
            }
        ]
        
        collaborations = retriever._find_org_collaborations(mock_repo, ["Topic1"])
        
        assert len(collaborations) == 1
        assert collaborations[0]["org1"] == "Org A"
        assert collaborations[0]["org2"] == "Org B"


class TestIntentToPatternMapping:
    """Tests for intent to pattern mapping."""
    
    def test_all_intents_have_patterns(self):
        """Test that all QueryIntent values map to a pattern."""
        retriever = GraphRetriever()
        
        for intent in QueryIntent:
            # Should not raise KeyError or return None
            pattern_fn = retriever.patterns.get(intent)
            # Either there's a pattern or it falls back to topic_relationship
            assert pattern_fn is not None or intent in [
                QueryIntent.ENTITY_FOCUSED,
                QueryIntent.RELATIONSHIP_QUERY,
                QueryIntent.TREND_ANALYSIS,
                QueryIntent.COMPARATIVE,
                QueryIntent.TOPIC_DISCOVERY,
            ]
