"""Auth service settings configuration."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # AWS Cognito
    aws_region: str
    cognito_user_pool_id: str
    cognito_app_client_id: str
    cognito_app_client_secret: str
    cognito_domain: str
    cognito_jwks_url: str
    cognito_token_endpoint: str
    
    # Service URLs
    backend_service_url: str
    curator_service_url: str
    retriever_service_url: str
    
    # Application
    application_url: str
    cookie_domain: str
    cookie_secure: bool = True
    
    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    
    # Computed properties
    @property
    def cognito_issuer(self) -> str:
        return f"https://cognito-idp.{self.aws_region}.amazonaws.com/{self.cognito_user_pool_id}"
    
    @property
    def oauth_redirect_uri(self) -> str:
        """Dynamically construct redirect URI"""
        # For local development, use port 8000 (auth service port)
        if "localhost" in self.application_url:
            return "http://localhost:8000/api/auth/callback"
        # For production, use the application URL + /api path
        return f"{self.application_url.replace('http://', 'https://')}/api/auth/callback"
    
    @property
    def validated_cookie_domain(self) -> str:
        """Validate and return cookie domain"""
        domain = self.cookie_domain
        
        # Prevent overly broad wildcard domains
        if domain.startswith('.'):
            raise ValueError("Cookie domain should not start with '.' - this allows subdomains which may be insecure")
        
        # Prevent secure cookies on localhost (they won't work)
        if domain == 'localhost' and self.cookie_secure:
            raise ValueError("Cannot use secure cookies with localhost. Set COOKIE_SECURE=false for development")
        
        return domain
    
    class Config:
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
