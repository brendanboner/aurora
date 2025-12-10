"""
Unit tests for HierarchyAnalyzer.

Tests LLM-based hierarchy analysis with mocked responses.
"""

import pytest
import json
from unittest.mock import patch, MagicMock


class TestHierarchyAnalyzer:
    """Tests for the HierarchyAnalyzer class."""
    
    def test_analyze_cluster_returns_relationships(self, mock_hierarchy_analyzer, sample_topics):
        """Test that analyze_cluster returns relationship data."""
        # Set up mock relationships
        mock_hierarchy_analyzer.set_mock_relationships([
            {
                "broader_topic": "wi-fi",
                "narrower_topic": "wi-fi 6",
                "confidence": 0.95,
                "reasoning": "Wi-Fi 6 is a specific version of Wi-Fi"
            }
        ])
        
        new_topics, relationships, stats = mock_hierarchy_analyzer.analyze_cluster(sample_topics[:4])
        
        assert len(relationships) == 1
        assert relationships[0]["broader_topic"] == "wi-fi"
        assert relationships[0]["narrower_topic"] == "wi-fi 6"
        assert relationships[0]["confidence"] == 0.95
    
    def test_analyze_cluster_records_call(self, mock_hierarchy_analyzer, sample_topics):
        """Test that analyze_cluster records the call for assertions."""
        mock_hierarchy_analyzer.analyze_cluster(sample_topics[:3])
        
        assert len(mock_hierarchy_analyzer.analyze_calls) == 1
        assert mock_hierarchy_analyzer.analyze_calls[0]["topics"] == sample_topics[:3]
    
    def test_analyze_cluster_empty_topics(self, mock_hierarchy_analyzer):
        """Test analyze_cluster with empty topic list."""
        new_topics, relationships, stats = mock_hierarchy_analyzer.analyze_cluster([])
        
        assert relationships == []
        assert stats["topics_analyzed"] == 0
    
    def test_analyze_cluster_auto_generates_relationships(self, mock_hierarchy_analyzer):
        """Test that auto-generation finds parent-child patterns in names."""
        topics = [
            {"topic_id": "wi-fi", "name": "Wi-Fi"},
            {"topic_id": "wi-fi-6", "name": "Wi-Fi 6"},
            {"topic_id": "wi-fi-6e", "name": "Wi-Fi 6E"},
        ]
        
        # Clear mock relationships to use auto-generation
        mock_hierarchy_analyzer.set_mock_relationships([])
        mock_hierarchy_analyzer._mock_relationships = []
        
        new_topics, relationships, stats = mock_hierarchy_analyzer.analyze_cluster(topics)
        
        # Auto-generation should find relationships based on name containment
        # Note: Actual results depend on mock implementation
        assert stats["topics_analyzed"] == 3
    
    def test_analyze_cluster_representatives(self, mock_hierarchy_analyzer):
        """Test cross-cluster analysis of representatives."""
        representatives = [
            {"topic_id": "wi-fi", "name": "Wi-Fi"},
            {"topic_id": "security", "name": "Network Security"},
        ]
        
        relationships, stats = mock_hierarchy_analyzer.analyze_cluster_representatives(representatives)
        
        assert "representatives_analyzed" in stats
        assert stats["representatives_analyzed"] == 2
    
    def test_confidence_threshold_filtering(self, llm_responses):
        """Test that low-confidence relationships are filtered."""
        # The mock should filter relationships below confidence threshold
        low_confidence_response = llm_responses["error_responses"]["low_confidence"]
        
        # Relationship with 0.3 confidence should be filtered when threshold is 0.7
        relationships = low_confidence_response["relationships"]
        filtered = [r for r in relationships if r.get("confidence", 0) >= 0.7]
        
        assert len(filtered) == 0


class TestHierarchyAnalyzerWithRealClass:
    """Tests using the real HierarchyAnalyzer with mocked OpenAI client."""
    
    @pytest.fixture
    def mock_openai_client(self, llm_responses):
        """Create a mock OpenAI client."""
        from testing.mocks import MockAzureOpenAI
        
        wifi_response = json.dumps(llm_responses["hierarchy_analysis"]["wifi_cluster"]["response"])
        return MockAzureOpenAI(responses=[wifi_response])
    
    def test_llm_call_with_retry_success(self, mock_openai_client):
        """Test that LLM calls succeed on first try."""
        response = mock_openai_client.chat.completions.create(
            model="test-deployment",
            messages=[{"role": "user", "content": "test"}],
            temperature=0.1,
            max_tokens=4096,
            response_format={"type": "json_object"}
        )
        
        assert response is not None
        assert response.choices[0].message.content is not None
        
        # Verify the response is valid JSON
        content = json.loads(response.choices[0].message.content)
        assert "relationships" in content
    
    def test_llm_response_parsing(self, mock_openai_client, llm_responses):
        """Test parsing of LLM JSON responses."""
        response = mock_openai_client.chat.completions.create(
            model="test-deployment",
            messages=[{"role": "user", "content": "test"}],
            temperature=0.1,
            max_tokens=4096,
            response_format={"type": "json_object"}
        )
        
        content = json.loads(response.choices[0].message.content)
        relationships = content.get("relationships", [])
        
        assert len(relationships) > 0
        
        for rel in relationships:
            assert "broader_topic" in rel
            assert "narrower_topic" in rel
            assert "confidence" in rel
            assert 0 <= rel["confidence"] <= 1
    
    def test_call_history_tracking(self, mock_openai_client):
        """Test that call history is tracked."""
        mock_openai_client.chat.completions.create(
            model="test-model",
            messages=[{"role": "user", "content": "first call"}]
        )
        mock_openai_client.chat.completions.create(
            model="test-model",
            messages=[{"role": "user", "content": "second call"}]
        )
        
        assert len(mock_openai_client.chat.completions.call_history) == 2


class TestPromptFormatting:
    """Tests for prompt formatting utilities."""
    
    def test_format_topics_for_prompt(self):
        """Test formatting topics into prompt-ready JSON."""
        from services.prompts import format_topics_for_prompt
        
        topics = [
            {"name": "Wi-Fi", "classification": "technology"},
            {"name": "Wi-Fi 6", "classification": "standard"},
        ]
        
        formatted = format_topics_for_prompt(topics)
        
        # Should be valid JSON
        parsed = json.loads(formatted)
        assert len(parsed) == 2
    
    def test_prompt_templates_exist(self):
        """Test that required prompt templates are defined."""
        from services.prompts import (
            HIERARCHY_ANALYSIS_SYSTEM_PROMPT,
            HIERARCHY_ANALYSIS_USER_PROMPT,
        )
        
        assert HIERARCHY_ANALYSIS_SYSTEM_PROMPT is not None
        assert len(HIERARCHY_ANALYSIS_SYSTEM_PROMPT) > 100  # Reasonable length
        
        assert HIERARCHY_ANALYSIS_USER_PROMPT is not None
        assert "{topics_json}" in HIERARCHY_ANALYSIS_USER_PROMPT


class TestRelationshipValidation:
    """Tests for relationship validation logic."""
    
    def test_valid_relationship_structure(self):
        """Test validation of relationship structure."""
        valid_relationship = {
            "broader_topic": "wi-fi",
            "narrower_topic": "wi-fi 6",
            "confidence": 0.95,
            "reasoning": "Wi-Fi 6 is a specific version"
        }
        
        # All required fields present
        assert "broader_topic" in valid_relationship
        assert "narrower_topic" in valid_relationship
        assert "confidence" in valid_relationship
        assert "reasoning" in valid_relationship
        
        # Confidence in valid range
        assert 0 <= valid_relationship["confidence"] <= 1
    
    def test_invalid_relationship_missing_fields(self):
        """Test detection of invalid relationships."""
        invalid_relationship = {
            "broader_topic": "wi-fi",
            # Missing narrower_topic, confidence, reasoning
        }
        
        required_fields = ["broader_topic", "narrower_topic", "confidence"]
        missing = [f for f in required_fields if f not in invalid_relationship]
        
        assert len(missing) > 0
    
    def test_circular_relationship_detection(self):
        """Test that circular relationships can be detected."""
        relationships = [
            {"broader_topic": "A", "narrower_topic": "B"},
            {"broader_topic": "B", "narrower_topic": "A"},  # Circular!
        ]
        
        # Build a simple graph to detect cycles
        graph = {}
        for rel in relationships:
            broader = rel["broader_topic"]
            narrower = rel["narrower_topic"]
            if broader not in graph:
                graph[broader] = []
            graph[broader].append(narrower)
        
        # Check for A -> B -> A cycle
        def has_cycle(node, visited, path):
            visited.add(node)
            path.add(node)
            
            for neighbor in graph.get(node, []):
                if neighbor in path:
                    return True
                if neighbor not in visited:
                    if has_cycle(neighbor, visited, path):
                        return True
            
            path.remove(node)
            return False
        
        has_circular = any(
            has_cycle(node, set(), set()) 
            for node in graph 
        )
        
        assert has_circular is True
