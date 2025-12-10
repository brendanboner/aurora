"""
Pytest configuration and shared fixtures for curator testing.

This file is automatically loaded by pytest and provides fixtures
available to all test files.
"""

import pytest
import json
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# =============================================================================
# Set test environment variables BEFORE any curator imports
# This must happen before settings.py is imported
# =============================================================================
os.environ.setdefault("AZURE_OPENAI_API_KEY", "test-api-key")
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com")
os.environ.setdefault("AZURE_OPENAI_DEPLOYMENT", "test-deployment")
os.environ.setdefault("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "testpassword")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")

# Add curator to path for imports
curator_path = Path(__file__).parent.parent
sys.path.insert(0, str(curator_path))


# =============================================================================
# Mock Client Fixtures
# =============================================================================

@pytest.fixture
def mock_neo4j_client():
    """Create a mock Neo4j client."""
    from testing.mocks import MockNeo4jClient
    
    client = MockNeo4jClient()
    client.connect()
    yield client
    client.close()


@pytest.fixture
def mock_graph_repository(mock_neo4j_client):
    """Create a mock GraphRepository."""
    from testing.mocks import MockGraphRepository
    
    return MockGraphRepository(mock_neo4j_client)


@pytest.fixture
def mock_redis_client():
    """Create a mock Redis client."""
    from testing.mocks import MockRedisClient
    
    client = MockRedisClient()
    yield client
    client.clear()


@pytest.fixture
def mock_hierarchy_analyzer():
    """Create a mock HierarchyAnalyzer."""
    from testing.mocks import MockHierarchyAnalyzer
    
    analyzer = MockHierarchyAnalyzer()
    yield analyzer
    analyzer.clear()


@pytest.fixture
def mock_azure_openai():
    """Create a mock Azure OpenAI client."""
    from testing.mocks import MockAzureOpenAI
    
    return MockAzureOpenAI()


# =============================================================================
# Test Data Fixtures
# =============================================================================

@pytest.fixture
def sample_topics() -> List[Dict[str, Any]]:
    """Load sample topic data from fixtures."""
    fixtures_path = Path(__file__).parent / "fixtures" / "topics.json"
    
    with open(fixtures_path) as f:
        data = json.load(f)
    
    return data["topics"]


@pytest.fixture
def sample_events() -> List[Dict[str, Any]]:
    """Load sample event data from fixtures."""
    fixtures_path = Path(__file__).parent / "fixtures" / "events.json"
    
    with open(fixtures_path) as f:
        data = json.load(f)
    
    return data["events"]


@pytest.fixture
def sample_ingestion_batches() -> List[Dict[str, Any]]:
    """Load sample ingestion batch data."""
    fixtures_path = Path(__file__).parent / "fixtures" / "events.json"
    
    with open(fixtures_path) as f:
        data = json.load(f)
    
    return data["ingestion_batches"]


@pytest.fixture
def llm_responses() -> Dict[str, Any]:
    """Load canned LLM responses."""
    fixtures_path = Path(__file__).parent / "fixtures" / "llm_responses.json"
    
    with open(fixtures_path) as f:
        return json.load(f)


@pytest.fixture
def expected_relationships() -> List[Dict[str, Any]]:
    """Load expected topic relationships."""
    fixtures_path = Path(__file__).parent / "fixtures" / "topics.json"
    
    with open(fixtures_path) as f:
        data = json.load(f)
    
    return data["expected_relationships"]


# =============================================================================
# Component Fixtures
# =============================================================================

@pytest.fixture
def topic_clusterer():
    """Create a TopicClusterer with test configuration."""
    from clustering import TopicClusterer
    
    return TopicClusterer(
        min_cluster_size=2,
        max_cluster_size=8,
        distance_threshold=0.5,
        overlap_neighbors=2
    )


@pytest.fixture
def api_client():
    """Create a FastAPI TestClient."""
    from fastapi.testclient import TestClient
    from api import app, set_start_time
    
    # Set start time for uptime calculation
    set_start_time(datetime.now())
    
    return TestClient(app)


# =============================================================================
# Utility Fixtures
# =============================================================================

@pytest.fixture
def temp_settings(monkeypatch):
    """
    Fixture to temporarily override settings.
    
    Usage:
        def test_something(temp_settings):
            temp_settings("neo4j_uri", "bolt://test:7687")
    """
    def _set_setting(name: str, value: Any):
        from settings import settings
        monkeypatch.setattr(settings, name, value)
    
    return _set_setting


@pytest.fixture
def populated_neo4j(mock_neo4j_client, sample_topics):
    """Create a mock Neo4j client pre-populated with sample topics."""
    for topic in sample_topics:
        mock_neo4j_client.add_node("Topic", topic["topic_id"], topic)
    
    return mock_neo4j_client


@pytest.fixture
def populated_redis(mock_redis_client):
    """Create a mock Redis client with typical state."""
    # Set last curation timestamp
    mock_redis_client.set(
        "curator:topic:last_curation_timestamp",
        datetime(2025, 1, 1, 0, 0, 0).isoformat()
    )
    
    return mock_redis_client


# =============================================================================
# Pytest Hooks
# =============================================================================

def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection based on markers."""
    # Skip integration tests unless explicitly requested
    if not config.getoption("--run-integration", default=False):
        skip_integration = pytest.mark.skip(reason="need --run-integration option to run")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run integration tests"
    )
