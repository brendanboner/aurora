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
    rabbitmq_password: str = "password"
    rabbitmq_queue: str = "scraped_content"
    
    # Redis Configuration
    redis_host: str = "redis"
    redis_port: int = 6379
    
    # Neo4j Configuration
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_database: str = "neo4j"
    
    # Scraper Configuration
    scraper_delay: float = 0.5  # Delay between requests in seconds
    scraper_max_redirects: int = 10
    scraper_max_resources: int = -1  # Maximum number of resources to scrape per run (-1 = unlimited)
    
    # Output Configuration
    output_mode: str = "rabbitmq"  # Options: "rabbitmq" or "json"
    json_output_file: str = "{scraper}_test_messages.json"  # Default uses scraper name; can override via env var
    
    # Logging
    log_level: str = "INFO"
    
    # API Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    
    # Scheduler Configuration
    scrape_schedule_hour: int = 2  # Hour to run daily scrape (0-23)
    scrape_schedule_minute: int = 0  # Minute to run daily scrape (0-59)


settings = Settings()
