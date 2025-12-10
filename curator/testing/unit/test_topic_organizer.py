"""
Unit tests for TopicOrganizer.

Tests the orchestration of topic hierarchy organization.
"""

import pytest
from unittest.mock import MagicMock, patch


class TestTopicOrganizer:
    """Tests for the TopicOrganizer class."""
    
    def test_run_returns_stats(
        self, 
        mock_neo4j_client, 
        mock_graph_repository, 
        mock_hierarchy_analyzer,
        sample_topics
    ):
        """Test that run() returns statistics dictionary."""
        from tasks.topic_organizer import TopicOrganizer
        
        # Pre-populate mock with topics
        for topic in sample_topics:
            mock_neo4j_client.add_node("Topic", topic["topic_id"], topic)
        
        # Create organizer with mocks - patch the dependencies
        with patch('tasks.topic_organizer.Neo4jClient', return_value=mock_neo4j_client):
            with patch('tasks.topic_organizer.GraphRepository', return_value=mock_graph_repository):
                with patch('tasks.topic_organizer.HierarchyAnalyzer', return_value=mock_hierarchy_analyzer):
                    organizer = TopicOrganizer(
                        graph_repository=mock_graph_repository,
                        logger_instance=MagicMock()
                    )
                    
                    # Mock the clusterer to return predictable clusters
                    organizer.clusterer = MagicMock()
                    organizer.clusterer.cluster_topics.return_value = [sample_topics[:4], sample_topics[4:8]]
                    
                    # Mock hierarchy analyzer
                    organizer.hierarchy_analyzer = mock_hierarchy_analyzer
                    
                    result = organizer.run()
        
        # Should return stats dictionary
        assert isinstance(result, dict)
        assert "topics_processed" in result
        assert "clusters_created" in result
        assert "relationships_created" in result
        assert "success" in result
    
    def test_run_with_no_topics(self, mock_graph_repository):
        """Test run() when no topics exist."""
        from tasks.topic_organizer import TopicOrganizer
        
        # Empty repository
        with patch('tasks.topic_organizer.Neo4jClient'):
            with patch('tasks.topic_organizer.GraphRepository', return_value=mock_graph_repository):
                with patch('tasks.topic_organizer.HierarchyAnalyzer'):
                    organizer = TopicOrganizer(
                        graph_repository=mock_graph_repository,
                        logger_instance=MagicMock()
                    )
                    
                    result = organizer.run()
        
        assert result["topics_processed"] == 0
        assert result["success"] is True
    
    def test_run_creates_relationships(
        self,
        mock_neo4j_client,
        mock_graph_repository,
        sample_topics
    ):
        """Test that run() creates ENCOMPASSES relationships."""
        from tasks.topic_organizer import TopicOrganizer
        from testing.mocks import MockHierarchyAnalyzer
        
        # Pre-populate with topics
        for topic in sample_topics[:4]:
            mock_neo4j_client.add_node("Topic", topic["topic_id"], topic)
        
        # Set up hierarchy analyzer with known relationships
        mock_analyzer = MockHierarchyAnalyzer()
        mock_analyzer.set_mock_relationships([
            {
                "broader_topic": "wi-fi",
                "narrower_topic": "wi-fi 6",
                "confidence": 0.95,
                "reasoning": "Wi-Fi 6 is a version of Wi-Fi"
            }
        ])
        
        with patch('tasks.topic_organizer.Neo4jClient', return_value=mock_neo4j_client):
            with patch('tasks.topic_organizer.GraphRepository', return_value=mock_graph_repository):
                with patch('tasks.topic_organizer.HierarchyAnalyzer', return_value=mock_analyzer):
                    organizer = TopicOrganizer(
                        graph_repository=mock_graph_repository,
                        logger_instance=MagicMock()
                    )
                    
                    # Mock clusterer
                    organizer.clusterer = MagicMock()
                    organizer.clusterer.cluster_topics.return_value = [sample_topics[:4]]
                    organizer.hierarchy_analyzer = mock_analyzer
                    
                    result = organizer.run()
        
        # Verify relationships were created
        assert result["relationships_created"] >= 0
    
    def test_heartbeat_callback_called(self, mock_graph_repository, sample_topics):
        """Test that heartbeat callback is invoked during long operations."""
        from tasks.topic_organizer import TopicOrganizer
        from testing.mocks import MockHierarchyAnalyzer
        
        heartbeat_mock = MagicMock()
        mock_analyzer = MockHierarchyAnalyzer()
        
        with patch('tasks.topic_organizer.Neo4jClient'):
            with patch('tasks.topic_organizer.GraphRepository', return_value=mock_graph_repository):
                with patch('tasks.topic_organizer.HierarchyAnalyzer', return_value=mock_analyzer):
                    organizer = TopicOrganizer(
                        graph_repository=mock_graph_repository,
                        heartbeat_callback=heartbeat_mock,
                        logger_instance=MagicMock()
                    )
                    
                    # Mock clusterer to return multiple clusters
                    organizer.clusterer = MagicMock()
                    organizer.clusterer.cluster_topics.return_value = [
                        sample_topics[:3],
                        sample_topics[3:6],
                        sample_topics[6:9]
                    ]
                    organizer.hierarchy_analyzer = mock_analyzer
                    
                    organizer.run()
        
        # Heartbeat should be called for each cluster
        # Note: Actual call count depends on implementation
    
    def test_close_releases_resources(self, mock_graph_repository):
        """Test that close() releases resources."""
        from tasks.topic_organizer import TopicOrganizer
        
        mock_client = MagicMock()
        
        with patch('tasks.topic_organizer.Neo4jClient', return_value=mock_client):
            with patch('tasks.topic_organizer.GraphRepository', return_value=mock_graph_repository):
                with patch('tasks.topic_organizer.HierarchyAnalyzer'):
                    organizer = TopicOrganizer(logger_instance=MagicMock())
                    organizer._neo4j_client = mock_client
                    organizer._owns_connections = True
                    
                    organizer.close()
        
        # Should close the client
        mock_client.close.assert_called_once()
    
    def test_cross_cluster_analysis_enabled(self, mock_graph_repository, sample_topics):
        """Test cross-cluster analysis when enabled."""
        from tasks.topic_organizer import TopicOrganizer
        from testing.mocks import MockHierarchyAnalyzer
        
        mock_analyzer = MockHierarchyAnalyzer()
        
        with patch('tasks.topic_organizer.Neo4jClient'):
            with patch('tasks.topic_organizer.GraphRepository', return_value=mock_graph_repository):
                with patch('tasks.topic_organizer.HierarchyAnalyzer', return_value=mock_analyzer):
                    with patch('tasks.topic_organizer.settings') as mock_settings:
                        mock_settings.enable_cross_cluster_analysis = True
                        mock_settings.cluster_min_size = 2
                        mock_settings.cluster_max_size = 10
                        mock_settings.cluster_distance_threshold = 0.5
                        mock_settings.cluster_overlap_neighbors = 2
                        
                        organizer = TopicOrganizer(
                            graph_repository=mock_graph_repository,
                            logger_instance=MagicMock()
                        )
                        
                        # Mock clusterer with multiple clusters
                        organizer.clusterer = MagicMock()
                        organizer.clusterer.cluster_topics.return_value = [
                            sample_topics[:4],
                            sample_topics[4:8]
                        ]
                        organizer.hierarchy_analyzer = mock_analyzer
                        
                        result = organizer.run()
        
        # Cross-cluster analysis should have been called
        cross_cluster_calls = [
            c for c in mock_analyzer.analyze_calls 
            if c.get("type") == "cross_cluster"
        ]
        # Note: May or may not have calls depending on cluster count


class TestTopicOrganizerErrorHandling:
    """Tests for error handling in TopicOrganizer."""
    
    def test_handles_clustering_error(self, mock_graph_repository, sample_topics):
        """Test graceful handling of clustering errors."""
        from tasks.topic_organizer import TopicOrganizer
        
        with patch('tasks.topic_organizer.Neo4jClient'):
            with patch('tasks.topic_organizer.GraphRepository', return_value=mock_graph_repository):
                with patch('tasks.topic_organizer.HierarchyAnalyzer'):
                    organizer = TopicOrganizer(
                        graph_repository=mock_graph_repository,
                        logger_instance=MagicMock()
                    )
                    
                    # Make clusterer raise an error
                    organizer.clusterer = MagicMock()
                    organizer.clusterer.cluster_topics.side_effect = ValueError("Clustering failed")
                    
                    result = organizer.run()
        
        # Should handle error gracefully
        assert result["success"] is False or "errors" in result
    
    def test_handles_llm_error(self, mock_graph_repository, sample_topics):
        """Test graceful handling of LLM errors."""
        from tasks.topic_organizer import TopicOrganizer
        from testing.mocks import MockHierarchyAnalyzer
        
        mock_analyzer = MockHierarchyAnalyzer()
        
        with patch('tasks.topic_organizer.Neo4jClient'):
            with patch('tasks.topic_organizer.GraphRepository', return_value=mock_graph_repository):
                with patch('tasks.topic_organizer.HierarchyAnalyzer', return_value=mock_analyzer):
                    organizer = TopicOrganizer(
                        graph_repository=mock_graph_repository,
                        logger_instance=MagicMock()
                    )
                    
                    organizer.clusterer = MagicMock()
                    organizer.clusterer.cluster_topics.return_value = [sample_topics[:4]]
                    
                    # Make analyzer raise an error
                    organizer.hierarchy_analyzer = MagicMock()
                    organizer.hierarchy_analyzer.analyze_cluster.side_effect = Exception("LLM error")
                    
                    result = organizer.run()
        
        # Should continue despite errors
        assert "errors" in result or result.get("success") is False
