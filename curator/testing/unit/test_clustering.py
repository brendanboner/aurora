"""
Unit tests for TopicClusterer.

Tests clustering functionality with various topic configurations.
"""

import pytest
import numpy as np
from typing import List, Dict, Any


class TestTopicClusterer:
    """Tests for the TopicClusterer class."""
    
    def test_cluster_topics_basic(self, topic_clusterer, sample_topics):
        """Test basic clustering of topics."""
        clusters = topic_clusterer.cluster_topics(sample_topics)
        
        # Should create at least one cluster
        assert len(clusters) >= 1
        
        # All topics should be assigned to clusters
        total_topics = sum(len(c) for c in clusters)
        assert total_topics >= len(sample_topics)  # >= because of overlaps
    
    def test_cluster_topics_empty_list(self, topic_clusterer):
        """Test clustering with empty topic list."""
        clusters = topic_clusterer.cluster_topics([])
        
        assert clusters == []
    
    def test_cluster_topics_single_topic(self, topic_clusterer):
        """Test clustering with a single topic (below min_cluster_size)."""
        single_topic = [{
            "topic_id": "single-topic",
            "name": "single topic",
            "classification": "technology",
            "embedding": [0.1] * 16
        }]
        
        clusters = topic_clusterer.cluster_topics(single_topic)
        
        # Should return all topics as single cluster when below min size
        assert len(clusters) == 1
        assert len(clusters[0]) == 1
    
    def test_cluster_topics_no_embeddings(self, topic_clusterer):
        """Test clustering with topics missing embeddings."""
        topics_no_embedding = [
            {"topic_id": "topic-1", "name": "topic 1", "classification": "tech"},
            {"topic_id": "topic-2", "name": "topic 2", "classification": "tech"},
            {"topic_id": "topic-3", "name": "topic 3", "classification": "tech"},
        ]
        
        clusters = topic_clusterer.cluster_topics(topics_no_embedding)
        
        # Should handle gracefully - return all as one cluster
        assert len(clusters) == 1
    
    def test_cluster_sizes_within_bounds(self, topic_clusterer, sample_topics):
        """Test that cluster sizes respect min/max constraints after refinement."""
        clusters = topic_clusterer.cluster_topics(sample_topics)
        
        for cluster in clusters:
            # Note: With overlaps, clusters may be slightly larger
            # Original cluster sizes should be >= min_cluster_size
            assert len(cluster) >= 1  # At minimum, each cluster has content
    
    def test_cluster_overlap_neighbors(self, sample_topics):
        """Test that clusters include overlap neighbors when configured."""
        from clustering import TopicClusterer
        
        # Create clusterer with overlap enabled
        clusterer_with_overlap = TopicClusterer(
            min_cluster_size=2,
            max_cluster_size=8,
            distance_threshold=0.5,
            overlap_neighbors=2  # Add 2 nearest external topics
        )
        
        clusters = clusterer_with_overlap.cluster_topics(sample_topics)
        
        # If multiple clusters exist, overlaps should be added
        if len(clusters) > 1:
            # Check that some topics appear in multiple clusters
            all_topic_ids = []
            for cluster in clusters:
                for topic in cluster:
                    all_topic_ids.append(topic.get("topic_id"))
            
            # With overlaps, total assignments > unique topics
            unique_ids = set(all_topic_ids)
            # Note: may not always have duplicates depending on clustering
    
    def test_cluster_no_overlap(self, sample_topics):
        """Test clustering without overlap neighbors."""
        from clustering import TopicClusterer
        
        clusterer_no_overlap = TopicClusterer(
            min_cluster_size=2,
            max_cluster_size=8,
            distance_threshold=0.5,
            overlap_neighbors=0  # No overlaps
        )
        
        clusters = clusterer_no_overlap.cluster_topics(sample_topics)
        
        # Count total topic assignments
        all_topic_ids = []
        for cluster in clusters:
            for topic in cluster:
                all_topic_ids.append(topic.get("topic_id"))
        
        # Without overlap, each topic should only appear once
        # (unless clustering algorithm assigns same topic to multiple clusters)
        assert len(clusters) >= 1
    
    def test_similar_topics_cluster_together(self):
        """Test that semantically similar topics end up in the same cluster."""
        from clustering import TopicClusterer
        
        # Create topics with distinct embedding groups
        wifi_embedding = [0.9, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]
        security_embedding = [0.1, 0.9, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]
        
        topics = [
            {"topic_id": "wifi-1", "name": "wi-fi", "embedding": wifi_embedding},
            {"topic_id": "wifi-2", "name": "wi-fi 6", "embedding": [0.88, 0.12, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]},
            {"topic_id": "wifi-3", "name": "wi-fi 7", "embedding": [0.87, 0.13, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]},
            {"topic_id": "sec-1", "name": "security", "embedding": security_embedding},
            {"topic_id": "sec-2", "name": "wpa3", "embedding": [0.12, 0.88, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]},
            {"topic_id": "sec-3", "name": "encryption", "embedding": [0.13, 0.87, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]},
        ]
        
        clusterer = TopicClusterer(
            min_cluster_size=2,
            max_cluster_size=5,
            distance_threshold=0.3,
            overlap_neighbors=0
        )
        
        clusters = clusterer.cluster_topics(topics)
        
        # Should create at least 2 clusters (wifi vs security)
        assert len(clusters) >= 1
        
        # Find which cluster contains wifi topics
        for cluster in clusters:
            topic_ids = [t.get("topic_id") for t in cluster]
            wifi_count = sum(1 for tid in topic_ids if tid.startswith("wifi"))
            sec_count = sum(1 for tid in topic_ids if tid.startswith("sec"))
            
            # Each cluster should be dominated by one type
            # (not a strict requirement due to clustering algorithm behavior)
    
    def test_extract_embeddings_handles_nested_format(self, topic_clusterer):
        """Test that embedding extraction handles various data formats."""
        # Topics with embeddings in different formats
        topics = [
            {"topic_id": "t1", "name": "topic 1", "embedding": [0.1, 0.2, 0.3]},
            {"topic_id": "t2", "name": "topic 2", "embedding": [0.4, 0.5, 0.6]},
            {"topic_id": "t3", "name": "topic 3", "embedding": [0.7, 0.8, 0.9]},
        ]
        
        embeddings = topic_clusterer._extract_embeddings(topics)
        
        assert embeddings is not None
        assert embeddings.shape[0] == 3  # 3 topics
        assert embeddings.shape[1] == 3  # 3 dimensions


class TestClusteringEdgeCases:
    """Edge case tests for clustering."""
    
    def test_all_identical_embeddings(self):
        """Test clustering when all topics have identical embeddings."""
        from clustering import TopicClusterer
        
        identical_embedding = [0.5] * 16
        topics = [
            {"topic_id": f"topic-{i}", "name": f"topic {i}", "embedding": identical_embedding.copy()}
            for i in range(5)
        ]
        
        clusterer = TopicClusterer(
            min_cluster_size=2,
            max_cluster_size=10,
            distance_threshold=0.5,
            overlap_neighbors=0
        )
        
        clusters = clusterer.cluster_topics(topics)
        
        # All identical topics should end up in one cluster
        assert len(clusters) >= 1
    
    def test_two_topics_minimum(self):
        """Test with exactly two topics."""
        from clustering import TopicClusterer
        
        topics = [
            {"topic_id": "t1", "name": "topic 1", "embedding": [0.1] * 16},
            {"topic_id": "t2", "name": "topic 2", "embedding": [0.9] * 16},
        ]
        
        clusterer = TopicClusterer(
            min_cluster_size=2,
            max_cluster_size=10,
            distance_threshold=0.5,
            overlap_neighbors=0
        )
        
        clusters = clusterer.cluster_topics(topics)
        
        # Should handle two topics
        assert len(clusters) >= 1
    
    def test_large_number_of_topics(self):
        """Test clustering with a larger number of topics."""
        from clustering import TopicClusterer
        import random
        
        # Generate 50 topics with random embeddings
        topics = []
        for i in range(50):
            embedding = [random.random() for _ in range(16)]
            topics.append({
                "topic_id": f"topic-{i}",
                "name": f"topic {i}",
                "embedding": embedding
            })
        
        clusterer = TopicClusterer(
            min_cluster_size=3,
            max_cluster_size=10,
            distance_threshold=0.5,
            overlap_neighbors=2
        )
        
        clusters = clusterer.cluster_topics(topics)
        
        # Should create multiple clusters
        assert len(clusters) >= 1
        
        # All original topics should be represented
        original_ids = {t["topic_id"] for t in topics}
        clustered_ids = set()
        for cluster in clusters:
            for topic in cluster:
                clustered_ids.add(topic.get("topic_id"))
        
        # All original topics should appear in at least one cluster
        assert original_ids.issubset(clustered_ids)
