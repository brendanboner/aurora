"""
Tests for the ConfigManager class.

Tests configuration loading from Neo4j, cron schedule evaluation,
and datasource retrieval methods.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConfigManagerInit:
    """Tests for ConfigManager initialization and connection handling."""
    
    def test_init_connects_to_neo4j(self, patched_neo4j):
        """ConfigManager should connect to Neo4j on initialization."""
        from config_manager import ConfigManager
        
        cm = ConfigManager()
        
        patched_neo4j['client'].connect.assert_called_once()
        assert cm.neo4j_client is not None
        assert cm.graph_repository is not None
    
    def test_init_handles_connection_failure(self):
        """ConfigManager should handle Neo4j connection failures gracefully."""
        with patch('config_manager.Neo4jClient') as mock_client:
            mock_client.return_value.connect.side_effect = Exception("Connection refused")
            
            from config_manager import ConfigManager
            cm = ConfigManager()
            
            # Should not raise, but should have no connection
            assert cm.neo4j_client is None or cm.graph_repository is None
    
    def test_ensure_connection_reconnects_on_failure(self, patched_neo4j):
        """_ensure_connection should reconnect if connection is lost."""
        from config_manager import ConfigManager
        
        cm = ConfigManager()
        
        # Simulate connection loss
        patched_neo4j['client'].execute_query.side_effect = Exception("Connection lost")
        
        # First call fails, second should attempt reconnect
        result = cm._ensure_connection()
        
        # Should have attempted to reconnect
        assert patched_neo4j['client'].connect.call_count >= 1


class TestGetDatasourceConfig:
    """Tests for get_datasource_config method."""
    
    def test_returns_config_from_neo4j(self, patched_neo4j, sample_datasource_config):
        """Should return datasource config from Neo4j."""
        from config_manager import ConfigManager
        
        patched_neo4j['repository'].get_datasource_config.return_value = sample_datasource_config
        
        cm = ConfigManager()
        result = cm.get_datasource_config("test_datasource")
        
        assert result == sample_datasource_config
        patched_neo4j['repository'].get_datasource_config.assert_called_with("test_datasource")
    
    def test_returns_default_when_not_found(self, patched_neo4j):
        """Should return default config when datasource not found."""
        from config_manager import ConfigManager
        
        patched_neo4j['repository'].get_datasource_config.return_value = None
        
        cm = ConfigManager()
        result = cm.get_datasource_config("nonexistent")
        
        # Should return default config
        assert result["datasource_id"] == "nonexistent"
        assert result["scrape_schedule"] is None
        assert result["run_on_startup"] is False
    
    def test_returns_default_on_error(self, patched_neo4j):
        """Should return default config on Neo4j error."""
        from config_manager import ConfigManager
        
        patched_neo4j['repository'].get_datasource_config.side_effect = Exception("Query failed")
        
        cm = ConfigManager()
        result = cm.get_datasource_config("test_datasource")
        
        # Should return default config without raising
        assert "datasource_id" in result


class TestIsScheduleDue:
    """Tests for cron schedule evaluation."""
    
    def test_schedule_due_after_reference(self, patched_neo4j):
        """Schedule should be due if prev scheduled time > reference time."""
        from config_manager import ConfigManager
        from freezegun import freeze_time
        
        cm = ConfigManager()
        
        # Schedule runs daily at 3am
        schedule = "0 3 * * *"
        
        # Reference time is before today's 3am
        reference = datetime(2026, 1, 9, 1, 0, 0, tzinfo=timezone.utc)
        
        # Current time is Jan 9, 4am (after the 3am run)
        with freeze_time("2026-01-09 04:00:00", tz_offset=0):
            result = cm.is_schedule_due(schedule, reference)
            
        # The 3am run (prev scheduled) is after reference, so should be due
        assert result is True
    
    def test_schedule_not_due_when_already_ran(self, patched_neo4j):
        """Schedule should not be due if last scrape was after prev scheduled time."""
        from config_manager import ConfigManager
        from freezegun import freeze_time
        
        cm = ConfigManager()
        
        # Schedule runs daily at 3am
        schedule = "0 3 * * *"
        
        # We already scraped at 3:30am today
        reference = datetime(2026, 1, 9, 3, 30, 0, tzinfo=timezone.utc)
        
        # Current time is 4am same day
        with freeze_time("2026-01-09 04:00:00", tz_offset=0):
            result = cm.is_schedule_due(schedule, reference)
        
        # Already ran after the 3am scheduled time, so not due
        assert result is False
    
    def test_schedule_not_due_with_none_reference(self, patched_neo4j):
        """Schedule should not be due if reference_time is None."""
        from config_manager import ConfigManager
        
        cm = ConfigManager()
        
        result = cm.is_schedule_due("0 3 * * *", None)
        
        assert result is False
    
    def test_schedule_not_due_with_empty_schedule(self, patched_neo4j):
        """Should return False for empty/None schedule."""
        from config_manager import ConfigManager
        
        cm = ConfigManager()
        reference = datetime(2026, 1, 9, 1, 0, 0, tzinfo=timezone.utc)
        
        assert cm.is_schedule_due(None, reference) is False
        assert cm.is_schedule_due("", reference) is False
    
    def test_handles_naive_datetime_reference(self, patched_neo4j):
        """Should handle timezone-naive reference times."""
        from config_manager import ConfigManager
        
        cm = ConfigManager()
        
        schedule = "0 3 * * *"
        # Naive datetime (no timezone)
        reference = datetime(2026, 1, 8, 1, 0, 0)
        
        # Should not raise, should handle timezone conversion
        result = cm.is_schedule_due(schedule, reference)
        assert isinstance(result, bool)
    
    def test_handles_invalid_cron_expression(self, patched_neo4j):
        """Should return False for invalid cron expressions."""
        from config_manager import ConfigManager
        
        cm = ConfigManager()
        reference = datetime(2026, 1, 9, 1, 0, 0, tzinfo=timezone.utc)
        
        result = cm.is_schedule_due("invalid cron", reference)
        
        assert result is False


class TestGetStartupDatasources:
    """Tests for get_startup_datasources method."""
    
    def test_returns_startup_datasources(self, patched_neo4j, sample_startup_datasource):
        """Should return datasources with run_on_startup=True."""
        from config_manager import ConfigManager
        
        patched_neo4j['repository'].get_startup_datasources.return_value = [sample_startup_datasource]
        
        cm = ConfigManager()
        result = cm.get_startup_datasources()
        
        assert len(result) == 1
        assert result[0]["datasource_id"] == "startup_datasource"
        assert result[0]["run_on_startup"] is True
    
    def test_returns_empty_when_no_startup_datasources(self, patched_neo4j):
        """Should return empty list when no startup datasources exist."""
        from config_manager import ConfigManager
        
        patched_neo4j['repository'].get_startup_datasources.return_value = []
        
        cm = ConfigManager()
        result = cm.get_startup_datasources()
        
        assert result == []
    
    def test_returns_empty_on_error(self, patched_neo4j):
        """Should return empty list on error."""
        from config_manager import ConfigManager
        
        patched_neo4j['repository'].get_startup_datasources.side_effect = Exception("Error")
        
        cm = ConfigManager()
        result = cm.get_startup_datasources()
        
        assert result == []


class TestGetDueDatasources:
    """Tests for get_due_datasources method."""
    
    def test_filters_to_due_datasources(self, patched_neo4j):
        """Should only return datasources that are due based on cron schedule."""
        from config_manager import ConfigManager
        
        # Two datasources: one due, one not
        ds_due = {
            "datasource_id": "ds_due",
            "scrape_schedule": "0 3 * * *",
            "last_scraped_at": datetime(2026, 1, 8, 3, 0, 0, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc)
        }
        ds_not_due = {
            "datasource_id": "ds_not_due",
            "scrape_schedule": "0 3 * * *",
            "last_scraped_at": datetime(2026, 1, 9, 3, 30, 0, tzinfo=timezone.utc),  # Just ran
            "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc)
        }
        
        patched_neo4j['repository'].get_scheduled_datasources.return_value = [ds_due, ds_not_due]
        
        cm = ConfigManager()
        
        # Mock is_schedule_due to return expected values
        original_is_due = cm.is_schedule_due
        def mock_is_due(schedule, ref):
            if ref == ds_due["last_scraped_at"]:
                return True
            return False
        cm.is_schedule_due = mock_is_due
        
        result = cm.get_due_datasources()
        
        assert len(result) == 1
        assert result[0]["datasource_id"] == "ds_due"
    
    def test_uses_updated_at_when_never_scraped(self, patched_neo4j):
        """Should use updated_at as reference when last_scraped_at is None."""
        from config_manager import ConfigManager
        
        ds = {
            "datasource_id": "never_scraped",
            "scrape_schedule": "0 3 * * *",
            "last_scraped_at": None,
            "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "created_at": datetime(2025, 12, 1, tzinfo=timezone.utc)
        }
        
        patched_neo4j['repository'].get_scheduled_datasources.return_value = [ds]
        
        cm = ConfigManager()
        
        # Track what reference time was passed
        captured_ref = []
        original_is_due = cm.is_schedule_due
        def mock_is_due(schedule, ref):
            captured_ref.append(ref)
            return True
        cm.is_schedule_due = mock_is_due
        
        cm.get_due_datasources()
        
        # Should have used updated_at since last_scraped_at is None
        assert captured_ref[0] == ds["updated_at"]


class TestGetFullRefreshDatasources:
    """Tests for get_full_refresh_datasources method."""
    
    def test_returns_due_full_refresh_datasources(self, patched_neo4j, sample_full_refresh_datasource):
        """Should return datasources due for full refresh."""
        from config_manager import ConfigManager
        
        patched_neo4j['repository'].get_full_refresh_datasources.return_value = [sample_full_refresh_datasource]
        
        cm = ConfigManager()
        
        # Mock is_schedule_due to return True
        cm.is_schedule_due = MagicMock(return_value=True)
        
        result = cm.get_full_refresh_datasources()
        
        assert len(result) == 1
        assert result[0]["full_refresh_schedule"] is not None


class TestGroupByScraper:
    """Tests for datasource grouping by scraper_type."""
    
    def test_groups_by_scraper_type(self, patched_neo4j):
        """Should group datasources by their scraper_type."""
        from config_manager import ConfigManager
        
        datasources = [
            {"datasource_id": "wfa1", "scraper_type": "wfa"},
            {"datasource_id": "wfa2", "scraper_type": "wfa"},
            {"datasource_id": "causeway1", "scraper_type": "wfa_causeway"},
        ]
        
        cm = ConfigManager()
        result = cm._group_by_scraper_type(datasources)
        
        assert "wfa" in result
        assert "wfa_causeway" in result
        assert len(result["wfa"]) == 2
        assert len(result["wfa_causeway"]) == 1
    
    def test_excludes_datasources_without_scraper_type(self, patched_neo4j):
        """Should exclude datasources without scraper_type."""
        from config_manager import ConfigManager
        
        datasources = [
            {"datasource_id": "with_type", "scraper_type": "wfa"},
            {"datasource_id": "no_type", "scraper_type": None},
        ]
        
        cm = ConfigManager()
        result = cm._group_by_scraper_type(datasources)
        
        assert "wfa" in result
        assert len(result["wfa"]) == 1


class TestUpdateLastScraped:
    """Tests for update_last_scraped method."""
    
    def test_updates_last_scraped_timestamp(self, patched_neo4j):
        """Should update last_scraped_at in Neo4j."""
        from config_manager import ConfigManager
        
        cm = ConfigManager()
        cm.update_last_scraped("test_datasource")
        
        patched_neo4j['repository'].update_datasource_last_scraped.assert_called_with("test_datasource")
    
    def test_handles_update_error(self, patched_neo4j):
        """Should handle update errors gracefully."""
        from config_manager import ConfigManager
        
        patched_neo4j['repository'].update_datasource_last_scraped.side_effect = Exception("Update failed")
        
        cm = ConfigManager()
        
        # Should not raise
        cm.update_last_scraped("test_datasource")


class TestClose:
    """Tests for close method."""
    
    def test_closes_neo4j_connection(self, patched_neo4j):
        """Should close Neo4j connection."""
        from config_manager import ConfigManager
        
        cm = ConfigManager()
        cm.close()
        
        patched_neo4j['client'].close.assert_called_once()
        assert cm.neo4j_client is None
        assert cm.graph_repository is None
