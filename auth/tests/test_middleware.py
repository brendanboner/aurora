"""Tests for JWT validation middleware."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException, Request
from utils.middleware import validate_request_token


class TestValidateRequestToken:
    """Test request token validation."""
    
    @pytest.mark.asyncio
    async def test_validate_with_valid_token(self, valid_token_claims):
        """Test validation with valid access token."""
        mock_request = MagicMock(spec=Request)
        mock_request.cookies.get.side_effect = lambda key: {
            "access_token": "valid-token",
            "refresh_token": "refresh-token"
        }.get(key)
        
        with patch('utils.middleware.validate_jwt_token', return_value=valid_token_claims):
            result = await validate_request_token(mock_request)
            
            assert result["id"] == "test-user-123"
            assert result["email"] == "testuser@example.com"
            assert result["role"] == "user"
    
    @pytest.mark.asyncio
    async def test_validate_no_token(self):
        """Test validation fails when no token provided."""
        mock_request = MagicMock(spec=Request)
        mock_request.cookies.get.return_value = None
        
        with pytest.raises(HTTPException) as exc_info:
            await validate_request_token(mock_request)
        
        assert exc_info.value.status_code == 401
        assert "No access token" in exc_info.value.detail
    
    @pytest.mark.asyncio
    async def test_validate_expired_token_with_refresh(self, valid_token_claims):
        """Test automatic token refresh when access token expired."""
        mock_request = MagicMock(spec=Request)
        mock_request.cookies.get.side_effect = lambda key: {
            "access_token": "expired-token",
            "refresh_token": "valid-refresh-token"
        }.get(key)
        mock_request.state = MagicMock()
        
        # First call raises expired error, second and third calls succeed after refresh
        with patch('utils.middleware.validate_jwt_token') as mock_validate:
            mock_validate.side_effect = [
                HTTPException(401, "Token has expired"),
                valid_token_claims,  # Validates new ID token
                valid_token_claims   # In case fallback is needed
            ]
            
            with patch('utils.middleware.refresh_access_token', 
                      return_value={"access_token": "new-token", "id_token": "new-id-token"}):
                result = await validate_request_token(mock_request)
                
                assert result["id"] == "test-user-123"
                assert hasattr(mock_request.state, 'new_access_token')
                assert mock_request.state.new_access_token == "new-token"
                assert hasattr(mock_request.state, 'new_id_token')
                assert mock_request.state.new_id_token == "new-id-token"
    
    @pytest.mark.asyncio
    async def test_validate_expired_token_refresh_fails(self):
        """Test when token refresh also fails."""
        mock_request = MagicMock(spec=Request)
        mock_request.cookies.get.side_effect = lambda key: {
            "access_token": "expired-token",
            "refresh_token": "expired-refresh-token"
        }.get(key)
        
        with patch('utils.middleware.validate_jwt_token', 
                  side_effect=HTTPException(401, "Token has expired")):
            with patch('utils.middleware.refresh_access_token', 
                      side_effect=Exception("Refresh failed")):
                
                with pytest.raises(HTTPException) as exc_info:
                    await validate_request_token(mock_request)
                
                assert exc_info.value.status_code == 401
                assert "Please login again" in exc_info.value.detail
