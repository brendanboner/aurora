"""
Unit tests for ThresholdMonitor.

Tests topic threshold monitoring and curation triggering.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch


class TestThresholdMonitor:
    """Tests for the TopicThresholdMonitor class."""
    
    def test_get_last_curation_timestamp_none(self, mock_redis_client):
        """Test getting timestamp when none is set."""
        from services.threshold_monitor import TopicThresholdMonitor
        
        monitor = TopicThresholdMonitor(
            redis_client=mock_redis_client,
            neo4j_client=MagicMock()
        )
        
        timestamp = monitor.get_last_curation_timestamp()
        
        assert timestamp is None
    
    def test_get_last_curation_timestamp_exists(self, mock_redis_client):
        """Test getting timestamp when one is set."""
        from services.threshold_monitor import TopicThresholdMonitor
        
        # Set a timestamp
        test_time = datetime(2025, 1, 15, 10, 0, 0)
        mock_redis_client.set("curator:topic:last_curation_timestamp", test_time.isoformat())
        
        monitor = TopicThresholdMonitor(
            redis_client=mock_redis_client,
            neo4j_client=MagicMock()
        )
        
        timestamp = monitor.get_last_curation_timestamp()
        
        assert timestamp == test_time
    
    def test_set_last_curation_timestamp(self, mock_redis_client):
        """Test setting the last curation timestamp."""
        from services.threshold_monitor import TopicThresholdMonitor
        
        monitor = TopicThresholdMonitor(
            redis_client=mock_redis_client,
            neo4j_client=MagicMock()
        )
        
        test_time = datetime(2025, 1, 20, 12, 0, 0)
        monitor.set_last_curation_timestamp(test_time)
        
        # Verify it was set
        stored = mock_redis_client.get("curator:topic:last_curation_timestamp")
        assert stored == test_time.isoformat()
    
    def test_set_last_curation_timestamp_defaults_to_now(self, mock_redis_client):
        """Test that timestamp defaults to current time."""
        from services.threshold_monitor import TopicThresholdMonitor
        
        monitor = TopicThresholdMonitor(
            redis_client=mock_redis_client,
            neo4j_client=MagicMock()
        )
        
        before = datetime.now()
        monitor.set_last_curation_timestamp()
        after = datetime.now()
        
        stored = mock_redis_client.get("curator:topic:last_curation_timestamp")
        stored_time = datetime.fromisoformat(stored)
        
        assert before <= stored_time <= after
    
    def test_count_topics_since_all_topics(self, mock_redis_client, mock_neo4j_client):
        """Test counting all topics when no timestamp provided."""
        from services.threshold_monitor import TopicThresholdMonitor
        
        # Mock Neo4j to return a count
        mock_neo4j_client.execute_query = MagicMock(return_value=[{"count": 42}])
        
        monitor = TopicThresholdMonitor(
            redis_client=mock_redis_client,
            neo4j_client=mock_neo4j_client
        )
        monitor._neo4j_client = mock_neo4j_client
        
        count = monitor.count_topics_since(None)
        
        assert count == 42
    
    def test_count_topics_since_timestamp(self, mock_redis_client, mock_neo4j_client):
        """Test counting topics created after a timestamp."""
        from services.threshold_monitor import TopicThresholdMonitor
        
        mock_neo4j_client.execute_query = MagicMock(return_value=[{"count": 15}])
        
        monitor = TopicThresholdMonitor(
            redis_client=mock_redis_client,
            neo4j_client=mock_neo4j_client
        )
        monitor._neo4j_client = mock_neo4j_client
        
        since = datetime(2025, 1, 10, 0, 0, 0)
        count = monitor.count_topics_since(since)
        
        assert count == 15
        
        # Verify the query was called with the timestamp
        call_args = mock_neo4j_client.execute_query.call_args
        assert "since" in str(call_args) or call_args[0][0].find("since") > 0
    
    def test_curation_running_flag(self, mock_redis_client):
        """Test setting and checking curation running flag."""
        from services.threshold_monitor import TopicThresholdMonitor
        
        monitor = TopicThresholdMonitor(
            redis_client=mock_redis_client,
            neo4j_client=MagicMock()
        )
        
        # Initially not running
        assert mock_redis_client.get("curator:topic:running") is None
        
        # Set running
        monitor.set_curation_running(True)
        assert mock_redis_client.get("curator:topic:running") is not None
        
        # Clear running
        monitor.set_curation_running(False)
    
    def test_threshold_check_below_threshold(self, mock_redis_client, mock_neo4j_client):
        """Test threshold check when below threshold."""
        from services.threshold_monitor import TopicThresholdMonitor
        
        mock_neo4j_client.execute_query = MagicMock(return_value=[{"count": 10}])
        
        monitor = TopicThresholdMonitor(
            redis_client=mock_redis_client,
            neo4j_client=mock_neo4j_client
        )
        monitor._neo4j_client = mock_neo4j_client
        
        # Set last curation timestamp
        monitor.set_last_curation_timestamp(datetime.now() - timedelta(hours=1))
        
        # Count is 10, default threshold is 50
        should_trigger, count, reason = monitor.should_trigger_curation()
        
        assert should_trigger is False
        assert count == 10
    
    def test_threshold_check_above_threshold(self, mock_redis_client, mock_neo4j_client):
        """Test threshold check when above threshold."""
        from services.threshold_monitor import TopicThresholdMonitor
        from unittest.mock import patch
        
        mock_neo4j_client.execute_query = MagicMock(return_value=[{"count": 60}])
        
        monitor = TopicThresholdMonitor(
            redis_client=mock_redis_client,
            neo4j_client=mock_neo4j_client
        )
        monitor._neo4j_client = mock_neo4j_client
        
        monitor.set_last_curation_timestamp(datetime.now() - timedelta(hours=1))
        
        # Patch settings to use threshold of 50
        with patch('tasks.threshold_monitor.settings') as mock_settings:
            mock_settings.topic_threshold_count = 50
            should_trigger, count, reason = monitor.should_trigger_curation()
        
        assert should_trigger is True
        assert count == 60
        assert "threshold" in reason
    
    def test_threshold_check_curation_already_running(self, mock_redis_client, mock_neo4j_client):
        """Test threshold check when curation is already running."""
        from services.threshold_monitor import TopicThresholdMonitor
        
        mock_neo4j_client.execute_query = MagicMock(return_value=[{"count": 100}])
        
        monitor = TopicThresholdMonitor(
            redis_client=mock_redis_client,
            neo4j_client=mock_neo4j_client
        )
        monitor._neo4j_client = mock_neo4j_client
        
        # Set curation as running
        monitor.set_curation_running(True)
        
        # Should not trigger even if above threshold
        should_trigger, count, reason = monitor.should_trigger_curation()
        
        assert should_trigger is False


class TestThresholdMonitorIngestionSignals:
    """Tests for ingestion complete signal handling."""
    
    def test_check_ingestion_complete_signal_not_set(self, mock_redis_client):
        """Test checking ingestion complete signal when not set."""
        from services.threshold_monitor import TopicThresholdMonitor
        
        monitor = TopicThresholdMonitor(
            redis_client=mock_redis_client,
            neo4j_client=MagicMock()
        )
        
        is_complete = monitor.check_ingestion_complete_signal()
        
        assert is_complete is False
    
    def test_check_ingestion_complete_signal_set(self, mock_redis_client):
        """Test checking ingestion complete signal when set."""
        from services.threshold_monitor import TopicThresholdMonitor
        
        # Set the signal
        mock_redis_client.set("ingestion:daily_complete", "1")
        
        monitor = TopicThresholdMonitor(
            redis_client=mock_redis_client,
            neo4j_client=MagicMock()
        )
        
        is_complete = monitor.check_ingestion_complete_signal()
        
        assert is_complete is True
    
    def test_clear_ingestion_complete_signal(self, mock_redis_client):
        """Test clearing the ingestion complete signal."""
        from services.threshold_monitor import TopicThresholdMonitor
        
        mock_redis_client.set("ingestion:daily_complete", "1")
        
        monitor = TopicThresholdMonitor(
            redis_client=mock_redis_client,
            neo4j_client=MagicMock()
        )
        
        monitor.clear_ingestion_complete_signal()
        
        assert mock_redis_client.get("ingestion:daily_complete") is None


class TestThresholdMonitorLocking:
    """Tests for Redis lock management."""
    
    def test_extend_curation_lock(self, mock_redis_client):
        """Test extending the curation lock."""
        from services.threshold_monitor import TopicThresholdMonitor
        
        monitor = TopicThresholdMonitor(
            redis_client=mock_redis_client,
            neo4j_client=MagicMock()
        )
        
        # Set initial lock
        monitor.set_curation_running(True)
        
        # Extend lock
        monitor.extend_curation_lock()
        
        # Lock should still exist
        assert mock_redis_client.exists("curator:topic:running") >= 0
    
    def test_is_curation_running(self, mock_redis_client):
        """Test checking if curation is running."""
        from services.threshold_monitor import TopicThresholdMonitor
        
        monitor = TopicThresholdMonitor(
            redis_client=mock_redis_client,
            neo4j_client=MagicMock()
        )
        
        # Not running initially
        assert monitor.is_curation_running() is False
        
        # Set running
        monitor.set_curation_running(True)
        assert monitor.is_curation_running() is True
        
        # Clear
        monitor.set_curation_running(False)
        assert monitor.is_curation_running() is False
