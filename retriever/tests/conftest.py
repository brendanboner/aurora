"""
Shared pytest fixtures for retriever service tests.

Provides mock implementations for external dependencies:
- Neo4j client and GraphRepository
- RabbitMQ producer
- Redis client
- Sample datasource configurations
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, Any, List, Optional


# =============================================================================
# Sample Test Data
# =============================================================================

@pytest.fixture
def sample_datasource_config() -> Dict[str, Any]:
    """Sample datasource configuration for testing."""
    return {
        "datasource_id": "test_datasource",
        "name": "Test Datasource",
        "scraper_type": "wfa",
        "resource_url": "/test/documents",
        "scrape_schedule": "0 3 * * *",  # Daily at 3am
        "run_on_startup": False,
        "check_content_hash": True,
        "publish_weight": 1.0,
        "update_weight": 0.8,
        "event_weight": 0.9,
        "last_scraped_at": datetime(2026, 1, 8, 3, 0, 0, tzinfo=timezone.utc),
        "scraper_delay": 0.5,
        "max_resources": 100,
        "max_redirects": 10,
        "discovery_mode": "date_based",
        "consecutive_duplicates_limit": 5,
        "full_refresh_schedule": None,
        "folders": None,
        "created_at": datetime(2025, 12, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc)
    }


@pytest.fixture
def sample_startup_datasource() -> Dict[str, Any]:
    """Datasource configured to run on startup."""
    return {
        "datasource_id": "startup_datasource",
        "name": "Startup Datasource",
        "scraper_type": "wfa_causeway",
        "resource_url": "/wg/TestWG/document",
        "run_on_startup": True,
        "scrape_schedule": "0 3 * * *",
        "last_scraped_at": None,
        "scraper_delay": 1.0,
        "max_resources": 50,
        "discovery_mode": "incremental",
        "folders": ["Docs", "Reports"]
    }


@pytest.fixture
def sample_full_refresh_datasource() -> Dict[str, Any]:
    """Datasource with full refresh schedule."""
    return {
        "datasource_id": "full_refresh_ds",
        "name": "Full Refresh Datasource",
        "scraper_type": "wfa",
        "resource_url": "/test/refresh",
        "scrape_schedule": "0 3 * * *",
        "full_refresh_schedule": "0 3 * * 0",  # Weekly on Sunday
        "last_scraped_at": datetime(2026, 1, 1, 3, 0, 0, tzinfo=timezone.utc),
        "discovery_mode": "date_based"
    }


# =============================================================================
# Mock Clients
# =============================================================================

@pytest.fixture
def mock_neo4j_client():
    """Mock Neo4j client."""
    mock = MagicMock()
    mock.connect.return_value = None
    mock.close.return_value = None
    mock.execute_query.return_value = []
    return mock


@pytest.fixture
def mock_graph_repository(mock_neo4j_client):
    """Mock GraphRepository with common methods."""
    mock = MagicMock()
    
    # Default return values
    mock.get_datasource_config.return_value = None
    mock.get_startup_datasources.return_value = []
    mock.get_scheduled_datasources.return_value = []
    mock.get_all_datasources_with_scraper.return_value = []
    mock.get_full_refresh_datasources.return_value = []
    mock.create_node.return_value = None
    mock.create_relationship.return_value = None
    mock.update_batch_status.return_value = None
    mock.update_datasource_last_scraped.return_value = None
    mock.increment_batch_scraped.return_value = None
    mock.get_node.return_value = None
    
    return mock


@pytest.fixture
def mock_rabbitmq_producer():
    """Mock RabbitMQ producer."""
    mock = MagicMock()
    mock.publish.return_value = None
    mock.close.return_value = None
    return mock


@pytest.fixture
def mock_redis_client():
    """Mock Redis client."""
    mock = MagicMock()
    mock.ping.return_value = True
    mock.set.return_value = True
    mock.get.return_value = None
    mock.delete.return_value = 1
    return mock


# =============================================================================
# Patched Environments
# =============================================================================

@pytest.fixture
def mock_settings():
    """Mock settings object."""
    mock = MagicMock()
    mock.neo4j_uri = "bolt://localhost:7687"
    mock.neo4j_user = "neo4j"
    mock.neo4j_password = "test"
    mock.neo4j_database = "neo4j"
    mock.rabbitmq_host = "localhost"
    mock.rabbitmq_port = 5672
    mock.rabbitmq_user = "user"
    mock.rabbitmq_password = "password"
    mock.rabbitmq_queue = "test_queue"
    mock.redis_host = "localhost"
    mock.redis_port = 6379
    mock.log_level = "INFO"
    mock.scheduler_poll_interval = 60
    mock.wfa_causeway_username = "test_user"
    mock.wfa_causeway_password = "test_pass"
    return mock


@pytest.fixture
def patched_neo4j(mock_neo4j_client, mock_graph_repository):
    """Patch Neo4j client and GraphRepository for isolated testing."""
    with patch('config_manager.Neo4jClient') as mock_client_class, \
         patch('config_manager.GraphRepository') as mock_repo_class:
        mock_client_class.return_value = mock_neo4j_client
        mock_repo_class.return_value = mock_graph_repository
        yield {
            'client': mock_neo4j_client,
            'repository': mock_graph_repository,
            'client_class': mock_client_class,
            'repository_class': mock_repo_class
        }


@pytest.fixture
def patched_base_scraper_deps(mock_neo4j_client, mock_graph_repository, 
                               mock_rabbitmq_producer, mock_redis_client, mock_settings):
    """Patch all BaseScraper dependencies for isolated testing."""
    with patch('scrapers.base.Neo4jClient') as mock_client_class, \
         patch('scrapers.base.GraphRepository') as mock_repo_class, \
         patch('scrapers.base.RabbitMQProducer') as mock_producer_class, \
         patch('scrapers.base.redis.Redis') as mock_redis_class, \
         patch('scrapers.base.settings', mock_settings), \
         patch('scrapers.base.ConfigManager') as mock_config_manager_class:
        
        mock_client_class.return_value = mock_neo4j_client
        mock_repo_class.return_value = mock_graph_repository
        mock_producer_class.return_value = mock_rabbitmq_producer
        mock_redis_class.return_value = mock_redis_client
        mock_config_manager_class.return_value = MagicMock()
        
        yield {
            'neo4j_client': mock_neo4j_client,
            'graph_repository': mock_graph_repository,
            'rabbitmq_producer': mock_rabbitmq_producer,
            'redis_client': mock_redis_client,
            'settings': mock_settings
        }


# =============================================================================
# Utility Functions for Tests
# =============================================================================

@pytest.fixture
def make_resource():
    """Factory fixture for creating Resource objects."""
    def _make_resource(
        title: str = "Test Document",
        url: str = "https://example.com/doc.pdf",
        category: str = "test",
        content: Optional[str] = None,
        datasource_id: str = "test_ds"
    ):
        from scrapers.base import Resource
        return Resource(
            title=title,
            url=url,
            category=category,
            content=content,
            datasource_id=datasource_id
        )
    return _make_resource


@pytest.fixture
def make_event():
    """Factory fixture for creating Event objects."""
    def _make_event(
        name: str = "Test Meeting",
        event_type: str = "meeting",
        start_date: str = "2026-01-15T10:00:00",
        end_date: Optional[str] = None,
        location: str = "Virtual",
        url: Optional[str] = "https://example.com/event/123",
        status: str = "scheduled",
        datasource_id: str = "test_ds"
    ):
        from scrapers.base import Event
        return Event(
            name=name,
            event_type=event_type,
            start_date=start_date,
            end_date=end_date,
            location=location,
            url=url,
            status=status,
            datasource_id=datasource_id
        )
    return _make_event
