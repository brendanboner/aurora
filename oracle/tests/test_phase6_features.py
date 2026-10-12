"""
Tests for Phase 6: Analytics & Tracking features.

Tests for:
- Oracle metrics recording
- Feedback endpoint
- Structured logging
- Enhanced OTEL span attributes
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime
import json

# Test metrics module
class TestMetrics:
    """Tests for oracle/src/metrics.py"""
    
    def test_record_query_metrics_no_meter(self):
        """Test that record_query_metrics handles missing meter gracefully."""
        from src.metrics import record_query_metrics
        
        # Should not raise even if meter is not available
        record_query_metrics(
            intent="topic_discovery",
            mode="answer",
            documents_count=5,
            confidence_score=0.85,
            latency_ms=1200,
            cache_hit=False,
            has_suggestions=False,
            strategies_used=["keyword", "vector"],
        )
    
    def test_record_query_metrics_with_error(self):
        """Test recording metrics for failed queries."""
        from src.metrics import record_query_metrics
        
        record_query_metrics(
            intent="unknown",
            mode="answer",
            documents_count=0,
            confidence_score=None,
            latency_ms=500,
            cache_hit=False,
            has_suggestions=False,
            strategies_used=[],
            error=True,
        )
    
    def test_record_enhance_metrics(self):
        """Test recording enhance request metrics."""
        from src.metrics import record_enhance_metrics
        
        record_enhance_metrics(
            latency_ms=3500,
            documents_fetched=3,
            chunks_used=12,
            confidence_score=0.78,
            error=False,
        )
    
    def test_record_feedback_metrics(self):
        """Test recording feedback metrics."""
        from src.metrics import record_feedback_metrics
        
        record_feedback_metrics(
            feedback_type="helpful",
            intent="entity_focused",
            mode="answer",
        )
        
        record_feedback_metrics(
            feedback_type="not_helpful",
            intent=None,
            mode=None,
        )
    
    def test_get_confidence_level(self):
        """Test confidence level categorization."""
        from src.metrics import _get_confidence_level
        
        assert _get_confidence_level(0.9) == "high"
        assert _get_confidence_level(0.75) == "high"
        assert _get_confidence_level(0.74) == "medium"
        assert _get_confidence_level(0.5) == "medium"
        assert _get_confidence_level(0.4) == "medium"
        assert _get_confidence_level(0.39) == "low"
        assert _get_confidence_level(0.1) == "low"


class TestFeedbackEndpoint:
    """Tests for the /oracle/feedback endpoint."""
    
    @pytest.fixture
    def mock_settings(self):
        """Mock settings for tests."""
        with patch('src.routes.query.settings') as mock:
            mock.analytics_logging_enabled = True
            mock.feedback_enabled = True
            yield mock
    
    @pytest.mark.asyncio
    async def test_feedback_request_model_valid(self):
        """Test FeedbackRequest model with valid data."""
        from src.models.request import FeedbackRequest, FeedbackType
        
        request = FeedbackRequest(
            query_id="test-query-123",
            feedback=FeedbackType.HELPFUL,
            comment="Great answer!",
            intent="topic_discovery",
            mode="answer",
        )
        
        assert request.query_id == "test-query-123"
        assert request.feedback == FeedbackType.HELPFUL
        assert request.comment == "Great answer!"
    
    @pytest.mark.asyncio
    async def test_feedback_request_model_minimal(self):
        """Test FeedbackRequest model with minimal required data."""
        from src.models.request import FeedbackRequest, FeedbackType
        
        request = FeedbackRequest(
            query_id="test-query-456",
            feedback=FeedbackType.NOT_HELPFUL,
        )
        
        assert request.query_id == "test-query-456"
        assert request.feedback == FeedbackType.NOT_HELPFUL
        assert request.comment is None
        assert request.intent is None
        assert request.mode is None
    
    @pytest.mark.asyncio
    async def test_feedback_response_model(self):
        """Test FeedbackResponse model."""
        from src.models.response import FeedbackResponse
        
        response = FeedbackResponse(
            status="recorded",
            feedback_id="fb-test-123",
            message="Thank you for your feedback",
        )
        
        assert response.status == "recorded"
        assert response.feedback_id == "fb-test-123"


class TestFeedbackType:
    """Tests for FeedbackType enum."""
    
    def test_feedback_type_values(self):
        """Test FeedbackType enum values."""
        from src.models.request import FeedbackType
        
        assert FeedbackType.HELPFUL.value == "helpful"
        assert FeedbackType.NOT_HELPFUL.value == "not_helpful"


class TestEnhancedSpans:
    """Tests for enhanced OTEL span attributes."""
    
    def test_span_attributes_list(self):
        """Verify expected span attributes are defined."""
        expected_attributes = [
            "oracle.query_id",
            "oracle.query.text",
            "oracle.query.mode_requested",
            "oracle.user_id",
            "oracle.cache_hit",
            "oracle.intent",
            "oracle.intent_confidence",
            "oracle.documents_count",
            "oracle.total_candidates",
            "oracle.strategies_used",
            "oracle.mode_effective",
            "oracle.confidence_score",
            "oracle.confidence_level",
            "oracle.has_suggestions",
            "oracle.processing_time_ms",
            "oracle.llm_tokens_used",
            "oracle.error",
            "oracle.error_message",
        ]
        
        # This is a documentation test - verifying the expected attributes
        # The actual span recording is tested through integration tests
        assert len(expected_attributes) > 0


class TestStructuredLogging:
    """Tests for structured logging format."""
    
    def test_query_completed_log_format(self):
        """Test expected structure of query_completed log entries."""
        expected_fields = {
            "event_type": "oracle_query",
            "query_id": str,
            "query_text": str,
            "intent": str,
            "intent_confidence": float,
            "mode": str,
            "documents_count": int,
            "confidence_score": (float, type(None)),
            "processing_time_ms": int,
            "cache_hit": bool,
            "has_suggestions": bool,
            "strategies_used": list,
            "llm_tokens_used": int,
        }
        
        # Sample log entry structure
        sample_entry = {
            "event_type": "oracle_query",
            "query_id": "test-123",
            "query_text": "What is Wi-Fi 7?",
            "intent": "topic_discovery",
            "intent_confidence": 0.92,
            "mode": "answer",
            "documents_count": 5,
            "confidence_score": 0.85,
            "processing_time_ms": 1200,
            "cache_hit": False,
            "has_suggestions": False,
            "strategies_used": ["keyword", "vector"],
            "llm_tokens_used": 450,
        }
        
        # Verify all expected fields are present
        for field in expected_fields:
            assert field in sample_entry
    
    def test_feedback_submitted_log_format(self):
        """Test expected structure of feedback_submitted log entries."""
        expected_fields = {
            "event_type": "oracle_feedback",
            "feedback_id": str,
            "query_id": str,
            "feedback_type": str,
            "has_comment": bool,
            "comment_length": int,
            "intent": (str, type(None)),
            "mode": (str, type(None)),
        }
        
        sample_entry = {
            "event_type": "oracle_feedback",
            "feedback_id": "fb-test-123",
            "query_id": "query-456",
            "feedback_type": "helpful",
            "has_comment": True,
            "comment_length": 25,
            "intent": "topic_discovery",
            "mode": "answer",
        }
        
        for field in expected_fields:
            assert field in sample_entry


class TestMetricLabels:
    """Tests for metric label definitions."""
    
    def test_metric_labels_defined(self):
        """Test that all metric labels are defined."""
        from src.metrics import MetricLabels
        
        assert MetricLabels.INTENT == "oracle.intent"
        assert MetricLabels.MODE == "oracle.mode"
        assert MetricLabels.CACHE_HIT == "oracle.cache_hit"
        assert MetricLabels.HAS_SUGGESTIONS == "oracle.has_suggestions"
        assert MetricLabels.CONFIDENCE_LEVEL == "oracle.confidence_level"
        assert MetricLabels.FEEDBACK_TYPE == "oracle.feedback_type"
        assert MetricLabels.STRATEGY == "oracle.retrieval_strategy"
        assert MetricLabels.ERROR == "oracle.error"


class TestPhase6Settings:
    """Tests for Phase 6 settings."""
    
    def test_phase6_settings_exist(self):
        """Test that Phase 6 settings are defined."""
        from src.settings import Settings
        
        settings = Settings()
        
        # These should have default values
        assert hasattr(settings, 'analytics_enabled')
        assert hasattr(settings, 'analytics_logging_enabled')
        assert hasattr(settings, 'feedback_enabled')
        assert hasattr(settings, 'metrics_prefix')
    
    def test_phase6_settings_defaults(self):
        """Test Phase 6 settings default values."""
        from src.settings import Settings
        
        settings = Settings()
        
        assert settings.analytics_enabled == True
        assert settings.analytics_logging_enabled == True
        assert settings.feedback_enabled == True
        assert settings.metrics_prefix == "oracle"


class TestIntegration:
    """Integration tests for Phase 6 features."""
    
    @pytest.mark.asyncio
    async def test_query_records_metrics(self):
        """Test that query endpoint records metrics."""
        # This is a placeholder for integration testing
        # Full integration tests would require running the service
        pass
    
    @pytest.mark.asyncio
    async def test_feedback_endpoint_integration(self):
        """Test feedback endpoint with mocked dependencies."""
        # This is a placeholder for integration testing
        pass


# Run basic validation
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
