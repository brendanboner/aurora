"""Auth service settings configuration."""

from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


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
    content_creator_service_url: str
    oracle_service_url: str
    
    # Application Configuration
    # Single base domain that derives APPLICATION_URL and COOKIE_DOMAIN
    deployment_domain: str  # e.g., "app.example.com" or "d123.cloudfront.net"
    use_https: bool = True  # Whether to use HTTPS (false only for testing)
    
    # Optional overrides (use only if you need custom values)
    application_url: Optional[str] = None
    cookie_domain: Optional[str] = None
    cookie_secure: Optional[bool] = None
    
    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    
    # Derived properties
    @property
    def effective_application_url(self) -> str:
        """Get the application URL - either explicit or derived from deployment_domain"""
        if self.application_url:
            return self.application_url
        
        protocol = "https" if self.use_https else "http"
        return f"{protocol}://{self.deployment_domain}"
    
    @property
    def effective_cookie_domain(self) -> str:
        """Get the cookie domain - either explicit or derived from deployment_domain"""
        if self.cookie_domain:
            return self.cookie_domain
        
        # For localhost testing, use localhost
        if "localhost" in self.deployment_domain or "127.0.0.1" in self.deployment_domain:
            return "localhost"
        
        return self.deployment_domain
    
    @property
    def effective_cookie_secure(self) -> bool:
        """Get cookie_secure setting - either explicit or derived from use_https"""
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.use_https
    
    # Computed properties
    @property
    def cognito_issuer(self) -> str:
        return f"https://cognito-idp.{self.aws_region}.amazonaws.com/{self.cognito_user_pool_id}"
    
    @property
    def oauth_redirect_uri(self) -> str:
        """Dynamically construct redirect URI"""
        app_url = self.effective_application_url
        
        # For local development, use port 8000 (auth service port)
        if "localhost" in app_url:
            return "http://localhost/api/auth/callback"
        # For production, use the application URL + /api path
        return f"{app_url.replace('http://', 'https://')}/api/auth/callback"
    
    @property
    def validated_cookie_domain(self) -> str:
        """Validate and return cookie domain"""
        domain = self.effective_cookie_domain
        
        # Prevent overly broad wildcard domains
        if domain.startswith('.'):
            raise ValueError("Cookie domain should not start with '.' - this allows subdomains which may be insecure")
        
        # Prevent secure cookies on localhost (they won't work)
        if domain == 'localhost' and self.effective_cookie_secure:
            raise ValueError("Cannot use secure cookies with localhost. Set USE_HTTPS=false or COOKIE_SECURE=false for development")
        
        return domain
    
    class Config:
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
