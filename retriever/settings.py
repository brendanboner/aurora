from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )
    
    # RabbitMQ Configuration
    rabbitmq_host: str = "aurora-rabbitmq"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "user"
    rabbitmq_password: str = "passsword"
    rabbitmq_queue: str = "scraped_content"
    
    # Redis Configuration
    redis_host: str = "redis"
    redis_port: int = 6379
    
    # Scraper Configuration
    scraper_delay: float = 0.5  # Delay between requests in seconds
    scraper_max_redirects: int = 10
    
    # Output Configuration
    output_mode: str = "rabbitmq"  # Options: "rabbitmq" or "json"
    json_output_file: str = "{scraper}_test_messages.json"  # Default uses scraper name; can override via env var
    
    # Logging
    log_level: str = "INFO"
    
    # API Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000


settings = Settings()
