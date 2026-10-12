"""
Mock Azure OpenAI Client and HierarchyAnalyzer for testing.

Provides mock implementations that return deterministic responses
without making actual API calls.
"""

from typing import Any, Dict, List, Optional
import json
import logging


class MockChatCompletion:
    """Mock chat completion response."""
    
    def __init__(self, content: str):
        self.choices = [MockChoice(content)]


class MockChoice:
    """Mock choice in a chat completion."""
    
    def __init__(self, content: str):
        self.message = MockMessage(content)


class MockMessage:
    """Mock message in a choice."""
    
    def __init__(self, content: str):
        self.content = content


class MockChatCompletions:
    """Mock chat completions API."""
    
    def __init__(self, responses: List[str]):
        self._responses = responses
        self._call_index = 0
        self.call_history: List[Dict[str, Any]] = []
    
    def create(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 4096,
        response_format: Optional[Dict[str, str]] = None,
    ) -> MockChatCompletion:
        """Create a chat completion (returns mock response)."""
        
        # Record the call
        self.call_history.append({
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
        })
        
        # Get the response (cycle through if more calls than responses)
        if self._responses:
            response = self._responses[self._call_index % len(self._responses)]
            self._call_index += 1
        else:
            response = '{"relationships": []}'
        
        return MockChatCompletion(response)


class MockAzureOpenAI:
    """
    Mock Azure OpenAI client.
    
    Returns predefined responses for testing hierarchy analysis.
    """
    
    def __init__(
        self,
        api_key: str = "mock-api-key",
        api_version: str = "2024-08-01-preview",
        azure_endpoint: str = "https://mock.openai.azure.com",
        responses: Optional[List[str]] = None,
    ):
        self.api_key = api_key
        self.api_version = api_version
        self.azure_endpoint = azure_endpoint
        
        # Default responses if none provided
        default_responses = [
            json.dumps({
                "relationships": [
                    {
                        "broader_topic": "Wi-Fi",
                        "narrower_topic": "Wi-Fi 6E",
                        "confidence": 0.95,
                        "reasoning": "Wi-Fi 6E is a specific version of Wi-Fi technology"
                    }
                ]
            })
        ]
        
        self.chat = MockChat(responses or default_responses)


class MockChat:
    """Mock chat API."""
    
    def __init__(self, responses: List[str]):
        self.completions = MockChatCompletions(responses)


class MockHierarchyAnalyzer:
    """
    Mock HierarchyAnalyzer for testing.
    
    Returns predefined hierarchy relationships without calling LLM.
    """
    
    def __init__(
        self,
        api_key: str = "mock-key",
        endpoint: str = "https://mock.openai.azure.com",
        deployment: str = "mock-deployment",
        api_version: str = "2024-08-01-preview",
        max_tokens: int = 4096,
        temperature: float = 0.1,
        confidence_threshold: float = 0.7,
        logger_instance: Optional[logging.Logger] = None,
        mock_relationships: Optional[List[Dict[str, Any]]] = None,
    ):
        self.deployment = deployment
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.confidence_threshold = confidence_threshold
        self.logger = logger_instance or logging.getLogger(__name__)
        
        # Predefined relationships to return
        self._mock_relationships = mock_relationships or []
        
        # Track calls for assertions
        self.analyze_calls: List[Dict[str, Any]] = []
    
    def analyze_cluster(
        self,
        topics: List[Dict[str, Any]]
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
        """
        Analyze a cluster of topics (returns mock relationships).
        
        Returns:
            Tuple of (new_topics, relationships, stats)
        """
        # Record the call
        self.analyze_calls.append({
            "topics": topics,
            "topic_names": [t.get("name") for t in topics]
        })
        
        # Generate mock relationships based on topic names
        relationships = []
        new_topics = []
        
        # If mock relationships are provided, use them
        if self._mock_relationships:
            relationships = self._mock_relationships
        else:
            # Auto-generate simple relationships based on naming patterns
            topic_names = [t.get("name", "") for t in topics]
            
            for topic in topics:
                name = topic.get("name", "")
                
                # Look for parent-child patterns
                for other_topic in topics:
                    other_name = other_topic.get("name", "")
                    
                    # Skip self
                    if name == other_name:
                        continue
                    
                    # Check if one topic name contains another (simple heuristic)
                    if other_name in name and len(other_name) < len(name):
                        # other_name is broader (e.g., "Wi-Fi" vs "Wi-Fi 6E")
                        relationships.append({
                            "broader_topic": other_name,
                            "narrower_topic": name,
                            "confidence": 0.85,
                            "reasoning": f"'{name}' is a more specific version of '{other_name}'"
                        })
        
        stats = {
            "topics_analyzed": len(topics),
            "relationships_found": len(relationships),
            "new_topics_suggested": len(new_topics),
        }
        
        return new_topics, relationships, stats
    
    def analyze_cluster_representatives(
        self,
        representatives: List[Dict[str, Any]]
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Analyze cluster representatives for cross-cluster relationships.
        
        Returns:
            Tuple of (relationships, stats)
        """
        self.analyze_calls.append({
            "type": "cross_cluster",
            "representatives": representatives,
        })
        
        # Return empty relationships by default for cross-cluster
        return [], {"representatives_analyzed": len(representatives)}
    
    def set_mock_relationships(self, relationships: List[Dict[str, Any]]):
        """Set mock relationships to return (test helper)."""
        self._mock_relationships = relationships
    
    def clear(self):
        """Clear call history (test helper)."""
        self.analyze_calls.clear()
