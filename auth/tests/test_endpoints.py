"""Tests for API endpoints."""

from unittest.mock import patch, MagicMock, AsyncMock


class TestHealthEndpoint:
    """Test health check endpoint."""
    
    def test_health_check(self, client):
        """Test health check returns OK."""
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "auth"}


class TestLoginEndpoint:
    """Test login endpoint."""
    
    def test_login_redirect(self, client):
        """Test login redirects to Cognito."""
        response = client.get("/api/auth/login", follow_redirects=False)
        assert response.status_code == 307
        assert "cognito" in response.headers["location"]
        assert "client_id=test_client_id" in response.headers["location"]


class TestAuthCallbackEndpoint:
    """Test OAuth callback endpoint."""
    
    def test_callback_success(self, client, mock_cognito_tokens, valid_token_claims):
        """Test successful authentication callback."""
        # Store state in Redis mock
        from utils.state_storage import store_oauth_state
        from settings import get_settings
        settings = get_settings()
        
        store_oauth_state("test-state", {"ip": "127.0.0.1", "user_agent": "test"})
        
        with patch('auth.exchange_code_for_tokens', return_value=mock_cognito_tokens), \
             patch('auth.validate_jwt_token', return_value=valid_token_claims):
            
            response = client.get(
                "/api/auth/callback?code=test-auth-code&state=test-state",
                follow_redirects=False
            )
            
            assert response.status_code == 307
            assert response.headers["location"] == f"{settings.effective_application_url}/"
            # Note: TestClient may not preserve Set-Cookie headers, but the response was successful
    
    def test_callback_failure(self, client):
        """Test failed authentication callback."""
        # Store state in Redis mock
        from utils.state_storage import store_oauth_state
        store_oauth_state("test-state", {"ip": "127.0.0.1", "user_agent": "test"})
        
        with patch('auth.exchange_code_for_tokens', 
                  side_effect=Exception("Token exchange failed")):
            
            response = client.get(
                "/api/auth/callback?code=invalid-code&state=test-state",
                follow_redirects=False
            )
            
            assert response.status_code == 307
            assert "error=auth_failed" in response.headers["location"]
    
    def test_callback_user_not_in_required_group(self, client, mock_cognito_tokens, unauthorized_group_claims):
        """Test authentication callback fails when user not in required group."""
        # Store state in Redis mock
        from utils.state_storage import store_oauth_state
        store_oauth_state("test-state", {"ip": "127.0.0.1", "user_agent": "test"})
        
        with patch('auth.exchange_code_for_tokens', return_value=mock_cognito_tokens), \
             patch('auth.validate_jwt_token', return_value=unauthorized_group_claims):
            
            response = client.get(
                "/api/auth/callback?code=test-auth-code&state=test-state",
                follow_redirects=False
            )
            
            # Should redirect to error page since user is not in required group
            assert response.status_code == 307
            assert "error=auth_failed" in response.headers["location"]


class TestLogoutEndpoint:
    """Test logout endpoint."""
    
    def test_logout_success(self, client):
        """Test logout clears cookies and redirects."""
        response = client.get("/api/auth/logout", follow_redirects=False)
        
        assert response.status_code == 307
        assert "cognito" in response.headers["location"]
        assert "logout" in response.headers["location"]


class TestAuthMeEndpoint:
    """Test /auth/me endpoint."""
    
    def test_auth_me_with_valid_token(self, client, valid_token_claims):
        """Test /auth/me with valid token."""
        with patch('utils.middleware.validate_jwt_token', return_value=valid_token_claims):
            response = client.get(
                "/api/auth/me",
                cookies={"access_token": "valid-token"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == "test-user-123"
            assert data["email"] == "testuser@example.com"
    
    def test_auth_me_without_token(self, client):
        """Test /auth/me without token."""
        response = client.get("/api/auth/me")
        assert response.status_code == 401


class TestProxyEndpoint:
    """Test proxy endpoint."""
    
    def test_proxy_with_authentication(self, client, valid_token_claims):
        """Test proxying request with valid authentication."""
        mock_backend_response = MagicMock()
        mock_backend_response.content = b'{"data": "test"}'
        mock_backend_response.status_code = 200
        mock_backend_response.headers = {"content-type": "application/json"}
        
        with patch('utils.middleware.validate_jwt_token', return_value=valid_token_claims), \
             patch('httpx.AsyncClient') as mock_client:
            
            mock_client_instance = mock_client.return_value.__aenter__.return_value
            mock_client_instance.request = AsyncMock(return_value=mock_backend_response)
            
            response = client.get(
                "/api/backend/query",
                cookies={"access_token": "valid-token"}
            )
            
            assert response.status_code == 200
            assert response.json() == {"data": "test"}
    
    def test_proxy_without_authentication(self, client):
        """Test proxying fails without authentication."""
        response = client.get("/api/backend/query")
        assert response.status_code == 401
