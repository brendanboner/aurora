"""Tests for OAuth and JWT validation utilities."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException
from utils.oauth import (
    get_jwks,
    validate_jwt_token,
    exchange_code_for_tokens,
    refresh_access_token,
    extract_user_info,
    validate_user_group
)


class TestGetJWKS:
    """Test JWKS fetching and caching."""
    
    @pytest.mark.asyncio
    async def test_get_jwks_success(self, mock_jwks):
        """Test successful JWKS fetch."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json = MagicMock(return_value=mock_jwks)  # json() is sync in httpx
            mock_response.raise_for_status = MagicMock()
            
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            
            result = await get_jwks()
            assert result == mock_jwks
    
    @pytest.mark.asyncio
    async def test_get_jwks_caching(self, mock_jwks):
        """Test that JWKS is cached after first fetch."""
        # Clear cache
        import utils.oauth as oauth_module
        oauth_module._jwks_cache = None
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json = MagicMock(return_value=mock_jwks)  # json() is sync in httpx
            mock_response.raise_for_status = MagicMock()
            
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            
            # First call - should fetch
            result1 = await get_jwks()
            assert result1 == mock_jwks
            
            # Second call - should use cache (no new HTTP call)
            result2 = await get_jwks()
            assert result2 == mock_jwks
            assert mock_client.call_count == 1  # Only called once


class TestValidateJWTToken:
    """Test JWT token validation."""
    
    @pytest.mark.asyncio
    async def test_validate_valid_token(self, valid_token_claims, mock_jwks):
        """Test validation of a valid token."""
        mock_token = "mock.jwt.token"
        
        with patch('utils.oauth.get_jwks', return_value=mock_jwks), \
             patch('jose.jwt.get_unverified_headers', return_value={"kid": "test-key-id"}), \
             patch('jose.jwt.decode', return_value=valid_token_claims):
            
            result = await validate_jwt_token(mock_token)
            assert result == valid_token_claims
    
    @pytest.mark.asyncio
    async def test_validate_expired_token(self, expired_token_claims, mock_jwks):
        """Test validation fails for expired token."""
        mock_token = "expired.jwt.token"
        
        with patch('utils.oauth.get_jwks', return_value=mock_jwks), \
             patch('jose.jwt.get_unverified_headers', return_value={"kid": "test-key-id"}), \
             patch('jose.jwt.decode', return_value=expired_token_claims):
            
            with pytest.raises(HTTPException) as exc_info:
                await validate_jwt_token(mock_token)
            
            assert exc_info.value.status_code == 401
            assert "expired" in exc_info.value.detail.lower()
    
    @pytest.mark.asyncio
    async def test_validate_token_invalid_kid(self, mock_jwks):
        """Test validation fails when key ID not found."""
        mock_token = "mock.jwt.token"
        
        with patch('utils.oauth.get_jwks', return_value=mock_jwks), \
             patch('jose.jwt.get_unverified_headers', return_value={"kid": "wrong-key-id"}):
            
            with pytest.raises(HTTPException) as exc_info:
                await validate_jwt_token(mock_token)
            
            assert exc_info.value.status_code == 401


class TestExchangeCodeForTokens:
    """Test authorization code exchange."""
    
    @pytest.mark.asyncio
    async def test_exchange_code_success(self, mock_cognito_tokens):
        """Test successful code exchange."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = MagicMock(return_value=mock_cognito_tokens)  # json() is sync in httpx
            
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            result = await exchange_code_for_tokens("test-auth-code")
            assert result == mock_cognito_tokens
    
    @pytest.mark.asyncio
    async def test_exchange_code_failure(self):
        """Test failed code exchange."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.text = "Invalid authorization code"
            
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            with pytest.raises(HTTPException) as exc_info:
                await exchange_code_for_tokens("invalid-code")
            
            assert exc_info.value.status_code == 400


class TestRefreshAccessToken:
    """Test token refresh."""
    
    @pytest.mark.asyncio
    async def test_refresh_token_success(self):
        """Test successful token refresh."""
        new_tokens = {"access_token": "new-access-token"}
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = MagicMock(return_value=new_tokens)  # json() is sync in httpx
            
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            result = await refresh_access_token("valid-refresh-token")
            assert result == new_tokens
    
    @pytest.mark.asyncio
    async def test_refresh_token_expired(self):
        """Test refresh with expired refresh token."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 401
            
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            with pytest.raises(HTTPException) as exc_info:
                await refresh_access_token("expired-refresh-token")
            
            assert exc_info.value.status_code == 401


class TestExtractUserInfo:
    """Test user info extraction."""
    
    def test_extract_user_info_complete(self):
        """Test extracting complete user info."""
        claims = {
            "sub": "user-123",
            "email": "test@example.com",
            "custom:role": "admin"
        }
        
        result = extract_user_info(claims)
        assert result["id"] == "user-123"
        assert result["email"] == "test@example.com"
        assert result["role"] == "admin"
    
    def test_extract_user_info_default_role(self):
        """Test default role when not provided."""
        claims = {
            "sub": "user-123",
            "email": "test@example.com"
        }
        
        result = extract_user_info(claims)
        assert result["role"] == "user"    
    def test_extract_user_info_with_groups(self):
        """Test extracting user info with Cognito groups."""
        claims = {
            "sub": "user-123",
            "email": "test@example.com",
            "custom:role": "admin",
            "cognito:groups": ["aurora-users", "admin-group"]
        }
        
        result = extract_user_info(claims)
        assert result["id"] == "user-123"
        assert result["email"] == "test@example.com"
        assert result["role"] == "admin"
        assert result["groups"] == ["aurora-users", "admin-group"]
    
    def test_extract_user_info_no_groups(self):
        """Test extracting user info when no groups claim exists."""
        claims = {
            "sub": "user-123",
            "email": "test@example.com",
            "custom:role": "user"
        }
        
        result = extract_user_info(claims)
        assert result["id"] == "user-123"
        assert result["groups"] == []  # Default to empty list


class TestValidateUserGroup:
    """Test group-based access control."""
    
    def test_validate_user_group_success(self):
        """Test successful group validation."""
        user_info = {
            "id": "user-123",
            "email": "test@example.com",
            "role": "user",
            "groups": ["aurora-users", "other-group"]
        }
        
        # Should not raise any exception
        validate_user_group(user_info, ["aurora-users"])
    
    def test_validate_user_group_failure(self):
        """Test group validation failure when user not in group."""
        user_info = {
            "id": "user-123",
            "email": "test@example.com",
            "role": "user",
            "groups": ["some-other-group"]
        }
        
        with pytest.raises(HTTPException) as exc_info:
            validate_user_group(user_info, ["aurora-users"])
        
        assert exc_info.value.status_code == 403
        assert "aurora-users" in str(exc_info.value.detail)
    
    def test_validate_user_group_no_groups(self):
        """Test group validation when user has no groups."""
        user_info = {
            "id": "user-123",
            "email": "test@example.com",
            "role": "user",
            "groups": []
        }
        
        with pytest.raises(HTTPException) as exc_info:
            validate_user_group(user_info, ["aurora-users"])
        
        assert exc_info.value.status_code == 403
    
    def test_validate_user_group_missing_groups_key(self):
        """Test group validation when groups key is missing."""
        user_info = {
            "id": "user-123",
            "email": "test@example.com",
            "role": "user"
            # No groups key
        }
        
        with pytest.raises(HTTPException) as exc_info:
            validate_user_group(user_info, ["aurora-users"])
        
        assert exc_info.value.status_code == 403