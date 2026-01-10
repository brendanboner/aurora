"""
Tests for the BaseScraper class and related dataclasses.

Tests Resource/Event dataclasses, batch tracking, collect mode,
URL/content hashing, event filtering, and publish methods.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
import hashlib
import json

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestResourceDataclass:
    """Tests for the Resource dataclass."""
    
    def test_resource_creation(self, make_resource):
        """Resource should be created with required fields."""
        resource = make_resource(
            title="Test Doc",
            url="https://example.com/doc.pdf",
            category="docs"
        )
        
        assert resource.title == "Test Doc"
        assert resource.url == "https://example.com/doc.pdf"
        assert resource.category == "docs"
        assert resource.scraped_at is not None  # Auto-set
    
    def test_resource_to_message(self, make_resource):
        """Resource.to_message() should return correct format."""
        resource = make_resource(
            title="Test",
            url="https://example.com/test",
            category="test",
            content="Test content",
            datasource_id="test_ds"
        )
        resource.batch_id = "batch-123"
        
        message = resource.to_message()
        
        assert message["message_type"] == "resource"
        assert message["resource_data"]["title"] == "Test"
        assert message["resource_data"]["url"] == "https://example.com/test"
        assert message["resource_data"]["content"] == "Test content"
        assert message["datasource_id"] == "test_ds"
        assert message["batch_id"] == "batch-123"


class TestEventDataclass:
    """Tests for the Event dataclass."""
    
    def test_event_creation(self, make_event):
        """Event should be created with required fields."""
        event = make_event(
            name="Test Meeting",
            event_type="meeting",
            start_date="2026-01-15T10:00:00"
        )
        
        assert event.name == "Test Meeting"
        assert event.event_type == "meeting"
        assert event.start_date == "2026-01-15T10:00:00"
        assert event.status == "scheduled"
        assert event.scraped_at is not None
    
    def test_event_to_message(self, make_event):
        """Event.to_message() should return correct format."""
        event = make_event(
            name="Conference",
            event_type="conference",
            start_date="2026-02-01",
            end_date="2026-02-03",
            location="San Francisco",
            url="https://example.com/event/1"
        )
        event.batch_id = "batch-456"
        event.datasource_id = "events_ds"
        
        message = event.to_message()
        
        assert message["message_type"] == "event"
        assert message["event_data"]["name"] == "Conference"
        assert message["event_data"]["event_type"] == "conference"
        assert message["event_data"]["start_date"] == "2026-02-01"
        assert message["event_data"]["end_date"] == "2026-02-03"
        assert message["event_data"]["location"] == "San Francisco"
        assert message["batch_id"] == "batch-456"


class TestBaseScraperInit:
    """Tests for BaseScraper initialization."""
    
    def test_init_creates_rabbitmq_producer(self, patched_base_scraper_deps):
        """BaseScraper should initialize RabbitMQ producer."""
        from scrapers.base import BaseScraper
        
        # Create a concrete implementation for testing
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        
        assert scraper.rabbitmq_producer is not None
    
    def test_init_creates_neo4j_client(self, patched_base_scraper_deps):
        """BaseScraper should initialize Neo4j client."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        
        assert scraper.neo4j_client is not None
        assert scraper.graph_repository is not None


class TestBatchTracking:
    """Tests for batch tracking functionality."""
    
    def test_start_batch_creates_batch_id(self, patched_base_scraper_deps):
        """start_batch should generate a unique batch_id."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        batch_id = scraper.start_batch("test_datasource")
        
        assert batch_id is not None
        assert len(batch_id) > 0
        assert scraper._current_batch_id == batch_id
        assert scraper._current_datasource_id == "test_datasource"
    
    def test_start_batch_creates_neo4j_node(self, patched_base_scraper_deps):
        """start_batch should create IngestionBatch node in Neo4j."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        scraper.start_batch("test_datasource")
        
        patched_base_scraper_deps['graph_repository'].create_node.assert_called()
        patched_base_scraper_deps['graph_repository'].create_relationship.assert_called()
    
    def test_end_batch_updates_status(self, patched_base_scraper_deps):
        """end_batch should update batch status in Neo4j."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        scraper.start_batch("test_datasource")
        scraper.end_batch(5)
        
        patched_base_scraper_deps['graph_repository'].update_batch_status.assert_called()
    
    def test_end_batch_clears_state(self, patched_base_scraper_deps):
        """end_batch should clear batch tracking state."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        scraper.start_batch("test_datasource")
        scraper.end_batch(5)
        
        assert scraper._current_batch_id is None
        assert scraper._current_datasource_id is None
        assert scraper._batch_items_count == 0
    
    def test_increment_batch_count(self, patched_base_scraper_deps):
        """increment_batch_count should track items and update Neo4j."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        scraper.start_batch("test_datasource")
        
        scraper.increment_batch_count(1)
        assert scraper._batch_items_count == 1
        
        scraper.increment_batch_count(3)
        assert scraper._batch_items_count == 4
        
        patched_base_scraper_deps['graph_repository'].increment_batch_scraped.assert_called()
    
    def test_end_batch_without_active_batch_logs_warning(self, patched_base_scraper_deps):
        """end_batch without active batch should log warning."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        
        # Should not raise
        scraper.end_batch(0)


class TestCollectMode:
    """Tests for collect mode functionality."""
    
    def test_enable_collect_mode(self, patched_base_scraper_deps):
        """enable_collect_mode should enable collection."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        scraper.enable_collect_mode()
        
        assert scraper._collect_mode is True
        assert scraper._collected_messages == []
    
    def test_disable_collect_mode(self, patched_base_scraper_deps):
        """disable_collect_mode should disable collection."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        scraper.enable_collect_mode()
        scraper.disable_collect_mode()
        
        assert scraper._collect_mode is False
    
    def test_publish_resource_collects_in_collect_mode(self, patched_base_scraper_deps, make_resource):
        """publish_resource should collect messages when in collect mode."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        scraper.enable_collect_mode()
        scraper.start_batch("test_ds")
        
        resource = make_resource()
        scraper.publish_resource(resource)
        
        # Should NOT publish to RabbitMQ
        patched_base_scraper_deps['rabbitmq_producer'].publish.assert_not_called()
        
        # Should collect message
        messages = scraper.get_collected_messages()
        assert len(messages) == 1
        assert messages[0]["message_type"] == "resource"
    
    def test_publish_event_collects_in_collect_mode(self, patched_base_scraper_deps, make_event):
        """publish_event should collect messages when in collect mode."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        scraper.enable_collect_mode()
        scraper.start_batch("test_ds")
        
        event = make_event()
        scraper.publish_event(event)
        
        # Should NOT publish to RabbitMQ
        patched_base_scraper_deps['rabbitmq_producer'].publish.assert_not_called()
        
        # Should collect message
        messages = scraper.get_collected_messages()
        assert len(messages) == 1
        assert messages[0]["message_type"] == "event"
    
    def test_clear_collected_messages(self, patched_base_scraper_deps, make_resource):
        """clear_collected_messages should empty the collection."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        scraper.enable_collect_mode()
        scraper.start_batch("test_ds")
        scraper.publish_resource(make_resource())
        
        assert len(scraper.get_collected_messages()) == 1
        
        scraper.clear_collected_messages()
        
        assert len(scraper.get_collected_messages()) == 0


class TestUrlHashing:
    """Tests for URL hashing and deduplication."""
    
    def test_compute_url_hash(self, patched_base_scraper_deps):
        """_compute_url_hash should return SHA256 hash."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        
        url = "https://example.com/doc.pdf"
        expected_hash = hashlib.sha256(url.encode('utf-8')).hexdigest()
        
        result = scraper._compute_url_hash(url)
        
        assert result == expected_hash
    
    def test_url_exists_in_db_returns_true_when_exists(self, patched_base_scraper_deps):
        """url_exists_in_db should return True when URL exists."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        # Configure mock to return a result
        patched_base_scraper_deps['neo4j_client'].execute_query.return_value = [{"url_hash": "abc123"}]
        
        scraper = TestScraper()
        result = scraper.url_exists_in_db("https://example.com/existing")
        
        assert result is True
    
    def test_url_exists_in_db_returns_false_when_not_exists(self, patched_base_scraper_deps):
        """url_exists_in_db should return False when URL doesn't exist."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        # Configure mock to return empty
        patched_base_scraper_deps['neo4j_client'].execute_query.return_value = []
        
        scraper = TestScraper()
        result = scraper.url_exists_in_db("https://example.com/new")
        
        assert result is False
    
    def test_batch_check_urls_exist(self, patched_base_scraper_deps):
        """batch_check_urls_exist should check multiple URLs in one query."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        urls = ["https://example.com/a", "https://example.com/b", "https://example.com/c"]
        
        # Only first URL exists
        first_hash = hashlib.sha256(urls[0].encode('utf-8')).hexdigest()
        patched_base_scraper_deps['neo4j_client'].execute_query.return_value = [
            {"hash": first_hash, "exists": True},
            {"hash": hashlib.sha256(urls[1].encode('utf-8')).hexdigest(), "exists": False},
            {"hash": hashlib.sha256(urls[2].encode('utf-8')).hexdigest(), "exists": False},
        ]
        
        scraper = TestScraper()
        result = scraper.batch_check_urls_exist(urls)
        
        assert result[urls[0]] is True
        assert result[urls[1]] is False
        assert result[urls[2]] is False


class TestContentHashing:
    """Tests for content hashing and change detection."""
    
    def test_compute_content_hash(self, patched_base_scraper_deps):
        """_compute_content_hash should return SHA256 hash."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        
        content = "This is test content"
        expected_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        
        result = scraper._compute_content_hash(content)
        
        assert result == expected_hash
    
    def test_has_content_changed_returns_true_for_new(self, patched_base_scraper_deps):
        """has_content_changed should return True for new content."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        # No stored hash found
        patched_base_scraper_deps['neo4j_client'].execute_query.return_value = []
        
        scraper = TestScraper()
        result = scraper.has_content_changed("https://example.com/doc", "New content")
        
        assert result is True
    
    def test_has_content_changed_returns_false_for_same(self, patched_base_scraper_deps):
        """has_content_changed should return False when content is same."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        content = "Same content"
        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        
        patched_base_scraper_deps['neo4j_client'].execute_query.return_value = [
            {"content_hash": content_hash}
        ]
        
        scraper = TestScraper()
        result = scraper.has_content_changed("https://example.com/doc", content)
        
        assert result is False
    
    def test_has_content_changed_returns_true_for_different(self, patched_base_scraper_deps):
        """has_content_changed should return True when content differs."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        old_hash = hashlib.sha256(b"Old content").hexdigest()
        
        patched_base_scraper_deps['neo4j_client'].execute_query.return_value = [
            {"content_hash": old_hash}
        ]
        
        scraper = TestScraper()
        result = scraper.has_content_changed("https://example.com/doc", "New content")
        
        assert result is True


class TestResourceUpdatedCheck:
    """Tests for is_resource_updated method."""
    
    def test_is_resource_updated_new_resource(self, patched_base_scraper_deps):
        """is_resource_updated should return True for new resource."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        # No existing resource
        patched_base_scraper_deps['neo4j_client'].execute_query.return_value = []
        
        scraper = TestScraper()
        result = scraper.is_resource_updated("https://example.com/new", "2026-01-10")
        
        assert result is True
    
    def test_is_resource_updated_newer_revision(self, patched_base_scraper_deps):
        """is_resource_updated should return True when revision is newer."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        # Existing resource with older date
        patched_base_scraper_deps['neo4j_client'].execute_query.return_value = [
            {"publish_date": "2026-01-05"}
        ]
        
        scraper = TestScraper()
        result = scraper.is_resource_updated("https://example.com/doc", "2026-01-10")
        
        assert result is True
    
    def test_is_resource_updated_same_revision(self, patched_base_scraper_deps):
        """is_resource_updated should return False when revision is same."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        patched_base_scraper_deps['neo4j_client'].execute_query.return_value = [
            {"publish_date": "2026-01-10"}
        ]
        
        scraper = TestScraper()
        result = scraper.is_resource_updated("https://example.com/doc", "2026-01-10")
        
        assert result is False


class TestEventFiltering:
    """Tests for event filtering logic."""
    
    def test_filter_events_publishes_future_events(self, patched_base_scraper_deps, make_event):
        """Future events should always be published."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        
        # Event in the future
        future_event = make_event(
            name="Future Meeting",
            start_date="2027-06-15T10:00:00"
        )
        
        result = scraper.filter_events([future_event])
        
        assert len(result) == 1
        assert result[0].name == "Future Meeting"
    
    def test_filter_events_marks_new_past_events_completed(self, patched_base_scraper_deps, make_event):
        """New past events should be published with status='completed'."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        # Event doesn't exist in DB
        patched_base_scraper_deps['neo4j_client'].execute_query.return_value = [
            {"hash": "somehash", "url_hash": None, "status": None, "start_date": None}
        ]
        
        scraper = TestScraper()
        
        # Event in the past
        past_event = make_event(
            name="Past Meeting",
            start_date="2020-01-15T10:00:00",
            url="https://example.com/event/past"
        )
        
        result = scraper.filter_events([past_event])
        
        assert len(result) == 1
        assert result[0].status == "completed"
    
    def test_filter_events_skips_completed_past_events(self, patched_base_scraper_deps, make_event):
        """Past events already marked completed should be skipped."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        url = "https://example.com/event/completed"
        url_hash = hashlib.sha256(url.encode('utf-8')).hexdigest()
        
        # Event exists and is already completed
        patched_base_scraper_deps['neo4j_client'].execute_query.return_value = [
            {"hash": url_hash, "url_hash": url_hash, "status": "completed", "start_date": "2020-01-15"}
        ]
        
        scraper = TestScraper()
        
        past_event = make_event(
            name="Completed Meeting",
            start_date="2020-01-15T10:00:00",
            url=url
        )
        
        result = scraper.filter_events([past_event])
        
        # Should be filtered out
        assert len(result) == 0


class TestPublishMethods:
    """Tests for publish_resource and publish_event methods."""
    
    def test_publish_resource_sends_to_rabbitmq(self, patched_base_scraper_deps, make_resource):
        """publish_resource should send message to RabbitMQ."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        scraper.start_batch("test_ds")
        
        resource = make_resource()
        scraper.publish_resource(resource)
        
        patched_base_scraper_deps['rabbitmq_producer'].publish.assert_called_once()
        
        call_args = patched_base_scraper_deps['rabbitmq_producer'].publish.call_args
        message = call_args[0][0]
        assert message["message_type"] == "resource"
    
    def test_publish_event_sends_to_rabbitmq(self, patched_base_scraper_deps, make_event):
        """publish_event should send message to RabbitMQ."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        scraper.start_batch("test_ds")
        
        event = make_event()
        scraper.publish_event(event)
        
        patched_base_scraper_deps['rabbitmq_producer'].publish.assert_called_once()
        
        call_args = patched_base_scraper_deps['rabbitmq_producer'].publish.call_args
        message = call_args[0][0]
        assert message["message_type"] == "event"
    
    def test_publish_resource_sets_batch_id(self, patched_base_scraper_deps, make_resource):
        """publish_resource should set batch_id on resource."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        batch_id = scraper.start_batch("test_ds")
        
        resource = make_resource()
        scraper.publish_resource(resource)
        
        call_args = patched_base_scraper_deps['rabbitmq_producer'].publish.call_args
        message = call_args[0][0]
        assert message["batch_id"] == batch_id
    
    def test_publish_resource_increments_count(self, patched_base_scraper_deps, make_resource):
        """publish_resource should increment batch count."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        scraper.start_batch("test_ds")
        
        assert scraper._batch_items_count == 0
        
        scraper.publish_resource(make_resource())
        assert scraper._batch_items_count == 1
        
        scraper.publish_resource(make_resource())
        assert scraper._batch_items_count == 2


class TestFilterNewUrls:
    """Tests for filter_new_urls method."""
    
    def test_filter_new_urls_removes_duplicates(self, patched_base_scraper_deps, make_resource):
        """filter_new_urls should remove resources with existing URLs."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        # First resource exists, second is new
        resources = [
            make_resource(url="https://example.com/existing"),
            make_resource(url="https://example.com/new")
        ]
        
        existing_hash = hashlib.sha256(b"https://example.com/existing").hexdigest()
        new_hash = hashlib.sha256(b"https://example.com/new").hexdigest()
        
        patched_base_scraper_deps['neo4j_client'].execute_query.return_value = [
            {"hash": existing_hash, "exists": True},
            {"hash": new_hash, "exists": False}
        ]
        
        scraper = TestScraper()
        result = scraper.filter_new_urls(resources)
        
        assert len(result) == 1
        assert result[0].url == "https://example.com/new"


class TestHeartbeatAndMonitoring:
    """Tests for Redis heartbeat and monitoring methods."""
    
    def test_update_heartbeat(self, patched_base_scraper_deps):
        """update_heartbeat should set Redis key."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        scraper.update_heartbeat()
        
        patched_base_scraper_deps['redis_client'].set.assert_called()
        call_args = patched_base_scraper_deps['redis_client'].set.call_args
        assert "retriever:heartbeat" in str(call_args)
    
    def test_clear_heartbeat(self, patched_base_scraper_deps):
        """clear_heartbeat should delete Redis key."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        scraper.clear_heartbeat()
        
        patched_base_scraper_deps['redis_client'].delete.assert_called_with("retriever:heartbeat")
    
    def test_update_current_processing(self, patched_base_scraper_deps, make_resource):
        """update_current_processing should set processing status in Redis."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        resource = make_resource()
        
        scraper.update_current_processing(resource, "downloading")
        
        patched_base_scraper_deps['redis_client'].set.assert_called()
        call_args = patched_base_scraper_deps['redis_client'].set.call_args
        assert "retriever:current" in str(call_args)
    
    def test_clear_current_processing(self, patched_base_scraper_deps):
        """clear_current_processing should delete processing status from Redis."""
        from scrapers.base import BaseScraper
        
        class TestScraper(BaseScraper):
            async def run_scraper(self):
                pass
            async def scrape_resource(self, resource):
                return resource
        
        scraper = TestScraper()
        scraper.clear_current_processing()
        
        patched_base_scraper_deps['redis_client'].delete.assert_called_with("retriever:current")
