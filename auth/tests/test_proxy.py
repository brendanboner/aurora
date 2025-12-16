"""Tests for request proxying."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException, Request
from services.proxy import get_target_service_url, proxy_request


class TestGetTargetServiceURL:
    """Test URL routing logic."""
    
    def test_backend_route(self):
        """Test routing to backend service."""
        url = get_target_service_url("/api/backend/query")
        assert url == "http://backend:8000/query"
    
    def test_curator_route(self):
        """Test routing to curator service."""
        url = get_target_service_url("/api/curator/analyze")
        assert url == "http://curator:8000/analyze"
    
    def test_retriever_route(self):
        """Test routing to retriever service."""
        url = get_target_service_url("/api/retriever/documents")
        assert url == "http://retriever:8000/documents"
    
    def test_unknown_route(self):
        """Test routing fails for unknown service."""
        with pytest.raises(HTTPException) as exc_info:
            get_target_service_url("/api/unknown/endpoint")
        
        assert exc_info.value.status_code == 404


class TestProxyRequest:
    """Test request proxying."""
    
    @pytest.mark.asyncio
    async def test_proxy_success(self):
        """Test successful request proxy."""
        mock_request = MagicMock(spec=Request)
        mock_request.method = "GET"
        mock_request.url.path = "/api/backend/query"
        mock_request.headers = {"Host": "localhost"}
        mock_request.body = AsyncMock(return_value=b"")
        mock_request.query_params = {}
        
        user_info = {
            "user_id": "user-123",
            "email": "test@example.com",
            "role": "user"
        }
        
        mock_response = MagicMock()
        mock_response.content = b'{"result": "success"}'
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client_instance = mock_client.return_value.__aenter__.return_value
            mock_client_instance.request = AsyncMock(return_value=mock_response)
            
            response = await proxy_request(mock_request, user_info)
            
            assert response.status_code == 200
            assert response.body == b'{"result": "success"}'
            
            # Verify user context headers were added
            call_args = mock_client_instance.request.call_args
            headers = call_args.kwargs['headers']
            assert headers["X-User-Id"] == "user-123"
            assert headers["X-User-Email"] == "test@example.com"
            assert headers["X-User-Role"] == "user"
    
    @pytest.mark.asyncio
    async def test_proxy_service_unavailable(self):
        """Test proxy when service is unavailable."""
        mock_request = MagicMock(spec=Request)
        mock_request.method = "GET"
        mock_request.url.path = "/api/backend/query"
        mock_request.headers = {}
        mock_request.body = AsyncMock(return_value=b"")
        mock_request.query_params = {}
        
        user_info = {"user_id": "user-123", "email": "test@example.com", "role": "user"}
        
        import httpx
        with patch('httpx.AsyncClient') as mock_client:
            mock_client_instance = mock_client.return_value.__aenter__.return_value
            mock_client_instance.request = AsyncMock(side_effect=httpx.RequestError("Connection refused"))
            
            with pytest.raises(HTTPException) as exc_info:
                await proxy_request(mock_request, user_info)
            
            assert exc_info.value.status_code == 503
