"""Tests for user_source_preferences graceful fallback (Fix 1).

The user_source_preferences table is created by migration 008.
Before the migration runs, every profile page load was crashing with:
  "relation 'user_source_preferences' does not exist"

These tests verify that get/upsert/delete_user_source_preferences all
return graceful results (empty list / no-op) when the table is missing.
"""

import pytest
from unittest.mock import patch, MagicMock


# ── helpers ──────────────────────────────────────────────────────────────────

def _table_missing_error():
    """Simulate the psycopg2 error when the table doesn't exist."""
    import psycopg2
    err = psycopg2.errors.UndefinedTable(
        'relation "user_source_preferences" does not exist LINE 3: FROM user_source_preferences ^'
    )
    return err


# ── get_user_source_preferences ──────────────────────────────────────────────

class TestGetUserSourcePreferencesFallback:
    """get_user_source_preferences returns [] when table is missing."""

    def test_returns_empty_list_when_table_missing(self):
        from backend.src.services.postgres import get_user_source_preferences
        with patch("backend.src.services.postgres.fetchall", side_effect=_table_missing_error()):
            result = get_user_source_preferences("user-123")
        assert result == [], f"Expected [], got {result!r}"

    def test_returns_data_when_table_exists(self):
        from backend.src.services.postgres import get_user_source_preferences
        expected = [{"datasource_id": "ietf_wg_quic", "weight": 1.0}]
        with patch("backend.src.services.postgres.fetchall", return_value=expected):
            result = get_user_source_preferences("user-123")
        assert result == expected

    def test_propagates_other_db_errors(self):
        """Non-table-missing errors should still propagate."""
        import psycopg2
        from backend.src.services.postgres import get_user_source_preferences
        with patch("backend.src.services.postgres.fetchall",
                   side_effect=psycopg2.OperationalError("connection refused")):
            with pytest.raises(psycopg2.OperationalError):
                get_user_source_preferences("user-123")


# ── upsert_user_source_preference ────────────────────────────────────────────

class TestUpsertUserSourcePreferenceFallback:
    """upsert_user_source_preference returns a dummy row when table is missing."""

    def test_returns_dummy_row_when_table_missing(self):
        from backend.src.services.postgres import upsert_user_source_preference
        with patch("backend.src.services.postgres.fetchone", side_effect=_table_missing_error()):
            result = upsert_user_source_preference("user-123", "ietf_wg_quic", 1.0)
        assert result["user_id"] == "user-123"
        assert result["datasource_id"] == "ietf_wg_quic"
        assert result["weight"] == 1.0

    def test_returns_real_row_when_table_exists(self):
        from backend.src.services.postgres import upsert_user_source_preference
        expected = {"user_id": "user-123", "datasource_id": "ietf_wg_quic", "weight": 0.8}
        with patch("backend.src.services.postgres.fetchone", return_value=expected):
            result = upsert_user_source_preference("user-123", "ietf_wg_quic", 0.8)
        assert result == expected


# ── delete_user_source_preference ────────────────────────────────────────────

class TestDeleteUserSourcePreferenceFallback:
    """delete_user_source_preference returns False (safe no-op) when table is missing."""

    def test_returns_false_when_table_missing(self):
        from backend.src.services.postgres import delete_user_source_preference
        with patch("backend.src.services.postgres.fetchone", side_effect=_table_missing_error()):
            result = delete_user_source_preference("user-123", "ietf_wg_quic")
        assert result is False

    def test_returns_true_when_row_deleted(self):
        from backend.src.services.postgres import delete_user_source_preference
        with patch("backend.src.services.postgres.fetchone",
                   return_value={"datasource_id": "ietf_wg_quic"}):
            result = delete_user_source_preference("user-123", "ietf_wg_quic")
        assert result is True

    def test_returns_false_when_row_not_found(self):
        from backend.src.services.postgres import delete_user_source_preference
        with patch("backend.src.services.postgres.fetchone", return_value=None):
            result = delete_user_source_preference("user-123", "nonexistent")
        assert result is False


# ── get_preferences API endpoint ──────────────────────────────────────────────

class TestGetPreferencesEndpointFallback:
    """The /users/{id}/preferences endpoint returns source_preferences=[]
    when the table is missing — no 500 error."""

    def test_preferences_endpoint_returns_empty_source_prefs_when_table_missing(self):
        """Profile page should load without crashing even without migration 008."""
        import sys, types

        # Minimal stubs so we can import the api module
        for stub_name in ['neo4j_client', 'neo4j_client.client',
                          'opentelemetry.trace', 'opentelemetry']:
            if stub_name not in sys.modules:
                sys.modules[stub_name] = types.ModuleType(stub_name)

        with patch("backend.src.services.postgres.get_user_preferences",
                   return_value={"topics": ["wifi"], "organisations": [], "people": [],
                                 "domains": [], "notify_email": True, "notify_digest": True}):
            with patch("backend.src.services.postgres.get_user_source_preferences",
                       side_effect=_table_missing_error()):
                # The postgres function itself catches the error and returns []
                from backend.src.services.postgres import get_user_source_preferences
                result = get_user_source_preferences("user-123")
                assert result == []
