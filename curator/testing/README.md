# Curator Service Testing

This directory contains the test suite for the Curator service.

## Quick Start

```bash
# From the curator directory
cd curator

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On macOS/Linux
# .venv\Scripts\activate   # On Windows

# Install dependencies
pip install -r requirements.txt
pip install -e ../neo4j-client

# Install test dependencies
pip install pytest pytest-cov pytest-mock

# Run all unit tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest testing/unit/test_clustering.py

# Run specific test class
pytest testing/unit/test_clustering.py::TestTopicClusterer

# Run specific test
pytest testing/unit/test_clustering.py::TestTopicClusterer::test_cluster_topics_basic

# Deactivate venv when done
deactivate
```

## Directory Structure

```
testing/
├── conftest.py              # Shared pytest fixtures
├── mocks/                   # Mock implementations
│   ├── __init__.py
│   ├── mock_neo4j.py        # Mock Neo4j client
│   ├── mock_redis.py        # Mock Redis client
│   └── mock_llm.py          # Mock Azure OpenAI
├── fixtures/                # Test data
│   ├── topics.json          # Sample topic data
│   ├── events.json          # Sample event data
│   └── llm_responses.json   # Canned LLM responses
└── unit/                    # Unit tests
    ├── test_api.py
    ├── test_clustering.py
    ├── test_event_reconciler.py
    ├── test_hierarchy_analyzer.py
    ├── test_threshold_monitor.py
    └── test_topic_organizer.py
```

## Test Categories

### Unit Tests (`testing/unit/`)

Unit tests run without external dependencies using mock clients:

| Test File | Component | Description |
|-----------|-----------|-------------|
| `test_clustering.py` | `TopicClusterer` | Tests topic clustering by embedding similarity |
| `test_hierarchy_analyzer.py` | `HierarchyAnalyzer` | Tests LLM-based hierarchy analysis |
| `test_topic_organizer.py` | `TopicOrganizer` | Tests the main orchestration logic |
| `test_event_reconciler.py` | `EventReconciler` | Tests event reconciliation |
| `test_threshold_monitor.py` | `TopicThresholdMonitor` | Tests threshold-based triggering |
| `test_api.py` | FastAPI endpoints | Tests health, status, and trigger endpoints |

## Running Tests with Coverage

```bash
# Run with coverage report
pytest --cov=. --cov-report=html

# Open coverage report
open htmlcov/index.html
```

## Mock Objects

### MockNeo4jClient

In-memory mock that simulates Neo4j operations:

```python
from testing.mocks import MockNeo4jClient

client = MockNeo4jClient()
client.connect()
client.add_node("Topic", "wifi", {"name": "Wi-Fi"})
nodes = client.get_all_nodes("Topic")
```

### MockRedisClient

In-memory mock that simulates Redis operations:

```python
from testing.mocks import MockRedisClient

redis = MockRedisClient()
redis.set("key", "value", ex=300)
value = redis.get("key")
```

### MockHierarchyAnalyzer

Mock that returns deterministic hierarchy relationships:

```python
from testing.mocks import MockHierarchyAnalyzer

analyzer = MockHierarchyAnalyzer()
analyzer.set_mock_relationships([
    {"broader_topic": "Wi-Fi", "narrower_topic": "Wi-Fi 6", "confidence": 0.95}
])
new_topics, relationships, stats = analyzer.analyze_cluster(topics)
```

## Test Fixtures

Fixtures are automatically loaded by pytest from `conftest.py`:

```python
def test_something(sample_topics, mock_neo4j_client):
    # sample_topics: List of topic dicts from fixtures/topics.json
    # mock_neo4j_client: Pre-configured MockNeo4jClient
    pass
```

### Available Fixtures

| Fixture | Description |
|---------|-------------|
| `mock_neo4j_client` | Mock Neo4j client |
| `mock_graph_repository` | Mock GraphRepository |
| `mock_redis_client` | Mock Redis client |
| `mock_hierarchy_analyzer` | Mock HierarchyAnalyzer |
| `sample_topics` | Sample topic data |
| `sample_events` | Sample event data |
| `llm_responses` | Canned LLM responses |
| `topic_clusterer` | Pre-configured TopicClusterer |
| `api_client` | FastAPI TestClient |

## Writing New Tests

### 1. Create a test file

```python
# testing/unit/test_my_component.py
import pytest

class TestMyComponent:
    def test_basic_functionality(self, mock_neo4j_client):
        """Test description."""
        # Arrange
        mock_neo4j_client.add_node("Topic", "test", {"name": "Test"})
        
        # Act
        result = my_function()
        
        # Assert
        assert result is not None
```

### 2. Use fixtures for dependencies

```python
def test_with_multiple_fixtures(
    mock_neo4j_client,
    mock_redis_client,
    sample_topics
):
    # All fixtures are available
    pass
```

### 3. Mock external dependencies

```python
from unittest.mock import patch, MagicMock

def test_with_patch(mock_graph_repository):
    with patch('tasks.topic_organizer.Neo4jClient') as mock:
        mock.return_value = MagicMock()
        # Test code
```

## CI/CD Integration

Tests run automatically on GitHub Actions:

- **On push** to `main`/`master` (if curator files changed)
- **On pull request** to `main`/`master` (if curator files changed)
- **Manual trigger** via workflow_dispatch

The workflow includes:
1. **Unit tests** - Core test suite
2. **Linting** - Code style checks with Ruff
3. **Type checking** - Static type analysis with mypy

## Troubleshooting

### Import errors

Make sure you're running from the `curator` directory:

```bash
cd curator
pytest
```

### Missing dependencies

Ensure your venv is activated and install test dependencies:

```bash
source .venv/bin/activate
pip install pytest pytest-cov pytest-mock
pip install -e ../neo4j-client
```

### Slow tests

Skip slow tests:

```bash
pytest -m "not slow"
```

### Debug a failing test

```bash
pytest testing/unit/test_clustering.py::test_name -v --tb=long
```
