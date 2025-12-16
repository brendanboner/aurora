"""Pytest configuration and shared fixtures."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
import os

# Set test environment variables
os.environ.update({
    "AWS_REGION": "us-east-1",
    "COGNITO_USER_POOL_ID": "us-east-1_TEST",
    "COGNITO_APP_CLIENT_ID": "test_client_id",
    "COGNITO_APP_CLIENT_SECRET": "test_client_secret",
    "COGNITO_DOMAIN": "test.auth.us-east-1.amazoncognito.com",
    "COGNITO_JWKS_URL": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TEST/.well-known/jwks.json",
    "COGNITO_TOKEN_ENDPOINT": "https://test.auth.us-east-1.amazoncognito.com/oauth2/token",
    "BACKEND_SERVICE_URL": "http://backend:8000",
    "CURATOR_SERVICE_URL": "http://curator:8000",
    "RETRIEVER_SERVICE_URL": "http://retriever:8000",
    "APPLICATION_URL": "http://localhost:3000",
    "FRONTEND_URL": "http://localhost:3000",
    "COOKIE_DOMAIN": "localhost",
    "COOKIE_SECURE": "false",
})

from auth import app


@pytest.fixture
def mock_redis():
    """Mock Redis client for testing."""
    redis_data = {}
    
    class MockRedis:
        def setex(self, key: str, ttl: int, value: str):
            """Set key with expiration."""
            redis_data[key] = value
        
        def get(self, key: str):
            """Get value by key."""
            return redis_data.get(key)
        
        def delete(self, key: str):
            """Delete key."""
            redis_data.pop(key, None)
        
        def scan_iter(self, match: str):
            """Scan keys matching pattern."""
            pattern = match.replace('*', '')
            return [k for k in redis_data.keys() if k.startswith(pattern)]
    
    mock_client = MockRedis()
    
    # Patch the Redis client in state_storage module
    with patch('utils.state_storage.get_redis_client', return_value=mock_client):
        yield mock_client
    
    # Clear data after test
    redis_data.clear()


@pytest.fixture
def client(mock_redis):
    """FastAPI test client with mocked Redis."""
    return TestClient(app)


@pytest.fixture
def mock_jwks():
    """Mock JWKS response."""
    return {
        "keys": [
            {
                "kid": "test-key-id",
                "kty": "RSA",
                "alg": "RS256",
                "use": "sig",
                "n": "test-modulus",
                "e": "AQAB"
            }
        ]
    }


@pytest.fixture
def valid_token_claims():
    """Valid JWT token claims."""
    import time
    return {
        "sub": "test-user-123",
        "email": "testuser@example.com",
        "custom:role": "user",
        "exp": int(time.time()) + 3600,  # Expires in 1 hour
        "aud": "test_client_id",
        "iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TEST"
    }


@pytest.fixture
def expired_token_claims():
    """Expired JWT token claims."""
    import time
    return {
        "sub": "test-user-123",
        "email": "testuser@example.com",
        "custom:role": "user",
        "exp": int(time.time()) - 3600,  # Expired 1 hour ago
        "aud": "test_client_id",
        "iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TEST"
    }


@pytest.fixture
def mock_cognito_tokens():
    """Mock Cognito token response."""
    return {
        "access_token": "mock-access-token",
        "id_token": "mock-id-token",
        "refresh_token": "mock-refresh-token",
        "expires_in": 3600,
        "token_type": "Bearer"
    }
