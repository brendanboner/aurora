"""
Quick test for algorithmic inference functionality.

Run with: python -m pytest testing/unit/test_algorithmic_inference.py -v
"""

import pytest
import numpy as np
from services.algorithmic_inference import AlgorithmicHierarchyInference


class TestAlgorithmicInference:
    """Tests for the AlgorithmicHierarchyInference class."""
    
    @pytest.fixture
    def inference_engine(self):
        """Create inference engine instance."""
        return AlgorithmicHierarchyInference()
    
    @pytest.fixture
    def sample_topics(self):
        """Sample topics with clear hierarchical patterns."""
        embedding_wifi = [0.9, 0.1] + [0.1] * 14
        embedding_wifi6 = [0.88, 0.12] + [0.1] * 14
        embedding_wifi7 = [0.87, 0.13] + [0.1] * 14
        
        return [
            {
                'topic_id': 'wifi',
                'name': 'Wi-Fi',
                'classification': 'technology',
                'embedding': embedding_wifi
            },
            {
                'topic_id': 'wifi-6',
                'name': 'Wi-Fi 6',
                'classification': 'technology',
                'embedding': embedding_wifi6
            },
            {
                'topic_id': 'wifi-7',
                'name': 'Wi-Fi 7',
                'classification': 'technology',
                'embedding': embedding_wifi7
            }
        ]
    
    def test_infer_from_names_version(self, inference_engine, sample_topics):
        """Test name pattern detection for version numbers."""
        relationships = inference_engine.infer_from_names(sample_topics)
        
        # Should detect "Wi-Fi" -> "Wi-Fi 6" and "Wi-Fi" -> "Wi-Fi 7"
        assert len(relationships) >= 2
        
        # Check that Wi-Fi is parent
        wifi_as_parent = [
            r for r in relationships 
            if r['source_topic_id'] == 'wifi'
        ]
        assert len(wifi_as_parent) >= 2
        
        # Check high confidence for version patterns
        for rel in wifi_as_parent:
            assert rel['confidence'] >= 0.90
    
    def test_infer_from_names_no_false_positives(self, inference_engine):
        """Test that unrelated topics don't create relationships."""
        topics = [
            {
                'topic_id': 'security',
                'name': 'Security',
                'classification': 'domain',
                'embedding': [0.5] * 16
            },
            {
                'topic_id': 'networking',
                'name': 'Networking',
                'classification': 'domain',
                'embedding': [0.4] * 16
            }
        ]
        
        relationships = inference_engine.infer_from_names(topics)
        
        # Should not create relationship between unrelated terms
        assert len(relationships) == 0
    
    def test_infer_from_embeddings(self, inference_engine, sample_topics):
        """Test embedding-based centrality detection."""
        relationships = inference_engine.infer_from_embeddings(sample_topics)
        
        # Should find some relationships based on similarity
        assert isinstance(relationships, list)
        
        # Each relationship should have required fields
        for rel in relationships:
            assert 'source_topic_id' in rel
            assert 'target_topic_id' in rel
            assert 'confidence' in rel
            assert 'method' in rel
            assert rel['method'] == 'embedding_centrality'
    
    def test_merge_relationships(self, inference_engine):
        """Test merging relationships from multiple methods."""
        name_rels = [
            {
                'source_topic_id': 'a',
                'target_topic_id': 'b',
                'confidence': 0.90,
                'method': 'name_pattern',
                'reasoning': 'Name match'
            }
        ]
        
        embedding_rels = [
            {
                'source_topic_id': 'a',
                'target_topic_id': 'b',
                'confidence': 0.70,
                'method': 'embedding_centrality',
                'reasoning': 'Embedding match'
            }
        ]
        
        high_conf, needs_review = inference_engine.merge_and_filter_relationships(
            name_rels,
            embedding_rels,
            [],
            [],
            confidence_threshold=0.75
        )
        
        # Should merge into one relationship with boosted confidence
        assert len(high_conf) == 1
        assert high_conf[0]['source_topic_id'] == 'a'
        assert high_conf[0]['target_topic_id'] == 'b'
        # Confidence should be average + bonus for multiple methods
        assert high_conf[0]['confidence'] > 0.80
    
    def test_classification_hierarchy(self, inference_engine):
        """Test classification-based hierarchy detection."""
        topics = [
            {
                'topic_id': 'domain-tech',
                'name': 'Technology',
                'classification': 'domain',
                'embedding': [0.5, 0.5] + [0.1] * 14
            },
            {
                'topic_id': 'protocol-http',
                'name': 'HTTP',
                'classification': 'protocol',
                'embedding': [0.52, 0.48] + [0.1] * 14  # Similar embedding
            }
        ]
        
        relationships = inference_engine.infer_from_classification(topics)
        
        # Should detect domain > protocol hierarchy
        assert len(relationships) >= 1
        domain_to_protocol = [
            r for r in relationships
            if r['source_topic_id'] == 'domain-tech' and r['target_topic_id'] == 'protocol-http'
        ]
        assert len(domain_to_protocol) >= 1
    
    def test_full_inference_pipeline(self, inference_engine, sample_topics):
        """Test complete inference pipeline."""
        high_confidence, needs_review = inference_engine.infer_all_relationships(
            sample_topics,
            confidence_threshold=0.75
        )
        
        # Should find relationships
        total_rels = len(high_confidence) + len(needs_review)
        assert total_rels >= 2  # At least Wi-Fi -> Wi-Fi 6/7
        
        # High confidence should have proper structure
        for rel in high_confidence:
            assert 'source_topic_id' in rel
            assert 'target_topic_id' in rel
            assert 'relationship_type' in rel
            assert rel['relationship_type'] == 'ENCOMPASSES'
            assert 'confidence' in rel
            assert rel['confidence'] >= 0.75
            assert 'reasoning' in rel
    
    def test_empty_topics(self, inference_engine):
        """Test handling of empty topic list."""
        high_confidence, needs_review = inference_engine.infer_all_relationships(
            [],
            confidence_threshold=0.75
        )
        
        assert len(high_confidence) == 0
        assert len(needs_review) == 0
    
    def test_topics_without_embeddings(self, inference_engine):
        """Test handling of topics without embeddings."""
        topics = [
            {
                'topic_id': 'a',
                'name': 'Topic A',
                'classification': 'technology'
                # No embedding
            },
            {
                'topic_id': 'b',
                'name': 'Topic B',
                'classification': 'protocol'
                # No embedding
            }
        ]
        
        # Should not crash, but won't find embedding-based relationships
        high_confidence, needs_review = inference_engine.infer_all_relationships(
            topics,
            confidence_threshold=0.75
        )
        
        # Should complete without error
        assert isinstance(high_confidence, list)
        assert isinstance(needs_review, list)
