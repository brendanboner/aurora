"""
Unit tests for EventReconciler.

Tests event reconciliation logic with mocked dependencies.

These tests cover:
- Basic functionality (has_pending_work, get_batches_pending_reconciliation)
- Event reconciliation (reconcile_datasource_events)
- Status updates (_mark_event_unconfirmed)
- Datetime handling with ISO string stored dates
- Error handling
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, call


class TestEventReconcilerBasics:
    """Tests for basic EventReconciler functionality."""
    
    def test_has_pending_work_no_batches(self, mock_neo4j_client):
        """Test has_pending_work when no batches need reconciliation."""
        from services.event_reconciler import EventReconciler
        
        mock_neo4j_client.execute_query = MagicMock(return_value=[{"pending_count": 0}])
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            logger_instance=MagicMock()
        )
        
        has_work, count = reconciler.has_pending_work()
        
        assert has_work is False
        assert count == 0
    
    def test_has_pending_work_with_batches(self, mock_neo4j_client):
        """Test has_pending_work when batches need reconciliation."""
        from services.event_reconciler import EventReconciler
        
        mock_neo4j_client.execute_query = MagicMock(return_value=[{"pending_count": 3}])
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            logger_instance=MagicMock()
        )
        
        has_work, count = reconciler.has_pending_work()
        
        assert has_work is True
        assert count == 3
    
    def test_get_batches_pending_reconciliation(self, mock_neo4j_client, sample_events):
        """Test retrieving batches that need reconciliation."""
        from services.event_reconciler import EventReconciler
        
        # Mock return value
        mock_batches = [
            {
                "batch_id": "batch-001",
                "datasource_id": "wfa-events",
                "scrape_started_at": "2025-01-15T09:00:00",
                "scrape_completed_at": "2025-01-15T10:30:00",
                "items_digested": 15,
                "events_count": 5
            },
            {
                "batch_id": "batch-002",
                "datasource_id": "ieee-meetings",
                "scrape_started_at": "2025-01-10T07:00:00",
                "scrape_completed_at": "2025-01-10T08:30:00",
                "items_digested": 8,
                "events_count": 3
            }
        ]
        mock_neo4j_client.execute_query = MagicMock(return_value=mock_batches)
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            logger_instance=MagicMock()
        )
        
        batches = reconciler.get_batches_pending_reconciliation()
        
        assert len(batches) == 2
        assert batches[0]["batch_id"] == "batch-001"
        assert batches[1]["datasource_id"] == "ieee-meetings"
    
    def test_similarity_threshold_configuration(self, mock_neo4j_client):
        """Test that similarity threshold is properly configured."""
        from services.event_reconciler import EventReconciler
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            logger_instance=MagicMock()
        )
        
        assert reconciler.SIMILARITY_THRESHOLD == 0.85
    
    def test_auto_cancel_days_configuration(self, mock_neo4j_client):
        """Test auto-cancel days configuration."""
        from services.event_reconciler import EventReconciler
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            logger_instance=MagicMock()
        )
        
        assert reconciler.AUTO_CANCEL_DAYS == 7
    
    def test_close_releases_resources_when_owning_connection(self, mock_neo4j_client):
        """Test that close() releases resources when owning the connection."""
        from services.event_reconciler import EventReconciler
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            logger_instance=MagicMock()
        )
        reconciler._owns_neo4j = True
        mock_client = MagicMock()
        mock_client.close = MagicMock()
        reconciler._neo4j_client = mock_client
        
        reconciler.close()
        
        mock_client.close.assert_called_once()
        assert reconciler._neo4j_client is None
    
    def test_close_does_not_release_external_connection(self, mock_neo4j_client):
        """Test that close() doesn't release externally provided connection."""
        from services.event_reconciler import EventReconciler
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            logger_instance=MagicMock()
        )
        # _owns_neo4j should be False when client is provided
        assert reconciler._owns_neo4j is False
        
        reconciler.close()
        
        # No error should occur, connection should remain


class TestReconcileDatasourceEvents:
    """Tests for the reconcile_datasource_events method."""
    
    def test_finds_disappeared_future_events(self, mock_neo4j_client, mock_graph_repository):
        """Test that future events not updated during scrape are found."""
        from services.event_reconciler import EventReconciler
        
        # Future date for testing
        future_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%S')
        scrape_started = "2025-12-09T10:00:00"
        
        # Events that weren't updated during the scrape (disappeared from source)
        disappeared_events = [
            {
                "url_hash": "event-disappeared-1",
                "name": "Disappeared Meeting 1",
                "status": "scheduled",
                "start_date": future_date,
                "embedding": [0.1] * 16,
                "last_updated": "2025-12-08T10:00:00"  # Before scrape started
            },
            {
                "url_hash": "event-disappeared-2",
                "name": "Disappeared Meeting 2",
                "status": "scheduled",
                "start_date": future_date,
                "embedding": None,
                "last_updated": "2025-12-08T09:00:00"
            }
        ]
        
        # Mock query returns: first for disappeared events, second for check_query
        mock_neo4j_client.execute_query = MagicMock(side_effect=[
            disappeared_events,  # Main query for disappeared events
            []  # Vector search (no similar events found)
        ])
        mock_neo4j_client.execute_write = MagicMock(return_value=[{"url_hash": "test"}])
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            graph_repository=mock_graph_repository,
            logger_instance=MagicMock()
        )
        
        stats = reconciler.reconcile_datasource_events("wfa-events", scrape_started)
        
        assert stats["events_checked"] == 2
        assert stats["marked_unconfirmed"] == 2
        assert stats["errors"] == 0
    
    def test_returns_empty_stats_when_no_disappeared_events(self, mock_neo4j_client, mock_graph_repository):
        """Test that empty stats returned when all events were updated."""
        from services.event_reconciler import EventReconciler
        
        # Events updated during scrape should NOT be returned by the query
        mock_neo4j_client.execute_query = MagicMock(side_effect=[
            [],  # No disappeared events (all were updated)
            [{"total_events": 4, "future_events": 4, "active_events": 4}]  # Check query
        ])
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            graph_repository=mock_graph_repository,
            logger_instance=MagicMock()
        )
        
        stats = reconciler.reconcile_datasource_events("wfa-events", "2025-12-09T10:00:00")
        
        assert stats["events_checked"] == 0
        assert stats["marked_unconfirmed"] == 0
    
    def test_skips_already_unconfirmed_events(self, mock_neo4j_client, mock_graph_repository):
        """Test that already unconfirmed events are checked but not marked again."""
        from services.event_reconciler import EventReconciler
        
        future_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%S')
        
        events = [
            {
                "url_hash": "event-already-unconfirmed",
                "name": "Already Unconfirmed Meeting",
                "status": "unconfirmed",  # Already unconfirmed
                "start_date": future_date,
                "embedding": None,
                "last_updated": "2025-12-08T10:00:00"
            }
        ]
        
        mock_neo4j_client.execute_query = MagicMock(return_value=events)
        mock_neo4j_client.execute_write = MagicMock()
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            graph_repository=mock_graph_repository,
            logger_instance=MagicMock()
        )
        
        stats = reconciler.reconcile_datasource_events("wfa-events", "2025-12-09T10:00:00")
        
        # Event is checked but not marked (already unconfirmed)
        assert stats["events_checked"] == 1
        assert stats["marked_unconfirmed"] == 0
    
    def test_handles_query_error_gracefully(self, mock_neo4j_client, mock_graph_repository):
        """Test that query errors are handled gracefully."""
        from services.event_reconciler import EventReconciler
        
        mock_neo4j_client.execute_query = MagicMock(
            side_effect=Exception("Database connection failed")
        )
        mock_logger = MagicMock()
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            graph_repository=mock_graph_repository,
            logger_instance=mock_logger
        )
        
        stats = reconciler.reconcile_datasource_events("wfa-events", "2025-12-09T10:00:00")
        
        assert stats["errors"] == 1
        mock_logger.error.assert_called()


class TestMarkEventUnconfirmed:
    """Tests for the _mark_event_unconfirmed method."""
    
    def test_marks_event_status_as_unconfirmed(self, mock_neo4j_client):
        """Test marking an event as unconfirmed updates status."""
        from services.event_reconciler import EventReconciler
        
        mock_neo4j_client.execute_write = MagicMock(return_value=[{"url_hash": "test123"}])
        mock_logger = MagicMock()
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            logger_instance=mock_logger
        )
        
        reconciler._mark_event_unconfirmed("test123", "Test Event")
        
        mock_neo4j_client.execute_write.assert_called_once()
        call_args = mock_neo4j_client.execute_write.call_args
        
        # Get the query from args or kwargs
        query = call_args[0][0] if call_args[0] else call_args.kwargs.get("query", "")
        
        # Get params from args[1] or kwargs
        if len(call_args[0]) > 1:
            params = call_args[0][1]
        else:
            params = call_args.kwargs
        
        assert "unconfirmed" in query
        assert "unconfirmed_at" in query
        # url_hash could be in params dict or as a kwarg
        assert params.get("url_hash") == "test123" or call_args.kwargs.get("url_hash") == "test123"
        mock_logger.info.assert_called()
    
    def test_handles_mark_error_gracefully(self, mock_neo4j_client):
        """Test that errors during marking are logged."""
        from services.event_reconciler import EventReconciler
        
        mock_neo4j_client.execute_write = MagicMock(side_effect=Exception("DB Error"))
        mock_logger = MagicMock()
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            logger_instance=mock_logger
        )
        
        # Should not raise
        reconciler._mark_event_unconfirmed("test123", "Test Event")
        
        mock_logger.error.assert_called()


class TestMarkBatchReconciled:
    """Tests for marking batches as reconciled."""
    
    def test_marks_batch_reconciled_with_timestamp(self, mock_neo4j_client):
        """Test marking a batch as reconciled sets reconciled_at."""
        from services.event_reconciler import EventReconciler
        
        mock_neo4j_client.execute_write = MagicMock(return_value=[{"batch_id": "batch-001"}])
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            logger_instance=MagicMock()
        )
        
        reconciler.mark_batch_reconciled("batch-001")
        
        mock_neo4j_client.execute_write.assert_called_once()
        call_args = mock_neo4j_client.execute_write.call_args
        
        # Get the query from args or kwargs
        query = call_args[0][0] if call_args[0] else call_args.kwargs.get("query", "")
        
        # Get params from args[1] or kwargs
        if len(call_args[0]) > 1:
            params = call_args[0][1]
        else:
            params = call_args.kwargs
        
        assert "reconciled_at" in query
        assert params.get("batch_id") == "batch-001" or call_args.kwargs.get("batch_id") == "batch-001"


class TestRunFullReconciliation:
    """Tests for the full run() method."""
    
    def test_run_returns_stats_with_no_pending_work(self, mock_neo4j_client):
        """Test run() when no work is pending."""
        from services.event_reconciler import EventReconciler
        
        # Return empty list for batches
        mock_neo4j_client.execute_query = MagicMock(return_value=[])
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            logger_instance=MagicMock()
        )
        
        result = reconciler.run()
        
        assert result is not None
        assert result.get("batches_processed", 0) == 0
    
    def test_run_processes_multiple_batches(self, mock_neo4j_client, mock_graph_repository):
        """Test that run() processes multiple pending batches."""
        from services.event_reconciler import EventReconciler
        
        batches = [
            {
                "batch_id": "batch-001",
                "datasource_id": "wfa-events",
                "scrape_started_at": "2025-12-09T10:00:00",
                "scrape_completed_at": "2025-12-09T11:00:00",
                "items_digested": 5,
                "events_count": 3
            },
            {
                "batch_id": "batch-002",
                "datasource_id": "ieee-meetings",
                "scrape_started_at": "2025-12-09T12:00:00",
                "scrape_completed_at": "2025-12-09T13:00:00",
                "items_digested": 3,
                "events_count": 2
            }
        ]
        
        mock_neo4j_client.execute_query = MagicMock(side_effect=[
            batches,  # get_batches_pending_reconciliation
            [],  # reconcile batch 1 (no disappeared events)
            [{"total_events": 3, "future_events": 0}],  # check query batch 1
            [],  # reconcile batch 2 (no disappeared events)
            [{"total_events": 2, "future_events": 0}],  # check query batch 2
        ])
        mock_neo4j_client.execute_write = MagicMock(return_value=[{"batch_id": "batch"}])
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            graph_repository=mock_graph_repository,
            logger_instance=MagicMock()
        )
        
        result = reconciler.run()
        
        assert result is not None
        assert result.get("batches_processed", 0) >= 1


class TestErrorHandling:
    """Tests for error handling in EventReconciler."""
    
    def test_handles_neo4j_connection_error_in_has_pending_work(self, mock_neo4j_client):
        """Test handling of Neo4j connection errors in has_pending_work."""
        from services.event_reconciler import EventReconciler
        
        mock_neo4j_client.execute_query = MagicMock(
            side_effect=Exception("Connection failed")
        )
        mock_logger = MagicMock()
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            logger_instance=mock_logger
        )
        
        has_work, count = reconciler.has_pending_work()
        
        assert has_work is False
        assert count == 0
        mock_logger.error.assert_called()
    
    def test_handles_batch_processing_error(self, mock_neo4j_client, mock_graph_repository):
        """Test handling of errors during batch processing."""
        from services.event_reconciler import EventReconciler
        
        batches = [{
            "batch_id": "batch-001",
            "datasource_id": "wfa-events",
            "scrape_started_at": "2025-12-09T10:00:00",
            "scrape_completed_at": "2025-12-09T11:00:00",
            "items_digested": 5,
            "events_count": 3
        }]
        
        mock_neo4j_client.execute_query = MagicMock(side_effect=[
            batches,  # get_batches_pending_reconciliation
            Exception("Query failed during reconciliation")
        ])
        mock_logger = MagicMock()
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            graph_repository=mock_graph_repository,
            logger_instance=mock_logger
        )
        
        result = reconciler.run()
        
        # Should handle error gracefully
        assert result is not None


class TestDatetimeHandling:
    """Tests for datetime string conversion in queries.
    
    Event start_date and end_date are stored as ISO strings (e.g., "2025-12-16T19:00:00")
    while last_updated uses native Neo4j datetime.
    
    The queries must use datetime() conversion when comparing start_date.
    """
    
    def test_reconcile_query_uses_datetime_conversion(self, mock_neo4j_client, mock_graph_repository):
        """Test that reconciliation query properly converts start_date strings."""
        from services.event_reconciler import EventReconciler
        
        mock_neo4j_client.execute_query = MagicMock(return_value=[])
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            graph_repository=mock_graph_repository,
            logger_instance=MagicMock()
        )
        
        reconciler.reconcile_datasource_events("wfa-events", "2025-12-09T10:00:00")
        
        # Check that the query uses datetime() conversion
        call_args = mock_neo4j_client.execute_query.call_args_list[0]
        query = call_args[0][0]
        
        # The query MUST use datetime(e.start_date) not just e.start_date
        # This is critical because start_date is stored as ISO string
        assert "datetime(e.start_date)" in query
        assert "datetime($scrape_started_at)" in query or "datetime()" in query
    
    def test_check_query_uses_datetime_conversion(self, mock_neo4j_client, mock_graph_repository):
        """Test that the diagnostic check query uses datetime conversion."""
        from services.event_reconciler import EventReconciler
        
        # First call returns empty events, second call is check query
        mock_neo4j_client.execute_query = MagicMock(side_effect=[
            [],  # No disappeared events
            [{"total_events": 5, "future_events": 3, "active_events": 5}]  # Check query
        ])
        
        reconciler = EventReconciler(
            neo4j_client=mock_neo4j_client,
            graph_repository=mock_graph_repository,
            logger_instance=MagicMock()
        )
        
        reconciler.reconcile_datasource_events("wfa-events", "2025-12-09T10:00:00")
        
        # Verify check query also uses datetime conversion
        if len(mock_neo4j_client.execute_query.call_args_list) > 1:
            check_call = mock_neo4j_client.execute_query.call_args_list[1]
            check_query = check_call[0][0]
            assert "datetime(e.start_date)" in check_query
