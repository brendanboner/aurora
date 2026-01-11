"""Tests for Oracle Service API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock

from src.api import app


class TestHealthEndpoint:
    """Tests for /health endpoint."""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    def test_health_returns_200(self, client):
        """Test that health endpoint returns 200."""
        # Mock the Neo4j check to avoid connection issues in tests
        with patch('src.routes.health.check_neo4j', return_value="ok"):
            with patch('src.routes.health.check_llm', return_value="ok"):
                response = client.get("/health")
                
                assert response.status_code == 200
    
    def test_health_returns_status(self, client):
        """Test that health returns status field."""
        with patch('src.routes.health.check_neo4j', return_value="ok"):
            with patch('src.routes.health.check_llm', return_value="ok"):
                response = client.get("/health")
                data = response.json()
                
                assert "status" in data
                assert data["status"] in ["healthy", "degraded", "unhealthy"]
    
    def test_health_returns_checks(self, client):
        """Test that health returns individual checks."""
        with patch('src.routes.health.check_neo4j', return_value="ok"):
            with patch('src.routes.health.check_llm', return_value="not_configured"):
                response = client.get("/health")
                data = response.json()
                
                assert "checks" in data
                assert "neo4j" in data["checks"]
                assert "llm" in data["checks"]
    
    def test_health_degraded_when_llm_not_configured(self, client):
        """Test that health is degraded when LLM not configured."""
        with patch('src.routes.health.check_neo4j', return_value="ok"):
            with patch('src.routes.health.check_llm', return_value="not_configured"):
                response = client.get("/health")
                data = response.json()
                
                assert data["status"] == "degraded"
    
    def test_health_unhealthy_when_neo4j_fails(self, client):
        """Test that health is unhealthy when Neo4j fails."""
        with patch('src.routes.health.check_neo4j', return_value="error: connection refused"):
            with patch('src.routes.health.check_llm', return_value="ok"):
                response = client.get("/health")
                data = response.json()
                
                assert data["status"] == "unhealthy"


class TestRootEndpoint:
    """Tests for root endpoint."""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    def test_root_returns_200(self, client):
        """Test that root endpoint returns 200."""
        response = client.get("/")
        
        assert response.status_code == 200
    
    def test_root_returns_service_info(self, client):
        """Test that root returns service information."""
        response = client.get("/")
        data = response.json()
        
        assert data["service"] == "oracle"
        assert "version" in data


class TestQueryEndpoint:
    """Tests for /query endpoint."""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    def test_query_requires_authentication(self, client):
        """Test that query endpoint requires user context."""
        response = client.post(
            "/query",
            json={
                "user_id": "test-user-123",
                "question": "What's new in Wi-Fi 7?",
                "mode": "retrieval"
            }
        )
        
        # Without auth headers, should get 401
        assert response.status_code == 401
    
    def test_query_with_auth_headers(self, client):
        """Test query with authentication headers."""
        # Mock all the services to avoid external dependencies
        with patch('src.routes.query.query_router.classify_intent', new_callable=AsyncMock) as mock_router:
            with patch('src.routes.query.query_parser.parse', new_callable=AsyncMock) as mock_parser:
                with patch('src.routes.query.keyword_retriever.retrieve', new_callable=AsyncMock) as mock_retriever:
                    with patch('src.routes.query.context_builder.build', new_callable=AsyncMock) as mock_context:
                        with patch('src.routes.query.response_generator.generate_answer', new_callable=AsyncMock) as mock_generator:
                            # Setup mocks
                            from src.services.query_router import IntentResult
                            from src.services.query_parser import ParsedQuery
                            from src.services.keyword_retriever import RetrievalResult
                            from src.services.response_generator import AnswerResult
                            from src.models.response import QueryIntent, GraphContext
                            
                            mock_router.return_value = IntentResult(
                                intent=QueryIntent.TOPIC_DISCOVERY,
                                confidence=0.9,
                                entities_detected=["Wi-Fi 7"],
                                requires_temporal=True,
                                requires_graph_traversal=False,
                                tokens_used=50
                            )
                            
                            mock_parser.return_value = ParsedQuery(
                                topics=["Wi-Fi 7"],
                                organizations=[],
                                people=[],
                                start_date=None,
                                end_date=None,
                                category=None,
                                doc_type=None,
                                keywords=[],
                                tokens_used=100
                            )
                            
                            mock_retriever.return_value = RetrievalResult(
                                documents=[],
                                total_candidates=0
                            )
                            
                            mock_context.return_value = GraphContext(
                                central_topics=[],
                                key_organizations=[],
                                key_people=[],
                                related_entities=[],
                                temporal_patterns=None
                            )
                            
                            mock_generator.return_value = AnswerResult(
                                answer="No documents found.",
                                citations=[],
                                confidence_score=0.5,
                                tokens_used=0
                            )
                            
                            response = client.post(
                                "/query",
                                json={
                                    "user_id": "test-user-123",
                                    "question": "What's new in Wi-Fi 7?",
                                    "mode": "answer"
                                },
                                headers={
                                    "X-User-ID": "test-user-123",
                                    "X-User-Email": "test@example.com"
                                }
                            )
                            
                            assert response.status_code == 200
                            data = response.json()
                            assert "mode" in data
                            assert "documents" in data
                            assert "metadata" in data
    
    def test_query_validates_request(self, client):
        """Test that query validates request body."""
        response = client.post(
            "/query",
            json={
                "user_id": "test-user-123"
                # Missing required 'question' field
            },
            headers={
                "X-User-ID": "test-user-123",
                "X-User-Email": "test@example.com"
            }
        )
        
        assert response.status_code == 422  # Validation error
    
    def test_query_rejects_empty_question(self, client):
        """Test that empty question is rejected."""
        response = client.post(
            "/query",
            json={
                "user_id": "test-user-123",
                "question": "",  # Empty question
                "mode": "retrieval"
            },
            headers={
                "X-User-ID": "test-user-123",
                "X-User-Email": "test@example.com"
            }
        )
        
        assert response.status_code == 422


class TestOpenAPIDocumentation:
    """Tests for API documentation endpoints."""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    def test_openapi_json_available(self, client):
        """Test that OpenAPI JSON is available."""
        response = client.get("/openapi.json")
        
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data
    
    def test_docs_available(self, client):
        """Test that Swagger docs are available."""
        response = client.get("/docs")
        
        assert response.status_code == 200
