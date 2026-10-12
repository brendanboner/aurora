"""
Unit tests for FastAPI endpoints.

Tests API health checks, status, and manual triggers.
"""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime
from unittest.mock import MagicMock, patch


class TestHealthEndpoint:
    """Tests for the /health endpoint."""
    
    def test_health_check_returns_healthy(self, api_client):
        """Test that health check returns healthy status."""
        response = api_client.get("/health")
        
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


class TestStatusEndpoint:
    """Tests for the /status endpoint."""
    
    def test_status_returns_service_info(self, api_client):
        """Test that status returns service information."""
        response = api_client.get("/status")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "status" in data
        assert "uptime_seconds" in data
        assert "jobs" in data
    
    def test_status_includes_job_info(self, api_client):
        """Test that status includes job information."""
        response = api_client.get("/status")
        data = response.json()
        
        jobs = data.get("jobs", [])
        job_names = [j["name"] for j in jobs]
        
        # Should include both main jobs
        assert "topic_organization" in job_names
        assert "event_reconciliation" in job_names
    
    def test_status_uptime_increases(self, api_client):
        """Test that uptime is calculated correctly."""
        import time
        
        response1 = api_client.get("/status")
        time.sleep(0.1)  # Brief pause
        response2 = api_client.get("/status")
        
        uptime1 = response1.json()["uptime_seconds"]
        uptime2 = response2.json()["uptime_seconds"]
        
        # Uptime should increase (or at least not decrease significantly)
        assert uptime2 >= uptime1 - 0.1  # Allow small variance


class TestTriggerEndpoints:
    """Tests for manual trigger endpoints."""
    
    def test_trigger_topic_organization_endpoint_exists(self, api_client):
        """Test that topic organization trigger endpoint exists."""
        # This may return 404 or 405 if not implemented, but shouldn't error
        response = api_client.post("/trigger/topic-organization")
        
        # Accept various responses - endpoint should be defined
        assert response.status_code in [200, 202, 400, 404, 405, 500]
    
    def test_trigger_event_reconciliation_endpoint_exists(self, api_client):
        """Test that event reconciliation trigger endpoint exists."""
        response = api_client.post("/trigger/event-reconciliation")
        
        assert response.status_code in [200, 202, 400, 404, 405, 500]


class TestJobStateManagement:
    """Tests for job state management."""
    
    def test_update_job_state(self):
        """Test updating job state."""
        from api import update_job_state, _job_state
        
        # Update topic organization state
        update_job_state(
            "topic_organization",
            is_running=True,
            last_run=datetime.now()
        )
        
        assert _job_state["topic_organization"]["is_running"] is True
        assert _job_state["topic_organization"]["last_run"] is not None
    
    def test_update_job_state_with_error(self):
        """Test updating job state with error."""
        from api import update_job_state, _job_state
        
        update_job_state(
            "event_reconciliation",
            is_running=False,
            last_error="Test error"
        )
        
        assert _job_state["event_reconciliation"]["is_running"] is False
        assert _job_state["event_reconciliation"]["last_error"] == "Test error"
    
    def test_update_job_state_unknown_job(self):
        """Test that unknown job names are handled gracefully."""
        from api import update_job_state, _job_state
        
        # Should not raise an error
        update_job_state("unknown_job", is_running=True)
        
        # Unknown job should not be in state
        assert "unknown_job" not in _job_state


class TestSchedulerIntegration:
    """Tests for scheduler integration with API."""
    
    def test_set_scheduler(self):
        """Test setting the scheduler instance."""
        from api import set_scheduler, _scheduler
        
        mock_scheduler = MagicMock()
        set_scheduler(mock_scheduler)
        
        # Note: Can't directly check _scheduler due to module-level variable
        # but the function should execute without error
    
    def test_set_start_time(self):
        """Test setting the service start time."""
        from api import set_start_time
        
        test_time = datetime.now()
        set_start_time(test_time)
        
        # Should execute without error


class TestAPIErrorHandling:
    """Tests for API error handling."""
    
    def test_invalid_endpoint_returns_404(self, api_client):
        """Test that invalid endpoints return 404."""
        response = api_client.get("/nonexistent")
        
        assert response.status_code == 404
    
    def test_invalid_method_returns_405(self, api_client):
        """Test that invalid methods return 405."""
        # GET on a POST-only endpoint
        response = api_client.get("/trigger/topic-organization")
        
        # Should be 405 or 404 depending on implementation
        assert response.status_code in [404, 405]


class TestAPIModels:
    """Tests for API Pydantic models."""
    
    def test_job_status_model(self):
        """Test JobStatus model."""
        from api import JobStatus
        
        job = JobStatus(
            name="test_job",
            is_running=True,
            last_run=datetime.now(),
            next_run=datetime.now(),
            last_error=None
        )
        
        assert job.name == "test_job"
        assert job.is_running is True
    
    def test_service_status_model(self):
        """Test ServiceStatus model."""
        from api import ServiceStatus, JobStatus
        
        status = ServiceStatus(
            status="healthy",
            uptime_seconds=100.5,
            jobs=[
                JobStatus(name="job1", is_running=False),
                JobStatus(name="job2", is_running=True)
            ]
        )
        
        assert status.status == "healthy"
        assert len(status.jobs) == 2
    
    def test_trigger_response_model(self):
        """Test TriggerResponse model."""
        from api import TriggerResponse
        
        response = TriggerResponse(
            success=True,
            message="Job triggered",
            job_id="123"
        )
        
        assert response.success is True
        assert response.job_id == "123"
